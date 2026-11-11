"""Artwork Overture draws from a title, for collections that have none.

The bundled Noto fonts draw the text, so any script a title uses renders and
the same title and style always give the same bytes.
"""

lazy import io
lazy import unicodedata
lazy from dataclasses import dataclass
lazy from functools import cache, lru_cache
lazy from pathlib import Path

lazy from fontTools.ttLib import TTFont
lazy from PIL import Image, ImageDraw, ImageFont

lazy from ..domain import ArtStyle, ArtType

#: The size each art type is drawn at, as servers display them.
_SIZES = {ArtType.POSTER: (1000, 1500), ArtType.BACKGROUND: (3840, 2160)}
#: The most lines a title wraps to before its size shrinks instead.
_MAX_LINES = 4
_FONT_DIR = Path(__file__).resolve().parent / "fonts"
#: The bundled fonts in the order a character looks for one that draws it.
FONT_FILES = (
    "NotoSans-Regular.ttf",
    "NotoSansArabic-Regular.ttf",
    "NotoSansHebrew-Regular.ttf",
    "NotoSansDevanagari-Regular.ttf",
    "NotoSansThai-Regular.ttf",
    "NotoSansCJKjp-Regular.otf",
    "NotoSansSymbols-Regular.ttf",
    "NotoSansSymbols2-Regular.ttf",
    "NotoEmoji-Regular.ttf",
)
#: Bidirectional classes that make a title read right to left.
_RTL_CLASSES = frozenset({"R", "AL"})

type _Rgb = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class _Palette:
    top: _Rgb
    bottom: _Rgb
    text: _Rgb
    muted: _Rgb
    rule: _Rgb


_PALETTES = {
    ArtStyle.DARK: _Palette(
        top=(28, 30, 38),
        bottom=(11, 12, 16),
        text=(242, 238, 230),
        muted=(158, 154, 146),
        rule=(199, 165, 96),
    ),
    ArtStyle.LIGHT: _Palette(
        top=(248, 245, 238),
        bottom=(226, 219, 205),
        text=(30, 28, 26),
        muted=(108, 102, 94),
        rule=(158, 122, 56),
    ),
    ArtStyle.ACCENT: _Palette(
        top=(186, 150, 86),
        bottom=(112, 82, 38),
        text=(255, 252, 244),
        muted=(244, 232, 210),
        rule=(255, 252, 244),
    ),
}


def _gradient(size: tuple[int, int], palette: _Palette) -> Image.Image:
    """A vertical gradient from the palette's top colour to its bottom one."""
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        share = y / max(height - 1, 1)
        draw.line(
            ((0, y), (width, y)),
            fill=tuple(
                round(top + (bottom - top) * share)
                for top, bottom in zip(palette.top, palette.bottom, strict=True)
            ),
        )
    return image


@cache
def font_coverage(font_file: str) -> frozenset[int]:
    """The code points *font_file* has a glyph for."""
    with TTFont(_FONT_DIR / font_file, lazy=True) as font:
        return frozenset(font.getBestCmap() or ())


@lru_cache(maxsize=128)
def _font(font_file: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_FONT_DIR / font_file, size)


def _font_for(char: str, current: str | None) -> str:
    """The font that draws *char*, keeping *current* while it can.

    A character no bundled font has falls back to the first, which draws its
    missing-glyph box.
    """
    point = ord(char)
    if current is not None and (
        point in font_coverage(current) or unicodedata.combining(char)
    ):
        return current
    return next(
        (name for name in FONT_FILES if point in font_coverage(name)), FONT_FILES[0]
    )


@dataclass(frozen=True, slots=True)
class _Text:
    """A line of text split into runs, each drawn by one bundled font."""

    runs: tuple[tuple[ImageFont.FreeTypeFont, str], ...]
    rtl: bool

    @classmethod
    def of(cls, text: str, size: int) -> _Text:
        runs: list[tuple[str, str]] = []
        for char in text:
            name = _font_for(char, runs[-1][0] if runs else None)
            if runs and runs[-1][0] == name:
                runs[-1] = (name, runs[-1][1] + char)
            else:
                runs.append((name, char))
        direction = next(
            (
                unicodedata.bidirectional(char)
                for char in text
                if unicodedata.bidirectional(char) in {"L", "R", "AL"}
            ),
            "L",
        )
        return cls(
            tuple((_font(name, size), run) for name, run in runs),
            direction in _RTL_CLASSES,
        )

    @property
    def width(self) -> float:
        return sum(font.getlength(run) for font, run in self.runs)

    def draw(
        self, draw: ImageDraw.ImageDraw, centre: float, baseline: float, fill: _Rgb
    ) -> None:
        """Draw the runs centred on *centre*, in reading order, on *baseline*."""
        x = centre - self.width / 2
        for font, run in reversed(self.runs) if self.rtl else self.runs:
            draw.text((x, baseline), run, font=font, fill=fill, anchor="ls")
            x += font.getlength(run)


def _wrap(text: str, size: int, width: float) -> list[_Text]:
    """Split *text* into lines no wider than *width*, word by word."""
    words: list[str] = []
    for word in text.split():
        candidate = f"{words[-1]} {word}" if words else word
        if words and _Text.of(candidate, size).width <= width:
            words[-1] = candidate
        else:
            words.append(word)
    return [_Text.of(line, size) for line in words or [""]]


def _fitted(text: str, width: float, size: int) -> tuple[int, list[_Text]]:
    """The largest size up to *size* that wraps *text* into few enough lines."""
    while True:
        lines = _wrap(text, size, width)
        widest = max(line.width for line in lines)
        if (len(lines) <= _MAX_LINES and widest <= width) or size <= 12:
            return size, lines
        size = round(size * 0.9)


def render_art(
    art_type: ArtType,
    style: ArtStyle,
    title: str | None = None,
    subtitle: str | None = None,
) -> bytes:
    """Draw *title*, under *subtitle* if given, as a PNG of *art_type*.

    Without a title the art is the style's colours alone.
    """
    palette = _PALETTES[style]
    image = _gradient(_SIZES[art_type], palette)
    if title is not None:
        _draw_title(image, palette, title, subtitle)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _draw_title(
    image: Image.Image, palette: _Palette, title: str, subtitle: str | None
) -> None:
    """Draw *title* centred on *image*, under *subtitle* and a rule if given."""
    width, height = image.size
    draw = ImageDraw.Draw(image)
    size, lines = _fitted(title.strip() or " ", width * 0.8, round(height * 0.085))
    ascent, descent = _font(FONT_FILES[0], size).getmetrics()
    line_height = round((ascent + descent) * 1.1)
    small_size = round(height * 0.028)
    small_ascent = _font(FONT_FILES[0], small_size).getmetrics()[0]
    heading = subtitle.strip().upper() if subtitle and subtitle.strip() else None
    rule_gap = round(height * 0.03)
    block = len(lines) * line_height + (small_ascent + 2 * rule_gap if heading else 0)
    y = (height - block) // 2
    if heading:
        _Text.of(heading, small_size).draw(
            draw, width / 2, y + small_ascent, palette.muted
        )
        y += small_ascent + rule_gap
        rule_width = round(width * 0.12)
        draw.rectangle(
            (
                (width - rule_width) // 2,
                y,
                (width + rule_width) // 2,
                y + max(round(height * 0.004), 2),
            ),
            fill=palette.rule,
        )
        y += rule_gap
    for line in lines:
        line.draw(draw, width / 2, y + ascent, palette.text)
        y += line_height
