"""In-memory downscaling of local artwork."""

lazy from io import BytesIO
lazy from pathlib import Path

lazy import pytest
lazy from PIL import ExifTags, Image

lazy from overture.utils.image import UnsupportedImageFormatError, downscaled_webp


def _decode(data: bytes | None) -> Image.Image:
    assert data is not None
    image = Image.open(BytesIO(data))
    image.load()
    return image


async def test_downscales_to_the_width_keeping_the_aspect_ratio(tmp_path: Path) -> None:
    path = tmp_path / "poster.jpg"
    Image.new("RGB", (1000, 1500), "red").save(path, "JPEG")

    image = _decode(await downscaled_webp(path, 92))

    assert image.format == "WEBP"
    assert image.size == (92, 138)


async def test_returns_none_for_an_image_no_wider_than_the_width(
    tmp_path: Path,
) -> None:
    path = tmp_path / "poster.png"
    Image.new("RGB", (92, 138), "red").save(path, "PNG")

    assert await downscaled_webp(path, 92) is None


async def test_keeps_the_orientation_the_image_is_shown_in(tmp_path: Path) -> None:
    # Stored landscape, shown portrait: the width limit applies to the shown width.
    path = tmp_path / "poster.jpg"
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    Image.new("RGB", (1500, 1000), "red").save(path, "JPEG", exif=exif)

    image = _decode(await downscaled_webp(path, 100))

    assert image.size == (100, 150)


async def test_keeps_transparency(tmp_path: Path) -> None:
    path = tmp_path / "poster.png"
    Image.new("LA", (400, 600), (0, 0)).save(path, "PNG")

    image = _decode(await downscaled_webp(path, 92))

    assert image.mode == "RGBA"
    assert image.getpixel((0, 0)) == (0, 0, 0, 0)


async def test_rejects_a_file_that_is_not_an_image(tmp_path: Path) -> None:
    path = tmp_path / "poster.jpg"
    path.write_bytes(b"not an image")

    with pytest.raises(UnsupportedImageFormatError):
        await downscaled_webp(path, 92)
