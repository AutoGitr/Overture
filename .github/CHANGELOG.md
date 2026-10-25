# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Composable multi-source collection builders supporting TMDB franchises, item IDs, person credits (with actor, director, writer, producer, and biography roles), MDBList, Radarr and Sonarr tags, recursive filter trees, Plex smart collections with boolean condition groups and managed labels, seasonal calendar windows, dynamic TMDB franchise group discovery, and summary format templates.

- Collection group defaults for sync, minimum membership, automatic assets, Plex visibility and sort-title templates, with individual rule overrides. Filtered bulk actions and empty-collection maintenance keep media files intact.
- Collection Configure shows TMDB source rosters, including missing franchise movies.

- Generate TMDB franchise collections from a synced movie library, and organize collections with preset or custom groups.

- Create, edit and delete Plex, Jellyfin and Emby collections, manage library members, and select collection posters and backgrounds. Plex supports custom member order, collection visibility and home promotion.
- Build dynamic collections from MDBList lists, TMDB franchises or library filters, with scheduled sync, inherited defaults and minimum member thresholds. Set `MDBLIST_API_KEY` for MDBList; the generator previews decade, genre and studio collections before creation.

- Browse the full OvertureDB catalog from the sidebar, filter movies, shows and collections, and save local artwork and theme drafts to contribute through GitHub or the ZIP export.
- Collection pages show their members, explicit TMDB identity and OvertureDB/ThemerrDB theme candidates. Jellyfin 12 collection themes write into a mounted collections directory configured with `JELLYFIN_COLLECTIONS_PATH`.

- Assets can include collection themes for selected libraries or the current collection sidebar, using the configured catalog source order. Newly identified collections can receive catalog themes automatically from an enabled incremental sync policy.

### Changed

- Collection creation and editing share Collection Setup for library, source, title and group, with franchise discovery inside Setup and content, members, display and schedule sections adapted to your choices. New collections open directly at Setup without an empty poster.

- Example Docker Compose configuration delegates all environment variables directly to `.env`.

- Collection groups hide their contents until opened, and share sidebar browsing with TMDB franchises. Art/theme badges and detail controls now share status and clear behavior; Emby collections hide unsupported theme badges.
- Creating a collection opens a fresh Configure page with library selection instead of a popup. Collection TMDB IDs are explicit and survive membership changes; existing IDs are preserved on upgrade, and automatic voting/matching controls are removed.
- Detail header boxes size to their contents with consistent button spacing and icon-only record actions. Collections without TMDB IDs skip artwork candidate requests.

- Item and collection headers use two continuous, stable boxes. Collections consolidate metadata, builder rules, explicit TMDB IDs and live members into Configure, with shared Save Changes and Sync Now controls.

- Plex and Jellyfin collections and their members are stored locally and refreshed on full syncs. Set an explicit TMDB collection ID for franchise artwork and catalog theme suggestions.
- Local artwork is cached under `<config>/cache/images/{originals,thumbs}` by BLAKE3 hash and served as AVIF display thumbnails across the UI, with cached originals used when opening posters at full size.

### Removed

- Legacy collection preset generator and single-source rule endpoints in favor of composable builders and group dynamic discovery.
- Collection matching endpoints and automatic member voting. Set `tmdb_collection_id` through collection creation or update instead.
- The Plex-only Enable Collections setting. Collection navigation follows the configured server's capability.

### Fixed

- Switching collection sources no longer submits hidden smart filters or stale manual members. Plex smart collections show server-controlled members without manual editing, and smart filters can use source builders through managed labels.

- Collection member ordering supports row-wide drag-and-drop and Up/Down controls, collection artwork links follow the selected slot, and create/generate selections stay consistent when changing libraries.

- OvertureDB item, collection, season and member images now show only catalog artwork or local draft overrides. Missing images use placeholders, and poster cards share consistent typography and spacing.
- OvertureDB pages reuse library artwork, season and theme views, with consistent links and clearable status badges. Draft artwork appears in the sidebar, and the original catalog artwork is offered only after a draft exists.
- Full Sync reports collection lookups, respects the selected libraries, and stops pending requests promptly when Stop is selected.
- Collection members appear in a linked poster grid. TMDB identity is available only for movie collections.
- Collection routes and queued downloads use stable database IDs, with migrated history and cascading cleanup. Jellyfin theme files retain their hashes and source provenance independently of Plex theme IDs.
- Unavailable Jellyfin mounts preserve saved state, and listed BoxSets keep their explicit IDs even when none of their members are visible locally.
- Catalog drafts stay editable after correcting their only identifier. Collection theme exports preserve ThemerrDB attribution, and catalog counts no longer require downloading the entire catalog.

- When YouTube or an artwork source such as ThePosterDB rate-limits Overture, Overture pauses its requests to that service, for longer each time the limit repeats. Theme and artwork downloads and bulk runs wait the pause out; theme searches, artwork matching, choosing artwork and media-server previews in the UI say when to try again.
- Assets runs that use only OvertureDB or ThemerrDB report artwork slots and themes the catalog has nothing for as No match, instead of skipping them as a saved selection that Overwrite existing would search again. Saved choices include the artwork URLs Sync copies from your media server, so this affected most items the catalog covers only partly.
- Assets logs say exactly why the catalogs had nothing: no OvertureDB entry, no artwork of that kind or no theme in the entry, or a theme that failed to download before. They also say whether a skipped saved choice is already the catalog's or differs from it. While OvertureDB is disabled, its targets are reported as Skipped because OvertureDB is disabled, instead of as No match.
- Failed theme downloads, YouTube searches and artwork downloads now say why, such as YouTube's own error or the HTTP status an artwork source returned, instead of a generic or truncated message.

## [1.1.0] - 2026-10-22

### Added

First stable public release of Overture

- Choose artwork and theme songs for Plex, Jellyfin and Emby
  libraries from your media server, TMDB, OvertureDB, ThemerrDB and YouTube,
  saved as files beside your media.
- Scheduled syncs and artwork and theme runs, along with renaming and audit functionality.
- Multi-platform container images on GHCR and Docker Hub, tagged with the full,
  minor and major version, and a native Linux archive with a systemd service.
