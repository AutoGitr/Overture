# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Improved readability across the interface with clearer text contrast, inline option hints, and top-anchored operations navigation.
- Clarified bulk asset counts so completed file transfers always count as downloaded, reserving adopted for existing local files kept without downloading.

### Fixed

- Prevented empty log placeholders when stopping an operation and improved live elapsed timer accuracy.

## [1.0.2] - 2026-10-21

### Added

- First stable public release of Overture: choose artwork and theme songs for Plex, Jellyfin and Emby
  libraries from your media server, TMDB, OvertureDB, ThemerrDB and YouTube,
  saved as files beside your media.
- Scheduled syncs and artwork and theme runs, Renamer and Audit.
- Multi-platform container images on GHCR and Docker Hub, tagged with the full,
  minor and major version, and a native Linux archive with a systemd service.
- Signed images and release files, with SBOMs and build provenance; the README
  explains how to verify them.
