"""Artwork Overture draws from a title, for collections that have none.

Pillow's built-in scalable font draws the text, so nothing is downloaded or
bundled, and the same title and style always give the same bytes.
"""

lazy import io
lazy from dataclasses import dataclass

lazy from PIL import Image, ImageDraw, ImageFont

lazy from ..domain import ArtStyle, ArtType

#: The size each art type is drawn at, as servers display them.
_SIZES = {ArtType.POSTER: (1000, 1500), ArtType.BACKGROUND: (3840, 2160)}
#: The most lines a title wraps to before its size shrinks instead.
_MAX_LINES = 4

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


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Pillow's built-in scalable font at *size* pixels.

    Raises:
        RuntimeError: When Pillow was built without FreeType, whose fixed-size
            fallback cannot be scaled.
    """
    font = ImageFont.load_default(size=size)
    if not isinstance(font, ImageFont.FreeTypeFont):
        raise RuntimeError("Drawing artwork needs Pillow built with FreeType")
    return font


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Split *text* into lines no wider than *width*, word by word."""
    lines: list[str] = []
    for word in text.split():
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and font.getlength(candidate) <= width:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines or [""]


def _fitted(
    text: str, width: float, size: int
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest font up to *size* that wraps *text* into few enough lines."""
    while True:
        font = _font(size)
        lines = _wrap(text, font, width)
        widest = max(font.getlength(line) for line in lines)
        if (len(lines) <= _MAX_LINES and widest <= width) or size <= 12:
            return font, lines
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
    text_width = width * 0.8
    font, lines = _fitted(title.strip() or " ", text_width, round(height * 0.085))
    ascent, descent = font.getmetrics()
    line_height = round((ascent + descent) * 1.1)
    small = _font(round(height * 0.028))
    heading = subtitle.strip().upper() if subtitle and subtitle.strip() else None
    rule_gap = round(height * 0.03)
    block = len(lines) * line_height + (
        small.getmetrics()[0] + 2 * rule_gap if heading else 0
    )
    y = (height - block) // 2
    if heading:
        draw.text((width / 2, y), heading, font=small, fill=palette.muted, anchor="mt")
        y += small.getmetrics()[0] + rule_gap
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
        draw.text((width / 2, y), line, font=font, fill=palette.text, anchor="mt")
        y += line_height
