# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Press `/` or Ctrl+K (Cmd+K on macOS) to jump to the sidebar search.

### Changed

- Improved readability across the interface with clearer text contrast and inline option hints.
- Every popup is centred and exactly as tall as its content, up to the window's height. Operations job logs and result lists take only the room their lines need and share what the window has, so the body scrolls only when even three lines each no longer fit.
- Popup sections are separated by thin lines instead of boxes, and art and themes keep the same colour in every popup, badge and progress bar.
- Downloads show which step they are on, such as "Transcoding 3/4", instead of a percentage, and their progress bar now advances by real steps.
- Each operation's schedules and the form for a new one are now one Schedules section, with the form first and the saved schedules below.
- Checkboxes have a new look and no longer leave a focus ring after a click, option lists such as libraries flow into columns instead of one per line, and many hints were removed or folded into the rows they explain.
- Light mode is easier to read: status colours meet WCAG AA contrast and text fields have visible borders. Both modes now share one default accent colour, which light mode darkens automatically, so a custom accent also stays legible there.
- Popup footers are slimmer, and buttons only grow to touch size on touch screens, not in narrow windows.
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
