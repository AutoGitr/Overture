"""Prepare the pinned upstream API contracts used by provider tests."""

lazy import argparse
lazy import hashlib
lazy import json
lazy import urllib.request
lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from typing import Any, cast
lazy from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "openapi"
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
REDOC_MARKER = "__redoc_state = "


@dataclass(frozen=True)
class ProviderSource:
    name: str
    url: str
    host: str
    version: str
    sha256: str
    redoc: bool = False
    redirect_suffixes: tuple[str, ...] = ()


SOURCES = (
    ProviderSource(
        name="jellyfin",
        url=(
            "https://repo.jellyfin.org/releases/openapi/stable/jellyfin-openapi-10.11.11.json"
        ),
        host="repo.jellyfin.org",
        version="10.11.11",
        sha256="1d4d82ac1304d44d95dfe2a0315158b05ee9f0d0ebdad211d34b85d19606eddc",
        redirect_suffixes=(".mirror.jellyfin.org",),
    ),
    ProviderSource(
        name="emby",
        url=(
            "https://raw.githubusercontent.com/MediaBrowser/Emby.SDK/bdd0dd7c0801f6e069dff2795d80cddae6f91791/Resources/OpenApi/openapi_v3.json"
        ),
        host="raw.githubusercontent.com",
        version="4.9.5.0",
        sha256="5885caf123c278989770b26f609413ace9d6e39122926a2d9e6ebc851987b723",
    ),
    ProviderSource(
        name="plex",
        url="https://developer.plex.tv/pms/",
        host="developer.plex.tv",
        version="1.2.3",
        sha256="7e51d7d0cfc424e790eff9a5b9062791fca8dd3b1093b774432a6c6f2c9ec0c0",
        redoc=True,
    ),
)


def _fetch(source: ProviderSource) -> bytes:
    initial = urlsplit(source.url)
    if initial.scheme != "https" or initial.hostname != source.host:
        raise RuntimeError(f"{source.name}: unsafe source URL {source.url}")
    # The fixed source and every redirect are constrained to the provider's HTTPS host.
    request = urllib.request.Request(
        source.url,
        headers={"User-Agent": "Overture provider-contract preparation"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        final = urlsplit(response.url)
        final_host = final.hostname or ""
        trusted_host = final_host == source.host or any(
            final_host.endswith(suffix) for suffix in source.redirect_suffixes
        )
        if final.scheme != "https" or not trusted_host:
            raise RuntimeError(f"{source.name}: unsafe redirect to {response.url}")
        body = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise RuntimeError(
            f"{source.name}: response exceeds {MAX_DOWNLOAD_BYTES} bytes"
        )
    return body


def _parse(source: ProviderSource, body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8")
    if source.redoc:
        try:
            start = text.index(REDOC_MARKER) + len(REDOC_MARKER)
        except ValueError as exc:
            raise RuntimeError(f"{source.name}: Redoc state was not found") from exc
        state, _ = json.JSONDecoder().raw_decode(text[start:])
        document = cast("dict[str, Any]", state)["spec"]["data"]
    else:
        document = json.loads(text)
    if not isinstance(document, dict):
        raise RuntimeError(f"{source.name}: specification is not a JSON object")
    return cast("dict[str, Any]", document)


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _validate(source: ProviderSource, document: dict[str, Any]) -> None:
    version = str(document.get("info", {}).get("version", "")).strip()
    if version != source.version:
        message = (
            f"{source.name}: expected version {source.version}, "
            f"received {version or 'none'}"
        )
        raise RuntimeError(message)
    digest = hashlib.sha256(_canonical(document)).hexdigest()
    if digest != source.sha256:
        message = (
            f"{source.name}: checksum changed; review the contract before updating"
        )
        raise RuntimeError(message)


def prepare(source: ProviderSource, output: Path) -> None:
    target = output / f"{source.name}-openapi.json"
    if target.is_file():
        try:
            document = cast("dict[str, Any]", json.loads(target.read_text()))
            _validate(source, document)
            return
        except json.JSONDecodeError, OSError, RuntimeError:
            pass

    document = _parse(source, _fetch(source))
    _validate(source, document)
    output.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        newline="\n",
    )
    temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    for source in SOURCES:
        prepare(source, args.output.resolve())
        print(f"{source.name} {source.version}")


if __name__ == "__main__":
    main()
