"""Rendering of AVIF display thumbnails for cached local artwork."""

lazy from io import BytesIO
lazy from pathlib import Path

lazy import pytest
lazy from PIL import ExifTags, Image

lazy from overture.utils.image import UnsupportedImageFormatError, render_thumb


def _decode(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    image.load()
    return image


def test_downscales_to_fit_bounds_keeping_the_aspect_ratio(tmp_path: Path) -> None:
    path = tmp_path / "poster.jpg"
    Image.new("RGB", (1000, 1500), "red").save(path, "JPEG")

    image = _decode(render_thumb(path, (960, 600)))

    assert image.format == "AVIF"
    assert image.size == (400, 600)


def test_encodes_without_enlarging_an_image_already_inside_bounds(
    tmp_path: Path,
) -> None:
    path = tmp_path / "poster.png"
    Image.new("RGB", (92, 138), "red").save(path, "PNG")

    image = _decode(render_thumb(path, (960, 600)))

    assert image.format == "AVIF"
    assert image.size == (92, 138)


def test_keeps_the_orientation_the_image_is_shown_in(tmp_path: Path) -> None:
    # Stored landscape, shown portrait: the bounds apply to the oriented dimensions.
    path = tmp_path / "poster.jpg"
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    Image.new("RGB", (1500, 1000), "red").save(path, "JPEG", exif=exif)

    image = _decode(render_thumb(path, (100, 150)))

    assert image.format == "AVIF"
    assert image.size == (100, 150)


def test_keeps_transparency(tmp_path: Path) -> None:
    path = tmp_path / "poster.png"
    Image.new("LA", (400, 600), (0, 0)).save(path, "PNG")

    image = _decode(render_thumb(path, (92, 138)))

    assert image.format == "AVIF"
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0)) == (0, 0, 0, 0)


def test_rejects_a_file_that_is_not_an_image(tmp_path: Path) -> None:
    path = tmp_path / "poster.jpg"
    path.write_bytes(b"not an image")

    with pytest.raises(UnsupportedImageFormatError):
        render_thumb(path, (92, 138))
