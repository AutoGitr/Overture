"""Plex API client."""

lazy import asyncio
lazy import logging
lazy import urllib.parse
lazy from collections.abc import AsyncIterator, Callable, Collection, Mapping, Sequence
lazy from ipaddress import IPv4Address
lazy from typing import Any, ClassVar, Literal, override

lazy import httpx2

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import (
    ArtType,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    MediaType,
)
lazy from ...integrations.http import LazyClient, create_client
lazy from ...schemas.art import ArtCandidate
lazy from ...utils.art_urls import art_preview_url, art_source_label, public_art_url
lazy from ...utils.image import sniff_image_size
lazy from ...utils.ssrf import LOOPBACK_HOSTS
lazy from ...version import APP_VERSION
lazy from ..adapters import ServerTheme
lazy from ..errors import MediaServerError
lazy from ..http_client import MediaServerHttpClient
lazy from ..wire import (
    PlexMetadata,
    PlexResource,
    PlexSection,
    plex_artwork_page,
    plex_items,
    plex_machine_identifier,
    plex_page,
    plex_resources,
    plex_sections_page,
    wire_object,
)

logger = logging.getLogger(__name__)

#: How Overture introduces itself to Plex and plex.tv.
_CLIENT_HEADERS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "X-Plex-Client-Identifier": "overture-server",
        "X-Plex-Product": "Overture",
        "X-Plex-Version": APP_VERSION,
        "Accept": "application/json",
    }
)
#: The port Plex listens on unless it is told otherwise.
_PLEX_PORT = 32400
#: The artwork listing that offers each art type's alternatives.
_ARTWORK_LISTING = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        ArtType.POSTER: "posters",
        ArtType.SEASON_POSTER: "posters",
        ArtType.BACKGROUND: "arts",
    }
)

#: Plex's metadata type number of each media type.
_PLEX_TYPES = frozendict(
    {MediaType.MOVIE: 1, MediaType.SHOW: 2}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)
#: Plex's metadata type number for episodes, whose fields show sections test.
_EPISODE_TYPE = 4
#: The member orders Plex keeps itself; others are stored as a custom order.
PLEX_COLLECTION_SORTS: frozendict[CollectionOrder, int] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        CollectionOrder.RELEASE_ASC: 0,
        CollectionOrder.TITLE_ASC: 1,
    }
)
PLEX_CUSTOM_SORT = 2
#: The collection preferences Plex stores as numbers, as plexapi names them.
PLEX_COLLECTION_MODES: frozendict[CollectionMode, int] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        CollectionMode.DEFAULT: -1,
        CollectionMode.HIDE: 0,
        CollectionMode.HIDE_ITEMS: 1,
        CollectionMode.SHOW_ITEMS: 2,
    }
)
PLEX_COLLECTION_FILTERING: frozendict[CollectionFiltering, int] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        CollectionFiltering.ADMIN: 0,
        CollectionFiltering.USER: 1,
    }
)


def _filter_key(key: str) -> str:
    """Decode a filter value's key; Plex percent-encodes some once or twice.

    Studios arrive as ``A%2520B`` and ratings as ``16%2B``, and Plex matches
    only the decoded value.
    """
    while (decoded := urllib.parse.unquote(key)) != key:
        key = decoded
    return key


def plex_web_link(
    kind: Literal["metadata", "collections"],
    rating_key: str,
    machine_id: str | None,
    *,
    app_config: Settings,
) -> str:
    """Return the Plex web link of an item or collection."""
    key = f"/library/{kind}/{rating_key}"
    if machine_id:
        return (
            "https://app.plex.tv/desktop/#!/server/"
            f"{machine_id}/details?key={urllib.parse.quote(key, safe='')}"
        )
    return (
        f"{app_config.MEDIA_SERVER_URL}/web/index.html"
        f"#!/server/details?key={urllib.parse.quote(key, safe='')}"
    )


