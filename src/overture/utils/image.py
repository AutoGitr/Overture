"""Decoding and inspecting images Overture keeps: formats, sizes, thumbnails."""

lazy from io import BytesIO
lazy from pathlib import Path

lazy from PIL import Image, ImageOps, UnidentifiedImageError

lazy from ..domain import ArtType, AspectRatioTolerance

#: AVIF is the most compact format every current browser decodes, and a
#: thumbnail is encoded once per image and then kept.
THUMB_MEDIA_TYPE = "image/avif"


THUMB_EXTENSION = ".avif"


#: AVIF quality of thumbnails: visually close to the original at a fraction of
#: the size of a JPEG.
_THUMB_QUALITY = 60


#: Most pixels Overture decodes from one image.
MAX_IMAGE_PIXELS = 50_000_000


class UnsupportedImageFormatError(ValueError):
    """Raised when local image bytes use an unsupported encoded format."""


#: The encoded formats Overture saves, with the extension each is saved under.
SAVED_IMAGE_EXTENSIONS = frozendict({"JPEG": ".jpg", "PNG": ".png"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub


#: The media type each saved extension is served as.
SAVED_MEDIA_TYPES = frozendict({".jpg": "image/jpeg", ".png": "image/png"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub


def get_local_image_size(path: Path) -> tuple[int, int]:
    """Return local image dimensions, or ``(0, 0)`` when unreadable."""
    try:
        with Image.open(path) as image:
            return image.size
    except UnidentifiedImageError, OSError, ValueError:
        return 0, 0


def render_thumb(path: Path, bounds: tuple[int, int]) -> bytes:
    """Return the image at *path* shrunk to fit *bounds*, as AVIF.

    The shown orientation is kept. An image already inside *bounds* is only
    re-encoded, never enlarged.

    Raises:
        UnsupportedImageFormatError: When the file is not a readable image
            within the pixel limit.
    """
    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise UnsupportedImageFormatError(
                    "Image dimensions exceed safety limit"
                )
            # A JPEG decodes straight to a reduced scale, far cheaper than in
            # full. Its reduction never leaves less than the thumbnail needs,
            # whichever way an EXIF orientation turns it.
            image.draft("RGB", bounds)
            rendition = ImageOps.exif_transpose(image)
            rendition.thumbnail(bounds)
            if rendition.mode not in {"RGB", "RGBA"}:
                alpha = rendition.has_transparency_data
                rendition = rendition.convert("RGBA" if alpha else "RGB")
            buffer = BytesIO()
            rendition.save(buffer, "AVIF", quality=_THUMB_QUALITY, speed=8)
            return buffer.getvalue()
    except UnsupportedImageFormatError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise UnsupportedImageFormatError("Unreadable image file") from exc


def _inspect_image(source: Path | BytesIO, unreadable: str) -> tuple[str, int, int]:
    """Return the Pillow format name and dimensions of a readable image."""
    try:
        with Image.open(source) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise UnsupportedImageFormatError(
                    "Image dimensions exceed safety limit"
                )
            image_format = image.format
            width, height = image.size
    except UnsupportedImageFormatError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsupportedImageFormatError(unreadable) from exc
    if image_format is None:
        raise UnsupportedImageFormatError(unreadable)
    if image_format not in Image.MIME:
        raise UnsupportedImageFormatError(f"Unsupported image format: {image_format}")
    return image_format, width, height


def encoded_image_format(image_data: bytes) -> str:
    """Return the Pillow format name, such as ``WEBP``, of readable image bytes."""
    return _inspect_image(BytesIO(image_data), "Unreadable image bytes")[0]


def saved_image_extension(image_format: str) -> str:
    """Return the extension an image in *image_format* is saved under.

    Raises:
        UnsupportedImageFormatError: When Overture does not save that format.
    """
    extension = SAVED_IMAGE_EXTENSIONS.get(image_format)
    if extension is None:
        raise UnsupportedImageFormatError(
            f"Unsupported image format: {image_format}. Only JPEG and PNG are allowed."
        )
    return extension


def inspect_saved_image(source: Path | bytes) -> tuple[str, int, int]:
    """Return the saved extension and dimensions of a readable JPEG or PNG.

    Raises:
        UnsupportedImageFormatError: When *source* is not a readable JPEG or PNG
            within the pixel limit.
    """
    if isinstance(source, bytes):
        image_format, width, height = _inspect_image(
            BytesIO(source), "Unreadable image bytes"
        )
    else:
        image_format, width, height = _inspect_image(source, "Unreadable image file")
    return saved_image_extension(image_format), width, height


def encoded_image_extension(image_data: bytes) -> str:
    """Return the extension readable JPEG or PNG bytes are saved under."""
    return inspect_saved_image(image_data)[0]


def is_valid_aspect_ratio(
    width: int,
    height: int,
    art_type: ArtType,
    tolerance: AspectRatioTolerance,
) -> bool:
    """Check if an image matches the expected aspect ratio for its slot.

    Unmeasured images are rejected unless the check is off.
    """
    if tolerance.fraction is None:
        return True
    if not width or not height:
        return False
    expected = art_type.aspect_ratio
    return abs(width / height - expected) / expected <= tolerance.fraction


def has_incorrect_aspect_ratio(
    width: int | None,
    height: int | None,
    art_type: ArtType,
    tolerance: AspectRatioTolerance,
) -> bool:
    """Return whether known dimensions break the expected ratio for *art_type*.

    Unlike :func:`is_valid_aspect_ratio`, missing dimensions are not a fault:
    artwork that has not been measured is not reported as misshapen.
    """
    return bool(
        width
        and height
        and not is_valid_aspect_ratio(width, height, art_type, tolerance)
    )
