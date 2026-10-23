# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- When YouTube rate-limits theme downloads or searches, Overture pauses its YouTube requests, waiting longer each time the limit repeats, and searches from the UI say when to try again; failed theme downloads and searches now show YouTube's actual error instead of a generic or truncated message.

## [1.1.0] - 2026-10-22

### Added

First stable public release of Overture

- Choose artwork and theme songs for Plex, Jellyfin and Emby
  libraries from your media server, TMDB, OvertureDB, ThemerrDB and YouTube,
  saved as files beside your media.
- Scheduled syncs and artwork and theme runs, along with renaming and audit functionality.
- Multi-platform container images on GHCR and Docker Hub, tagged with the full,
  minor and major version, and a native Linux archive with a systemd service.
