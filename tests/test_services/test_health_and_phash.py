"""Focused health and pHash service tests."""

lazy import io
lazy from concurrent.futures import ThreadPoolExecutor
lazy from pathlib import Path

lazy import pytest
lazy from PIL import Image, ImageDraw

lazy from overture.config import Settings
lazy from overture.domain import ServerType
lazy from overture.schemas.settings import ConnectivityStatusResponse
lazy from overture.services import health
lazy from overture.services.art import phash as phash_module
lazy from overture.services.art.phash import (
    PHASH_HEX_LENGTH,
    PhashService,
)
lazy from overture.utils import phash as phash_utils
lazy from overture.utils.phash import (
    compute_phash_from_bytes,
)
lazy from tests.runtime_helpers import NoopProviderRegistry


def test_hamming_distance_counts_hex_bit_differences() -> None:
    assert (
        PhashService.hamming_distance("0" * PHASH_HEX_LENGTH, "0" * PHASH_HEX_LENGTH)
        == 0
    )
    assert (
        PhashService.hamming_distance(
            "0" * PHASH_HEX_LENGTH,
            f"{'0' * (PHASH_HEX_LENGTH - 1)}1",
        )
        == 1
    )
    # Each step is eight differing bits, any part of one counting as a step.
    assert (
        PhashService.hamming_distance(
            "0" * PHASH_HEX_LENGTH,
            f"{'0' * (PHASH_HEX_LENGTH - 2)}ff",
        )
        == 1
    )
    assert (
        PhashService.hamming_distance(
            "0" * PHASH_HEX_LENGTH,
            f"{'0' * (PHASH_HEX_LENGTH - 3)}1ff",
        )
        == 2
    )
    assert (
        PhashService.hamming_distance("f" * PHASH_HEX_LENGTH, "0" * PHASH_HEX_LENGTH)
        == 32
    )


def test_hamming_distance_rejects_non_detailed_fingerprints() -> None:
    with pytest.raises(ValueError, match="Invalid pHash fingerprint"):
        PhashService.hamming_distance(
            "0" * (PHASH_HEX_LENGTH - 1), "0" * PHASH_HEX_LENGTH
        )
    with pytest.raises(ValueError, match="Invalid pHash fingerprint"):
        PhashService.hamming_distance("-00000000000001", "0" * PHASH_HEX_LENGTH)
    with pytest.raises(ValueError, match="Invalid pHash fingerprint"):
        PhashService.hamming_distance("g" * PHASH_HEX_LENGTH, "0" * PHASH_HEX_LENGTH)
    with pytest.raises(ValueError, match="Invalid pHash fingerprint"):
        PhashService.hamming_distance(
            "0" * (PHASH_HEX_LENGTH - 1) + " ", "0" * PHASH_HEX_LENGTH
        )


def test_computed_fingerprint_contains_detailed_phash() -> None:
    buffer_white = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer_white, format="PNG")
    white_hash = compute_phash_from_bytes(buffer_white.getvalue())

    assert len(white_hash) == PHASH_HEX_LENGTH

    buffer_black = io.BytesIO()
    Image.new("RGB", (32, 32), "black").save(buffer_black, format="PNG")
    black_hash = compute_phash_from_bytes(buffer_black.getvalue())

    assert len(black_hash) == PHASH_HEX_LENGTH
    # Solid black and solid white differ only in DC component vs background
    assert PhashService.hamming_distance(white_hash, black_hash) == 1


def test_computed_fingerprint_stabilizes_zero_dct_coefficients() -> None:
    image = Image.new("L", (64, 64))
    ImageDraw.Draw(image).rectangle((9, 4, 38, 48), fill=255)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    assert compute_phash_from_bytes(buffer.getvalue()) == (
        "c1b6c1b63641c1b636413641c1b63641364136413641c1b636413641c1b63641"
    )


async def test_service_status_reports_the_media_server_and_tmdb_apart() -> None:
    class Provider:
        server_type = ServerType.EMBY

        async def test_connection(self) -> bool:
            return True

    class Tmdb:
        async def test_connection(self) -> bool:
            return False

    assert await health.get_service_status(
        NoopProviderRegistry(Provider()), Tmdb()
    ) == ConnectivityStatusResponse(media_server=True, tmdb=False)


@pytest.mark.real_process_pool
async def test_phash_pool_hashes_bytes_and_files(
    tmp_path: Path, *, app_config: Settings
) -> None:
    image_bytes = _png_bytes()
    image_path = tmp_path / "image.png"
    image_path.write_bytes(image_bytes)
    service = PhashService(app_config=app_config)
    try:
        byte_hash = await service.compute_from_bytes(image_bytes)
        assert await service.compute_from_file(str(image_path)) == byte_hash
    finally:
        service.shutdown()


def test_phash_rejects_excessive_decoded_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phash_utils, "MAX_PHASH_PIXELS", 1)
    with pytest.raises(ValueError, match="pHash safety limit"):
        compute_phash_from_bytes(_png_bytes())


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
async def test_phash_service_recovers_from_worker_control_flow(
    error: type[BaseException], monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    service = PhashService(
        app_config=app_config,
        executor=executor,
    )

    def crashing_func(_bytes: bytes) -> str:
        raise error("Worker interrupted")

    monkeypatch.setattr(phash_module, "compute_phash_from_bytes", crashing_func)

    with pytest.raises(OSError, match="pHash worker operation interrupted"):
        await service.compute_from_bytes(b"dummy")

    monkeypatch.setattr(
        phash_module, "compute_phash_from_bytes", compute_phash_from_bytes
    )
    assert await service.compute_from_bytes(_png_bytes())
    service.shutdown()