def _owned_servers(resources: list[PlexResource]) -> list[PlexResource]:
    """Return the media servers the account owns among its plex.tv resources.

    The token is the owner's, so it must never reach a server shared with the
    account, whose LAN address can also collide with the owner's.
    """
    return [
        resource
        for resource in resources
        if "server"
        in {item.strip() for item in resource.get("provides", "").split(",")}
        and resource.get("owned")
        and resource.get("clientIdentifier")
    ]


def _server_at(servers: list[PlexResource], url: str) -> str | None:
    """Return the server listed at *url*'s address, or the only one there is."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port or _PLEX_PORT
    matches = {
        server.get("clientIdentifier")
        for server in servers
        for connection in server.get("connections") or []
        if connection.get("address", "").lower() == host
        and connection.get("port") == port
    }
    if len(matches) == 1:
        return matches.pop()
    if not matches and len(servers) == 1:
        return servers[0].get("clientIdentifier")
    return None


def _secure_candidates(
    server: PlexResource, url: str, *, app_config: Settings
) -> list[str]:
    """Return the server's plex.direct origins in the order to prefer them.

    The configured IPv4 address comes first under the server's certificate
    domain, since plex.tv lists the addresses Plex sees, not the one a
    container network or port mapping exposes. Local addresses follow before
    remote ones, so LAN traffic stays off the WAN.
    """
    connections = sorted(
        server.get("connections") or [],
        key=lambda connection: not connection.get("local", False),
    )
    origins = [
        origin
        for connection in connections
        if (origin := app_config.plex_direct_origin(connection.get("uri", "")))
    ]
    if origins:
        # plex.direct names are <address>.<server hash>.plex.direct.
        domain = (urllib.parse.urlsplit(origins[0]).hostname or "").split(".", 1)[1]
        origins.insert(0, app_config.plex_direct_origin(_address_origin(url, domain)))
    return list(dict.fromkeys(origin for origin in origins if origin))


def _address_origin(url: str, domain: str) -> str:
    """Return the HTTPS origin naming *url*'s IPv4 address in *domain*, or ``""``."""
    parsed = urllib.parse.urlsplit(url)
    try:
        address = IPv4Address(parsed.hostname or "")
    except ValueError:
        return ""
    return (
        f"https://{str(address).replace('.', '-')}.{domain}:{parsed.port or _PLEX_PORT}"
    )


