"""The collection check reads from Overture and can change nothing."""

lazy import json
lazy from pathlib import Path
lazy from typing import Any

lazy import httpx2
lazy import pytest

lazy from scripts import verify_collections as module


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/collections"),
        ("PUT", "/api/collections/1/rule"),
        ("POST", "/api/collections/1/sync"),
        ("DELETE", "/api/collections/1"),
        ("POST", "/api/sync/run"),
    ],
)
async def test_writes_are_refused_before_they_are_sent(method: str, path: str) -> None:
    sent: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request.url.path)
        return httpx2.Response(200, json={})

    async with httpx2.AsyncClient(
        base_url="http://overture.test",
        transport=httpx2.MockTransport(handler),
        event_hooks={"request": [module.refuse_writes]},
    ) as client:
        with pytest.raises(module.WriteRefusedError):
            await client.request(method, path)

    assert sent == []


def fake_overture(previews: list[dict[str, Any]]) -> httpx2.MockTransport:
    """An Overture with one movie library on Plex, signed in, holding Alien."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        media_type = request.url.params.get("media_type")
        if path == "/api/auth/me":
            return httpx2.Response(200, json={"authenticated": True})
        if path == "/api/library/libraries":
            libraries = [{"id": "1", "title": "Movies", "count": 1}]
            return httpx2.Response(200, json=libraries if media_type == "movie" else [])
        if path == "/api/collections/capabilities":
            field = {
                "field": "genre",
                "label": "Genre",
                "kind": "tag",
                "operators": ["is"],
                "local": True,
                "smart": True,
            }
            return httpx2.Response(200, json={"smart": True, "fields": [field]})
        if path == "/api/collections/field-values":
            return httpx2.Response(200, json=[{"value": "Horror", "count": 1}])
        if path == "/api/collections/tags/radarr":
            return httpx2.Response(200, json=[])
        if path == "/api/collections/preview":
            body = json.loads(request.content)
            previews.append(body)
            smart = body["rule"]["smart"]
            if body["rule"]["criteria"]["conditions"][0]["kind"] == "source":
                return httpx2.Response(422, json={"detail": "Set TMDB_API_KEY"})
            # Plex disagrees, which the report must point out.
            return httpx2.Response(
                200, json={"member_count": 2 if smart else 1, "members": ["Alien"]}
            )
        return httpx2.Response(404)

    return httpx2.MockTransport(handler)


async def test_a_run_previews_both_ways_and_reports_the_problems(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    previews: list[dict[str, Any]] = []
    transport = fake_overture(previews)
    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(module.httpx2, "AsyncClient", client)
    report = tmp_path / "report.md"
    args = module.argparse.Namespace(
        url="http://overture.test", report=report, sources=None
    )

    assert await module.run(args) == 1

    assert [(p["rule"]["smart"], p["library_id"]) for p in previews] == [
        (False, "1"),
        (True, "1"),
        (False, "1"),
    ]
    text = report.read_text()
    assert "2 cases, 2 problems." in text
    assert (
        "| Movies (movie) | Genre is 'Horror' | 1 | 2 | Alien | counts differ |" in text
    )
    assert "| TMDB chart popular |" in text
    assert "Set TMDB_API_KEY" in text
