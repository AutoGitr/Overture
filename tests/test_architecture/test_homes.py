"""Each low-level concern has one home in ``utils``, read from the code itself.

Code elsewhere reaches these primitives through their home, so a rule about
them (a hash's algorithm, how a file reaches the disk, which clock is read)
holds everywhere by being written once. Migrations are snapshots and keep
their own.
"""

lazy import re
lazy from pathlib import Path

lazy import pytest

lazy import overture

ROOT = Path(overture.__file__).parent

#: Each primitive, and the modules that may use it directly.
HOMES: dict[str, tuple[re.Pattern[str], frozenset[str]]] = {
    "hashing": (
        re.compile(
            r"^\s*(lazy )?(import hashlib|from (hashlib|blake3) import)", re.MULTILINE
        ),
        frozenset({"utils/hashing.py"}),
    ),
    "kept files": (
        re.compile(
            r"\bos\.fsync\(|\btempfile\.|\.replace\([a-z_]*(path|destination|target)\)"
        ),
        frozenset({"utils/file.py", "utils/temporary.py"}),
    ),
    "the clock": (
        re.compile(r"\bdatetime\.(now|utcnow|today)\(|\bdate\.today\("),
        frozenset({"utils/time.py"}),
    ),
    "MediaBrowser membership writes": (
        # One place batches the IDs a write carries in its URL.
        re.compile(r"/Collections/\{[^}]*\}/Items"),
        frozenset({"media_servers/jellyfin/client.py"}),
    ),
    "worker threads": (
        # A thread the event loop owns, so a cancelled caller never leaves it
        # running unseen.
        re.compile(r"\bto_thread\("),
        frozenset({"utils/threads.py"}),
    ),
    "HTTP clients": (
        # One place sets the timeouts every outgoing request has.
        re.compile(r"\bhttpx2\.AsyncClient\("),
        frozenset({"integrations/http.py"}),
    ),
    "routes that need a media server": (
        # The factory declares the 409, 502 and 503 such a route answers.
        re.compile(r"Depends\(require_media_server\)"),
        frozenset({"routers/auth.py"}),
    ),
    "SQLite files": (
        re.compile(r"\bsqlite3\.connect\("),
        frozenset(
            {
                "utils/scratch.py",
                # One long-lived scratch connection, set up by utils.scratch.
                "services/sync/staging.py",
                # SQLite's online backup API, which SQLModel has no form of.
                "services/backup/files.py",
            }
        ),
    ),
}


def _sources() -> list[tuple[str, str]]:
    return [
        (path.relative_to(ROOT).as_posix(), path.read_text())
        for path in sorted(ROOT.rglob("*.py"))
        if "migrations" not in path.relative_to(ROOT).parts
    ]


@pytest.mark.parametrize("concern", HOMES)
def test_a_primitive_is_used_only_in_its_home(concern: str) -> None:
    pattern, homes = HOMES[concern]
    strays = [
        name
        for name, source in _sources()
        if name not in homes and pattern.search(source)
    ]
    assert strays == [], f"Reach {concern} through {sorted(homes)}"