class PlexClient(MediaServerHttpClient):
    """Interface to the Plex Media Server API."""

    _PAGE_PARAMETERS: ClassVar[tuple[str, str]] = (
        "X-Plex-Container-Start",
        "X-Plex-Container-Size",
    )

    def __init__(
        self,
        *,
        app_config: Settings,
        client_factory: Callable[..., httpx2.AsyncClient] = create_client,
    ) -> None:
        """Initialize instance state."""
        super().__init__(app_config=app_config, client_factory=client_factory)
        self._machine_identifier: str | None = None

        async def build_public() -> httpx2.AsyncClient:
            return client_factory()

        #: Credential-free client shared by public image probes.
        self._public_images = LazyClient(build_public, name="Plex public image")

    @property
    @override
    def auth_headers(self) -> dict[str, str]:
        """Authenticate with the configured Plex token."""
        return {
            "X-Plex-Token": self._app_config.MEDIA_SERVER_API_KEY.get_secret_value()
        }

    @override
    async def close(self) -> None:
        """Close both the media-server API client and public image client."""
        await super().close()
        await self._public_images.close()

    async def get_machine_identifier(self) -> str | None:
        """Get the Plex server machine identifier."""
        if self._machine_identifier:
            return self._machine_identifier
        try:
            self._machine_identifier = plex_machine_identifier(
                await self._get("/identity")
            )
        except (httpx2.HTTPError, ValueError) as e:
            logger.warning("Could not read the Plex machine identifier: %s", e)
            return None
        return self._machine_identifier

    async def resolve_secure_url(self) -> str | None:
        """Return a verified plex.direct origin, or ``None`` to keep the configured URL.

        Plex's certificate names only plex.direct hosts, and "Required" secure
        connections refuse plain HTTP, so a configured URL that is not already
        verified HTTPS is upgraded to an address plex.tv lists for the server.
        Raises when the server answers at neither.
        """
        configured = self._app_config.MEDIA_SERVER_URL
        parsed = urllib.parse.urlsplit(configured)
        verify = self._app_config.media_server_verify_tls()
        identity = await self._identify(configured, verify=verify)
        if identity and (
            (parsed.scheme == "https" and verify) or parsed.hostname in LOOPBACK_HOSTS
        ):
            self._machine_identifier = identity
            return None

        servers = await self._account_servers()
        machine_id = identity or _server_at(servers, configured)
        server = next(
            (s for s in servers if s.get("clientIdentifier") == machine_id), None
        )
        if machine_id and server:
            self._machine_identifier = machine_id
            candidates = _secure_candidates(
                server, configured, app_config=self._app_config
            )
            # Probe every address at once but take the most preferred one that
            # proves the server's identity under a verified certificate.
            probes = [
                asyncio.create_task(self._identify(candidate, verify=True))
                for candidate in candidates
            ]
            try:
                for candidate, probe in zip(candidates, probes, strict=True):
                    if await probe == machine_id:
                        logger.info("Connected to Plex securely through plex.direct")
                        return self._app_config.trust_plex_secure_url(candidate)
            finally:
                for probe in probes:
                    probe.cancel()
                await asyncio.gather(*probes, return_exceptions=True)
            if candidates:
                logger.warning(
                    "No plex.direct address of the Plex server answered; check "
                    "that DNS rebinding protection allows plex.direct"
                )

        if identity:
            self._machine_identifier = identity
            return None
        raise MediaServerError("Media server is unavailable", status_code=503)

    async def _identify(self, origin: str, *, verify: bool) -> str | None:
        """Return the machine identifier the server at *origin* reports."""
        try:
            async with self._client_factory(
                base_url=origin, verify=verify, headers=dict(_CLIENT_HEADERS)
            ) as client:
                response = await client.get("/identity")
                response.raise_for_status()
                return plex_machine_identifier(response.json())
        except (httpx2.HTTPError, ValueError) as exc:
            logger.debug("Plex did not identify itself: %s", exc)
            return None

    async def _account_servers(self) -> list[PlexResource]:
        """Return the media servers the token's account owns, or none."""
        try:
            async with self._client_factory(
                headers={**_CLIENT_HEADERS, **self.auth_headers}
            ) as client:
                response = await client.get(
                    "https://plex.tv/api/v2/resources", params={"includeHttps": 1}
                )
                response.raise_for_status()
                return _owned_servers(plex_resources(response.json()))
        except (httpx2.HTTPError, ValueError) as exc:
            logger.warning("Could not list the Plex servers on plex.tv: %s", exc)
            return []

    async def base_url(self) -> str:
        """Return the origin Plex is reached at, secure when plex.tv offers one."""
        return str((await self.get_client()).base_url).rstrip("/")

    @override
    async def _create_client(self) -> httpx2.AsyncClient:
        """Build an authenticated Plex client, preferring a secure origin."""
        base_url = await self.resolve_secure_url() or self._app_config.MEDIA_SERVER_URL
        return self._client_factory(
            base_url=base_url,
            verify=self._app_config.media_server_verify_tls(base_url),
            headers={**_CLIENT_HEADERS, **self.auth_headers},
        )

    @override
    async def _get(self, path: str, **kwargs: Any) -> Any:
        response = await self._request("GET", path, **kwargs)
        data = wire_object(self._json(response))
        container = wire_object(data.get("MediaContainer"))
        data["MediaContainer"] = container
        for field, header in (
            ("totalSize", "X-Plex-Container-Total-Size"),
            ("offset", "X-Plex-Container-Start"),
        ):
            if header in response.headers:
                try:
                    value = int(response.headers[header])
                except ValueError as exc:
                    raise MediaServerError(
                        "Plex returned invalid pagination headers"
                    ) from exc
                if field in container and container[field] != value:
                    raise MediaServerError(
                        "Plex returned conflicting pagination metadata"
                    )
                container[field] = value
        return data

    async def get_sections(self) -> list[PlexSection]:
        return await self._pages(
            "/library/sections/all",
            params=None,
            parse=plex_sections_page,
            identity=lambda section: str(section["key"]),
        )

    async def _metadata(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[PlexMetadata]:
        return await self._pages(
            path,
            params=params,
            parse=plex_page,
            identity=lambda item: str(item["ratingKey"]),
        )

    async def iter_section_items(
        self, section_key: str
    ) -> AsyncIterator[list[PlexMetadata]]:
        """Yield validated media pages without retaining the whole section.

        Plex builds each response on one thread, so four pages in flight
        listed 3,758 movies in 0.9 s against 1.5 s one page at a time.
        """
        async for page in self._page_batches(
            f"/library/sections/{section_key}/all",
            params={"includeGuids": 1},
            parse=plex_page,
            identity=lambda item: str(item["ratingKey"]),
            track_all_ids=False,
            require_total=True,
            prefetch=4,
        ):
            yield page

    async def get_shows_with_seasons(self, show_keys: list[str]) -> list[PlexMetadata]:
        """Return shows with their folders and season rows in one request.

        Plex lists shows without folders or season episode counts; the
        metadata of up to a page of shows carries both.
        """
        return plex_items(
            await self._get(
                f"/library/metadata/{','.join(show_keys)}",
                params={"includeChildren": 1},
            )
        )

    async def get_metadata(
        self, rating_key: str, *, include_fields: str | None = None
    ) -> PlexMetadata | None:
        params = {"includeFields": include_fields} if include_fields else None
        items = plex_items(
            await self._get(f"/library/metadata/{rating_key}", params=params)
        )
        return items[0] if items else None

    async def get_children(
        self, rating_key: str, *, include_fields: str | None = None
    ) -> list[PlexMetadata]:
        params = {"includeFields": include_fields} if include_fields else None
        return await self._metadata(f"/library/metadata/{rating_key}/children", params)

    async def get_art_url(
        self, rating_key: str, field: Literal["thumb", "art"]
    ) -> str | None:
        metadata = await self.get_metadata(rating_key, include_fields=field)
        url = metadata.get(field) if metadata else None
        return await self.asset_url(url) if url else None

    async def _theme_id(self, rating_key: str) -> str | None:
        """Return the version of the item's theme, or ``None`` without one."""
        metadata = await self.get_metadata(rating_key, include_fields="theme")
        theme = metadata.get("theme") if metadata else None
        return str(theme) if theme else None

    async def asset_url(self, path: str) -> str:
        """Return the absolute URL of a Plex asset path."""
        if path.startswith("/") and not path.startswith("//"):
            client = await self.get_client()
            return f"{str(client.base_url).rstrip('/')}{path}"
        parsed = urllib.parse.urlsplit(path)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
        ):
            raise MediaServerError("Plex returned an invalid asset URL")
        return path

    @override
    async def find_item_id(self, item: MediaItem) -> str | None:
        """Find a Plex ratingKey by matching GUIDs, memoized per item identity."""
        return await self._cache.get_or_compute(
            ("find_item", item.media_type, item.tmdb_id, item.tvdb_id, item.imdb_id),
            self._find_item_id,
            item,
        )

    async def _find_item_id(self, item: MediaItem) -> str | None:
        wanted = {
            f"{source}://{value}"
            for source, value in (
                ("tmdb", item.tmdb_id),
                ("tvdb", item.tvdb_id),
                ("imdb", item.imdb_id),
            )
            if value is not None
        }
        for section in await self.get_sections():
            if section["type"] != item.media_type:
                continue
            items = await self._metadata(
                f"/library/sections/{section['key']}/all",
                {"title": item.title, "includeGuids": 1, "includeFields": "ratingKey"},
            )
            for metadata in items:
                if wanted.intersection(
                    guid.get("id", "") for guid in metadata.get("Guid") or []
                ):
                    return str(metadata["ratingKey"])
        return None

    @override
    async def find_season_id(self, show_id: str, season_num: int) -> str | None:
        for season in await self.get_children(
            show_id, include_fields="index,ratingKey"
        ):
            if season.get("index") == season_num:
                return str(season["ratingKey"])
        return None

    @override
    async def get_art_candidates(
        self, item_id: str, art_type: ArtType
    ) -> list[ArtCandidate]:
        """Get alternate art candidates from Plex, cached by item."""
        return await self._cache.get_or_compute(
            ("art", item_id, art_type),
            self._get_art_candidates,
            item_id,
            art_type,
        )

    async def _get_art_candidates(
        self, rating_key: str, art_type: ArtType
    ) -> list[ArtCandidate]:
        raw_items = await self._pages(
            f"/library/metadata/{rating_key}/{_ARTWORK_LISTING[art_type]}",
            params={"includeFields": "key,thumb,width,height"},
            parse=plex_artwork_page,
            identity=None,
        )

        results: list[ArtCandidate] = []
        seen: set[str] = set()
        dns_cache: dict[str, asyncio.Task[bool]] = {}
        for raw in raw_items:
            key = raw.get("key", "") or raw.get("thumb", "")
            if not key:
                continue
            url = await public_art_url(
                key, dns_cache=dns_cache, app_config=self._app_config
            )
            if url is None or url in seen:
                continue
            seen.add(url)
            results.append(
                ArtCandidate(
                    url=url,
                    preview_url=art_preview_url(url, art_type) or url,
                    width=raw.get("width") or 0,
                    height=raw.get("height") or 0,
                    source=art_source_label(url),
                )
            )

        missing_sizes = [result for result in results if not result.area]
        if not missing_sizes:
            return results
        sniff_slots = asyncio.Semaphore(16)
        sniffer = await self._public_images.get()

        async def _get_size(candidate: ArtCandidate) -> None:
            async with sniff_slots:
                candidate.width, candidate.height = await sniff_image_size(
                    candidate.url, sniffer
                )

        await asyncio.gather(*(_get_size(result) for result in missing_sizes))
        return results

    async def unlock_fields(self, rating_key: str, fields: Collection[str]) -> None:
        """Unlock *fields* (``thumb``, ``art``, ``theme``) for a refresh to replace."""
        if fields:
            await self._request(
                "PUT",
                f"/library/metadata/{rating_key}",
                params={f"{field}.locked": "0" for field in sorted(fields)},
            )

    async def refresh_item(self, rating_key: str, *, unlock: Collection[str]) -> None:
        """Refresh an item so it adopts its local files for the *unlock* fields.

        Plex picks up an item's local artwork and theme on refresh only once
        its poster listing has been read, as its metadata editor does; without
        that read, the refresh leaves a missing or uploaded asset in place.
        Reading the theme or background listing instead does not help.
        """
        await self._request(
            "GET", f"/library/metadata/{rating_key}/posters", allow_not_found=True
        )
        await self.unlock_fields(rating_key, unlock)
        await self._request("PUT", f"/library/metadata/{rating_key}/refresh")

    @override
    async def get_theme_songs(self, item_id: str) -> list[ServerTheme]:
        """Return the item's theme, if any, with the URL that serves its file.

        The URL leaves out the version segment of the ``theme`` field, as the
        collection-theme check does: Plex serves the same file either way, and
        requests with the segment coincided with "Time value greater than
        duration" in its log.
        """
        if not await self._theme_id(item_id):
            return []
        url = await self.asset_url(f"/library/metadata/{item_id}/theme")
        return [ServerTheme(id=item_id, url=url)]

    async def delete_theme(self, rating_key: str) -> None:
        """Delete the item's theme; Plex locks the field until it is unlocked."""
        await self._request("DELETE", f"/library/metadata/{rating_key}/theme")

    async def get_collections(self, section_key: str) -> list[PlexMetadata]:
        """Return a section's collections with their theme field."""
        return await self._metadata(
            f"/library/sections/{section_key}/collections",
            {"includeGuids": 0, "includeFields": "theme"},
        )

    async def get_collection_member_ids(self, rating_key: str) -> list[str]:
        """Return the rating keys of the items a collection holds."""
        children = await self._metadata(
            f"/library/collections/{rating_key}/children", {"includeGuids": 0}
        )
        return [str(child["ratingKey"]) for child in children]

    async def upload_collection_theme(self, rating_key: str, mp3_bytes: bytes) -> str:
        await self._request(
            "POST",
            f"/library/metadata/{rating_key}/themes",
            content=mp3_bytes,
            headers={"Content-Type": "audio/mpeg"},
            timeout=300,
        )
        await self.unlock_fields(rating_key, ("theme",))
        theme_id = await self._theme_id(rating_key)
        if not theme_id:
            raise MediaServerError("Plex did not return the uploaded collection theme")
        return theme_id

    async def delete_collection_theme(self, rating_key: str) -> None:
        """Delete a collection theme and unlock the field the deletion locked."""
        await self.delete_theme(rating_key)
        await self.unlock_fields(rating_key, ("theme",))

    @override
    async def test_connection(self) -> bool:
        try:
            plex_machine_identifier(await self._get("/identity"))
        except MediaServerError:
            return False
        return True

    async def _collection_uri(self, member_ids: list[str]) -> str:
        machine_id = await self.get_machine_identifier()
        if not machine_id:
            raise MediaServerError("Plex returned no server identity")
        return f"server://{machine_id}/com.plexapp.plugins.library/library/metadata/{','.join(member_ids)}"

    async def _smart_collection_uri(
        self, section_key: str, media_type: MediaType, filter_query: str
    ) -> str:
        machine_id = await self.get_machine_identifier()
        if not machine_id:
            raise MediaServerError("Plex returned no server identity")
        type_num = _PLEX_TYPES[media_type]
        suffix = f"&{filter_query}" if filter_query else ""
        return (
            f"server://{machine_id}/com.plexapp.plugins.library"
            f"/library/sections/{section_key}/all?type={type_num}{suffix}"
        )

    async def create_collection(
        self, section_key: str, title: str, media_type: MediaType, member_ids: list[str]
    ) -> PlexMetadata:
        """Create a regular collection, with its initial members."""
        response = await self._request(
            "POST",
            "/library/collections",
            params={
                "sectionId": section_key,
                "title": title,
                "smart": "0",
                "type": _PLEX_TYPES[media_type],
                "uri": await self._collection_uri(member_ids),
            },
        )
        rows = plex_items(self._json(response))
        if len(rows) != 1:
            raise MediaServerError("Plex did not return the new collection")
        return rows[0]

    async def create_smart_collection(
        self,
        section_key: str,
        title: str,
        media_type: MediaType,
        filter_query: str,
    ) -> PlexMetadata:
        """Create a smart collection backed by a Plex filter query."""
        response = await self._request(
            "POST",
            "/library/collections",
            params={
                "sectionId": section_key,
                "title": title,
                "smart": "1",
                "type": _PLEX_TYPES[media_type],
                "uri": await self._smart_collection_uri(
                    section_key, media_type, filter_query
                ),
            },
        )
        rows = plex_items(self._json(response))
        if len(rows) != 1:
            raise MediaServerError("Plex did not return the new smart collection")
        return rows[0]

    async def update_smart_collection_filter(
        self,
        collection_id: str,
        section_key: str,
        media_type: MediaType,
        filter_query: str,
    ) -> None:
        """Update the filter URI of an existing smart collection."""
        await self._request(
            "PUT",
            f"/library/collections/{collection_id}/items",
            params={
                "uri": await self._smart_collection_uri(
                    section_key, media_type, filter_query
                )
            },
        )

    async def sync_item_labels(
        self,
        section_key: str,
        media_type: MediaType,
        label: str,
        *,
        add: Mapping[str, Sequence[str]],
        remove_ids: list[str],
    ) -> None:
        """Add and remove a managed label on items in a Plex section.

        Plex replaces an item's labels with the ``label[i]`` it is sent, so an
        addition resends the labels each item already has; items that share
        them share a request.
        """
        type_num = _PLEX_TYPES[media_type]
        groups: dict[tuple[str, ...], list[str]] = {}
        for item_id, existing in add.items():
            others = {tag for tag in existing if tag.casefold() != label.casefold()}
            kept = tuple(sorted({*others, label}, key=str.casefold))
            groups.setdefault(kept, []).append(item_id)
        for labels, ids in groups.items():
            await self._request(
                "PUT",
                f"/library/sections/{section_key}/all",
                params={
                    "type": type_num,
                    "id": ",".join(sorted(ids)),
                    "includeExternalMedia": 1,
                    **{
                        f"label[{index}].tag.tag": tag
                        for index, tag in enumerate(labels)
                    },
                    "label.locked": 1,
                },
            )
        if remove_ids:
            await self._request(
                "PUT",
                f"/library/sections/{section_key}/all",
                params={
                    "type": type_num,
                    "id": ",".join(remove_ids),
                    "includeExternalMedia": 1,
                    "label[].tag.tag-": label,
                },
            )

    async def get_filter_choices(
        self, section_key: str, media_type: MediaType, field: str
    ) -> list[tuple[str, str]]:
        """List the keys and names of a field's values in a section.

        Show sections list the values of an ``episode.`` field among episodes.
        """
        episode_field = field.removeprefix("episode.")
        data = await self._get(
            f"/library/sections/{section_key}/{episode_field}",
            params={
                "type": _EPISODE_TYPE
                if episode_field != field
                else _PLEX_TYPES[media_type]
            },
        )
        entries: list[object] = data["MediaContainer"].get("Directory") or []
        return [
            (key, str(entry.get("title") or key))
            for entry in map(wire_object, entries)
            if entry.get("key") is not None and (key := _filter_key(str(entry["key"])))
        ]

    async def find_matching(
        self, section_key: str, media_type: MediaType, filter_query: str, size: int
    ) -> tuple[int, list[str]]:
        """How many items a smart filter matches, and the first *size* of them."""
        suffix = f"&{filter_query}" if filter_query else ""
        data = await self._get(
            f"/library/sections/{section_key}/all?type={_PLEX_TYPES[media_type]}{suffix}",
            params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": size},
        )
        page = plex_page(data)
        return (
            page.total if page.total is not None else len(page.items),
            [str(key) for row in page.items if (key := row.get("ratingKey"))],
        )

    async def order_collection_hubs(
        self, section_key: str, collection_ids: Sequence[str]
    ) -> None:
        """Put promoted collections' rows first on Plex's Home, in this order.

        Plex names a collection's hub after its section and rating key; each
        moves after the previous one, the first to the top.
        """
        previous: str | None = None
        for collection_id in collection_ids:
            identifier = f"custom.collection.{section_key}.{collection_id}"
            await self._request(
                "PUT",
                f"/hubs/sections/{section_key}/manage/{identifier}/move",
                params={"after": previous} if previous else None,
            )
            previous = identifier

    async def delete_collection(self, collection_id: str) -> None:
        """Delete only the collection metadata."""
        await self._request("DELETE", f"/library/metadata/{collection_id}")

    async def set_collection_members(
        self,
        collection_id: str,
        member_ids: list[str],
        order: CollectionOrder,
        *,
        append: bool = False,
    ) -> list[str]:
        """Use Plex's item endpoints; children is a read-only listing."""
        current_ids = await self.get_collection_member_ids(collection_id)
        current = set(current_ids)
        if append:
            requested = set(member_ids)
            member_ids = [
                *member_ids,
                *(identity for identity in current_ids if identity not in requested),
            ]
        wanted = set(member_ids)
        additions = [item for item in member_ids if item not in current]
        if additions:
            await self._request(
                "PUT",
                f"/library/collections/{collection_id}/items",
                params={"uri": await self._collection_uri(additions)},
            )
        for item in sorted(current - wanted):
            await self._request(
                "DELETE", f"/library/collections/{collection_id}/items/{item}"
            )
        server_order = [item for item in current_ids if item in wanted] + additions
        if order not in PLEX_COLLECTION_SORTS and server_order != member_ids:
            for position, item in enumerate(member_ids):
                await self._request(
                    "PUT",
                    f"/library/collections/{collection_id}/items/{item}/move",
                    params={"after": member_ids[position - 1]} if position else {},
                )

        return member_ids

    async def update_collection_details(
        self,
        collection_id: str,
        *,
        title: str,
        summary: str | None,
        sort_title: str | None,
        mode: CollectionMode,
        order: CollectionOrder,
        smart: bool,
        visible_home: bool,
        visible_shared: bool = False,
        visible_library: bool = False,
        filtering: CollectionFiltering | None = None,
    ) -> None:
        """Edit collection metadata and its library visibility preferences.

        ``None`` leaves the summary or sort title as it is; an empty sort title
        hands it back to Plex. Plex rejects a smart collection's
        ``collectionSort`` (its query sorts it) and a regular collection's
        ``collectionFilterBasedOnUser`` with 400 Bad Request.
        """
        fields: dict[str, str | int] = {"title.value": title, "title.locked": 1}
        if summary is not None:
            fields |= {"summary.value": summary, "summary.locked": int(bool(summary))}
        if sort_title is not None:
            fields |= {
                "titleSort.value": sort_title,
                "titleSort.locked": int(bool(sort_title)),
            }
        await self._request("PUT", f"/library/metadata/{collection_id}", params=fields)
        prefs: dict[str, int] = {"collectionMode": PLEX_COLLECTION_MODES[mode]}
        if not smart:
            prefs["collectionSort"] = PLEX_COLLECTION_SORTS.get(order, PLEX_CUSTOM_SORT)
        elif filtering is not None:
            prefs["collectionFilterBasedOnUser"] = PLEX_COLLECTION_FILTERING[filtering]
        await self._request(
            "PUT",
            f"/library/metadata/{collection_id}/prefs",
            params=prefs,
        )
        metadata = await self.get_metadata(collection_id)
        section_id = metadata.get("librarySectionID") if metadata else None
        if section_id is None:
            raise MediaServerError("Plex returned no collection library")
        path = f"/hubs/sections/{section_id}/manage"
        data = wire_object(
            await self._get(path, params={"metadataItemId": collection_id})
        )
        container = wire_object(data.get("MediaContainer"))
        hubs: list[dict[str, Any]] = container.get("Hub") or []
        hub = next(
            (
                row
                for row in hubs
                if row.get("identifier")
                == f"custom.collection.{section_id}.{collection_id}"
            ),
            None,
        )
        params: dict[str, int | str] = {"promotedToOwnHome": int(visible_home)}
        if visible_shared or (hub and hub.get("promotedToSharedHome")):
            params["promotedToSharedHome"] = int(visible_shared)
        if visible_library or (hub and hub.get("promotedToRecommended")):
            params["promotedToRecommended"] = int(visible_library)
        if hub:
            await self._request("PUT", f"{path}/{hub['identifier']}", params=params)
        elif visible_home or visible_shared or visible_library:
            await self._request(
                "POST", path, params={**params, "metadataItemId": collection_id}
            )

    async def upload_collection_art(
        self, collection_id: str, art_type: ArtType, image_bytes: bytes, mime_type: str
    ) -> None:
        """Upload bytes rather than asking Plex to fetch an arbitrary URL."""
        endpoint = "art" if art_type is ArtType.BACKGROUND else "posters"
        await self._request(
            "POST",
            f"/library/metadata/{collection_id}/{endpoint}",
            content=image_bytes,
            headers={"Content-Type": mime_type},
        )
