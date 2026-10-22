# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Press `/` or Ctrl+K (Cmd+K on macOS) to jump to the sidebar search.

### Changed

- Improved readability across the interface with clearer text contrast and inline option hints.
- Popups are centred, and Operations and Statistics keep one size while you switch tabs.
- Popup sections are separated by thin lines instead of boxes, and art and themes keep the same colour in every popup, badge and progress bar.
- Downloads show which step they are on, such as "Transcoding 3/4", instead of a percentage, and their progress bar now advances by real steps.
- Each operation's schedules and the form for a new one are now one Schedules section.
- Job logs show at most eight lines before scrolling.
- Clarified bulk asset counts so completed file transfers always count as downloaded, reserving adopted for existing local files kept without downloading.

### Fixed

- Prevented empty log placeholders when stopping an operation and improved live elapsed timer accuracy.
- A finished operation's log now lists exactly its saved lines, and its time taken no longer drops back when it ends.

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
