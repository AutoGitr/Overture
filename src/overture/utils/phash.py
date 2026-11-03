"""8x8 DCT perceptual hash using Pillow and the standard library."""

lazy import io
lazy import math
lazy from pathlib import Path
lazy from statistics import median

lazy from PIL import Image

PHASH_SIZE = 8
IMG_SIZE = 32
MAX_PHASH_PIXELS = 50_000_000

# Precompute the low-frequency rows of the 32-point DCT-II matrix.
# C[k, n] = 2.0 * cos(pi * k * (2 * n + 1) / (2 * N)) for k in [0..7], n in [0..31]
_C: tuple[tuple[float, ...], ...] = tuple(
    tuple(
        2.0 * math.cos(math.pi * k * (2 * n + 1) / (2.0 * IMG_SIZE))
        for n in range(IMG_SIZE)
    )
    for k in range(PHASH_SIZE)
)


def compute_phash(image: Image.Image) -> str:
    """Compute a 64-bit perceptual hash formatted as a 16-character hex string."""
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_PHASH_PIXELS:
        raise ValueError("Image dimensions exceed the pHash safety limit")

    # Pillow's size annotation includes an optional, untyped NumPy array alias.
    # This call uses only a tuple; NumPy is deliberately not a dependency.
    img = image.convert("L").resize(  # pyright: ignore[reportUnknownMemberType]
        (IMG_SIZE, IMG_SIZE), Image.Resampling.LANCZOS
    )
    raw = img.tobytes()

    columns = tuple(raw[column::IMG_SIZE] for column in range(IMG_SIZE))

    # Transform columns, then rows, retaining only the 8x8 low frequencies.
    d_rows = [
        [
            sum(weight * pixel for weight, pixel in zip(weights, column, strict=True))
            for column in columns
        ]
        for weights in _C
    ]

    coefficients = [
        sum(value * weight for value, weight in zip(row, weights, strict=True))
        for row in d_rows
        for weights in _C
    ]

    # Stabilize mathematically zero frequencies for flat/symmetric images.
    coefficients = [0.0 if abs(value) < 1e-4 else value for value in coefficients]
    threshold = median(coefficients)

    # Pack 64 bits row-major, including the DC coefficient in the median.
    hash_val = 0
    for value in coefficients:
        hash_val = (hash_val << 1) | (value > threshold)

    return f"{hash_val:016x}"


def _open_and_compute(source: str | Path | io.BytesIO) -> str:
    try:
        with Image.open(source) as img:
            return compute_phash(img)
    except Image.DecompressionBombError as exc:
        raise ValueError("Image dimensions exceed the pHash safety limit") from exc


def compute_phash_from_bytes(data: bytes) -> str:
    """Compute the perceptual hash from encoded image bytes."""
    return _open_and_compute(io.BytesIO(data))


def compute_phash_from_file(file_path: str | Path) -> str:
    """Compute the perceptual hash directly from an image file path."""
    return _open_and_compute(file_path)
