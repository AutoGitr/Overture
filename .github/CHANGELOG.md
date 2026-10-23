# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

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
