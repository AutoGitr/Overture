"""The hashes stored values depend on keep their algorithm and form."""

lazy import io
lazy from pathlib import Path

lazy from overture.utils.hashing import (
    compute_bytes_hash,
    compute_file_hash,
    copy_with_hash,
    text_digest,
)


def test_text_digests_are_sha256_so_stored_ones_stay_valid() -> None:
    # Signed-in sessions and Plex labels keep digests taken this way.
    assert text_digest("token") == (
        "3c469e9d6c5875d37a43f353d4f88e61fcf812c66eee3457465a40b0da4153e0"
    )
    assert text_digest("token", 8) == "3c469e9d"


def test_a_file_a_copy_and_its_bytes_hash_alike(tmp_path: Path) -> None:
    source = tmp_path / "poster.jpg"
    source.write_bytes(b"poster")
    copy = io.BytesIO()

    assert copy_with_hash(source, copy) == compute_bytes_hash(b"poster")
    assert copy.getvalue() == b"poster"
    assert compute_file_hash(source) == compute_bytes_hash(b"poster")
    assert compute_file_hash(tmp_path / "missing") is None
