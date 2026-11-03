# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-03

The first public release of Overture: artwork, collections and theme songs for
Plex, Jellyfin and Emby, kept as ordinary files beside your media.

### Added

- **Artwork:** compare posters, backgrounds and season posters from your media
  server, TMDB and OvertureDB, ranked by resolution and by visual similarity to
  what you already have. Filter by aspect ratio and language, or paste an image
  URL.
- **Themes:** choose an OvertureDB or ThemerrDB theme, search YouTube with a
  duration limit or paste a link, preview it and save it as MP3 with optional
  loudness normalization.
- **Collections:** create and manage Plex, Jellyfin and Emby collections from
  nested criteria over library metadata, TMDB facts, franchises, people and
  lists, MDBList lists and Radarr or Sonarr tags. Collection sets build one
  collection per decade, genre, studio, network, language or other value, and
  presets cover charts, holidays, universes and more. On Plex, criteria can
  also become smart collections.
- Collections sync on a schedule, can be active only on chosen dates, request
  missing titles from Radarr or Sonarr, label or tag their members, and adopt
  collections made outside Overture.
- **Operations:** Sync imports your libraries and existing local files; Assets
  fills in artwork and themes from your chosen sources; Renamer standardizes
  asset filenames; Audit checks that the media server shows and plays the files
  on disk. Each runs now or on a schedule, for chosen libraries or collection
  groups.
- **OvertureDB:** browse the community catalog, save artwork and theme drafts
  for any title, including ones outside your library, and export them as a
  contribution.
- Review tools: coverage filters, auto-advance after saving, skipping completed
  items, coverage and storage statistics, and TMDB search for choosing artwork
  and themes before a title is in your library.
- Sign-in with a password, OpenID Connect or both, and read-only API keys for
  dashboards and scripts over the documented REST API.
- `MEDIA_SERVER=none` runs Overture without a media server, for curating
  OvertureDB.
- Scheduled and manual database backups, plus one before every database
  upgrade.
- An installable progressive web app for desktop and mobile.
- Signed multi-platform container images (`amd64`, `arm64`) on GHCR and Docker
  Hub, tagged with the full, minor and major version, and a native x86_64 Linux
  archive with a systemd service.
