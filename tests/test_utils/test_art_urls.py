"""Overture's artwork URL policy on top of the shared OvertureDB link contract.

How each source's links canonicalise is tested once, with the contract, in
OvertureDB; these tests cover what Overture adds and that every way artwork
enters Overture goes through it.
"""

lazy import pytest

lazy from overture.config import Settings
lazy from overture.domain import ArtSource, ArtType, ServerType
lazy from overture.integrations.tmdb import extract_art
lazy from overture.schemas.art import ArtCandidate
lazy from overture.services.public_dataset.lookup import build_candidate
lazy from overture.services.public_dataset.schema.contract import ART_HOSTS, art_source
lazy from overture.utils.art_urls import (
    art_preview_url,
    art_source_label,
    public_art_url,
    selected_art_source,
)

TMDB = "https://image.tmdb.org/t/p/original/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg"


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def public_url(_: str, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr("overture.utils.art_urls.is_private_url", public_url)


@pytest.mark.parametrize("provider", ["plex", "jellyfin", "emby"])
@pytest.mark.parametrize(
    "url",
    [
        "https://plex.direct/art.jpg",
        "https://192-168-1-2.server.plex.direct:32400/art.jpg",
        "http://remote.server.PLEX.DIRECT./art.jpg",
    ],
)
async def test_plex_server_domains_are_not_public_artwork(
    monkeypatch: pytest.MonkeyPatch, provider: str, url: str, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER = ServerType(provider)
    app_config.MEDIA_SERVER_URL = "https://server.test"

    async def check_public(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("Plex server domains should not require a DNS lookup")

    monkeypatch.setattr("overture.utils.art_urls.is_private_url", check_public)
    assert await public_art_url(url, app_config=app_config) is None


@pytest.mark.usefixtures("public_dns")
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://image.tmdb.org/t/p/w342/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg", TMDB),
        (f" {TMDB} ", TMDB),
        (
            "https://theposterdb.com/poster/207889",
            "https://theposterdb.com/api/assets/207889",
        ),
        (
            "https://www.theposterdb.com/api/assets/207889/view",
            "https://theposterdb.com/api/assets/207889",
        ),
        (
            "https://assets.fanart.tv/preview/movies/1/movieposter/a.jpg",
            "https://assets.fanart.tv/fanart/movies/1/movieposter/a.jpg",
        ),
        (
            "https://artworks.thetvdb.com/banners/v4/movie/1/posters/abc_t.jpg",
            "https://artworks.thetvdb.com/banners/v4/movie/1/posters/abc.jpg",
        ),
        (
            "https://m.media-amazon.com/images/M/MV5Babc@._V1_SX300.jpg",
            "https://m.media-amazon.com/images/M/MV5Babc@.jpg",
        ),
        (
            "https://cdn.example.test/poster.jpg?api_key=secret&v=2",
            "https://cdn.example.test/poster.jpg?v=2",
        ),
        ("https://theposterdb.com/set/12345", None),
        ("https://image.tmdb.org/t/p/w342/logo.svg", None),
        ("ftp://cdn.example.test/poster.jpg", None),
        ("https://user:secret@cdn.example.test/poster.jpg", None),
        ("", None),
        (None, None),
    ],
)
async def test_public_art_url_stores_the_canonical_full_size_link(
    value: str | None, expected: str | None, *, app_config: Settings
) -> None:
    assert await public_art_url(value, app_config=app_config) == expected


async def test_media_server_urls_are_never_public_artwork(
    *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER = ServerType.JELLYFIN
    app_config.MEDIA_SERVER_URL = "https://jellyfin.test"

    assert (
        await public_art_url(
            "https://jellyfin.test/Items/1/Images/Primary",
            fetched_publicly=True,
            app_config=app_config,
        )
        is None
    )


@pytest.mark.parametrize(
    ("url", "art_type", "preview"),
    [
        (TMDB, "poster", TMDB.replace("/original/", "/w342/")),
        (TMDB, "season_poster", TMDB.replace("/original/", "/w342/")),
        (TMDB, "background", TMDB.replace("/original/", "/w780/")),
        (
            "https://assets.fanart.tv/fanart/a-52b3.jpg",
            "background",
            "https://assets.fanart.tv/preview/a-52b3.jpg",
        ),
        (
            "https://artworks.thetvdb.com/banners/posters/81189-1.jpg",
            "poster",
            "https://artworks.thetvdb.com/banners/posters/81189-1_t.jpg",
        ),
        ("https://theposterdb.com/api/assets/207889", "poster", None),
        ("https://cdn.example.test/poster.jpg", "poster", None),
    ],
)
def test_art_preview_url_uses_each_sources_smaller_rendition(
    url: str, art_type: str, preview: str | None
) -> None:
    assert art_preview_url(url, ArtType(art_type)) == preview


@pytest.mark.parametrize(
    ("url", "label"),
    [
        ("https://media.themoviedb.org/t/p/w500/a.jpg", "tmdb"),
        ("https://theposterdb.com/api/assets/1", "tpdb"),
        ("https://assets.fanart.tv/fanart/a.png", "fanart"),
        ("https://artworks.thetvdb.com/banners/a.jpg", "tvdb"),
        ("https://metadata-static.plex.tv/a.jpg", "plex"),
        ("https://m.media-amazon.com/images/M/a.jpg", "amazon"),
        ("https://cdn.example.org/a.jpg", "example"),
        ("not a url", "external"),
    ],
)
def test_art_source_label_names_known_sources_then_sites(url: str, label: str) -> None:
    assert art_source_label(url) == label


def test_art_sources_are_the_catalog_sources_and_overturedb() -> None:
    hosts = {art_source(f"https://{host}/") for host in ART_HOSTS}

    assert hosts == set(ArtSource) - {ArtSource.OVERTUREDB}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (None, None),
        (TMDB, ArtSource.TMDB),
        ("https://theposterdb.com/api/assets/1", ArtSource.TPDB),
        ("https://assets.fanart.tv/fanart/movies/1/a.jpg", ArtSource.FANART),
        # Amazon serves artwork but is not a host the catalog links to.
        ("https://m.media-amazon.com/images/M/abc.jpg", None),
        ("https://img.test/poster.jpg", None),
    ],
)
def test_selected_art_source_is_the_catalog_host(
    url: str | None, expected: ArtSource | None
) -> None:
    assert selected_art_source(url) == expected


def test_tmdb_candidates_are_canonical_and_skip_unusable_files(
    *, app_config: Settings
) -> None:
    art = extract_art(
        {"posters": [{"file_path": "/a.jpg"}, {"file_path": "/logo.svg"}, {}]},
        ArtType.POSTER,
    )

    assert art == [
        ArtCandidate(
            url="https://image.tmdb.org/t/p/original/a.jpg",
            preview_url="https://image.tmdb.org/t/p/w342/a.jpg",
            width=0,
            height=0,
            iso_639_1=None,
            source="tmdb",
        )
    ]


def test_overturedb_candidates_carry_a_preview() -> None:
    assert build_candidate(TMDB, ArtType.BACKGROUND) == ArtCandidate(
        url=TMDB,
        preview_url=TMDB.replace("/original/", "/w780/"),
        source="tmdb",
        title="OvertureDB",
        art_type=ArtType.BACKGROUND,
    )
