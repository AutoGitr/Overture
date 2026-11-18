"""Unit tests for Pillow and standard-library perceptual hashing."""

lazy import io
lazy from pathlib import Path

lazy import pytest
lazy from PIL import Image, ImageDraw

lazy from overture.utils.phash import (
    compute_phash,
    compute_phash_from_bytes,
    compute_phash_from_file,
)


def _hamming_distance(h1: str, h2: str) -> int:
    return (int(h1, 16) ^ int(h2, 16)).bit_count()


def test_compute_phash_format_and_length() -> None:
    img = Image.new("RGB", (100, 100), color=(100, 150, 200))
    h = compute_phash(img)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_phash_resize_invariance() -> None:
    # A continuous tone image and its downsampled version should yield very close hashes
    img_large = Image.linear_gradient("L")
    # Pillow's resize annotation includes an optional, untyped NumPy array alias.
    # The tuple-based call does not require installing NumPy.
    img_small = img_large.resize(  # pyright: ignore[reportUnknownMemberType]
        (50, 50), Image.Resampling.LANCZOS
    )

    h_large = compute_phash(img_large)
    h_small = compute_phash(img_small)
    assert _hamming_distance(h_large, h_small) <= 12


def test_compute_phash_compression_invariance() -> None:
    # PNG vs lossy JPEG
    img = Image.new("RGB", (200, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.line((0, 0, 200, 200), fill="black", width=10)
    draw.rectangle((30, 40, 160, 170), fill="red")

    buf_png = io.BytesIO()
    img.save(buf_png, format="PNG")
    h_png = compute_phash_from_bytes(buf_png.getvalue())

    buf_jpg = io.BytesIO()
    img.save(buf_jpg, format="JPEG", quality=75)
    h_jpg = compute_phash_from_bytes(buf_jpg.getvalue())

    assert _hamming_distance(h_png, h_jpg) <= 12


def test_compute_phash_dissimilar_images() -> None:
    # Completely different patterns should have high distance
    img1 = Image.linear_gradient("L")
    img2 = Image.new("RGB", (100, 100), color="white")
    draw2 = ImageDraw.Draw(img2)
    for i in range(0, 100, 10):
        draw2.line((0, i, 100, 100 - i), fill="black")

    h1 = compute_phash(img1)
    h2 = compute_phash(img2)
    assert _hamming_distance(h1, h2) >= 60


def test_compute_phash_file_matches_bytes(tmp_path: Path) -> None:
    img = Image.new("RGB", (120, 80), color="green")
    path = tmp_path / "test.png"
    img.save(path)

    h_file = compute_phash_from_file(path)
    h_bytes = compute_phash_from_bytes(path.read_bytes())
    assert h_file == h_bytes


def test_compute_phash_rejects_excessive_pixels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    img = Image.new("RGB", (10, 10))
    monkeypatch.setattr("overture.utils.phash.MAX_PHASH_PIXELS", 50)
    with pytest.raises(ValueError, match="Image dimensions exceed"):
        compute_phash(img)


@pytest.mark.parametrize("level", [0, 1, 127, 255])
def test_flat_images_have_no_spurious_ac_bits(level: int) -> None:
    image = Image.new("L", (32, 32), color=level)
    assert compute_phash(image) == ("8" + "0" * 63 if level else "0" * 64)


def test_compute_phash_tells_apart_posters_that_differ_only_in_detail() -> None:
    def poster(detail: bool) -> Image.Image:
        image = Image.new("L", (400, 600), color=40)
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 80, 340, 420), fill=200)
        if detail:
            # A credit block and a fine border, as another print of a poster has.
            for row in range(470, 560, 12):
                draw.line((80, row, 320, row), fill=230, width=4)
        return image

    plain, detailed = compute_phash(poster(False)), compute_phash(poster(True))
    resized = compute_phash(
        poster(True).resize(  # pyright: ignore[reportUnknownMemberType] -- NumPy-typed overload
            (267, 400), Image.Resampling.LANCZOS
        )
    )

    assert _hamming_distance(plain, detailed) > 8
    assert _hamming_distance(detailed, resized) <= 8


def test_compute_phash_rejects_invalid_encoding() -> None:
    with pytest.raises(OSError, match="cannot identify image"):
        compute_phash_from_bytes(b"not an image")


def test_compute_phash_translates_pillow_decompression_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.BytesIO()
    Image.new("L", (10, 10)).save(buffer, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    with pytest.raises(ValueError, match="pHash safety limit"):
        compute_phash_from_bytes(buffer.getvalue())
