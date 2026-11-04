# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Collections:** MDBList conditions take franchise URLs (`mdblist.com/franchises/...`) besides lists; official-list URLs are refused, since MDBList's API does not serve them.
- **Collections:** `verify_collections.py --plex` reports every filter, field and sort Plex offers that Overture's criteria cannot use.

### Changed

- **Settings:** new installs start with the Art & Themes workflow, auto-advance through slots and items, auto-unmonitor once art and theme are complete, the theme search `{title} {year} main theme music`, theme durations of 20 to 600 seconds, collections of at least 2 members that are deleted below it and removed from the server when inactive, no scheduled collection sync, and Radarr and Sonarr searches off when titles are added. Saved settings are kept.
- **Collections:** regular collections now evaluate and order criteria as Plex does: an unknown number or release date matches no condition (`is not` included), a title never played counts as last played before any date, durations compare whole minutes on both sides, titles sort by the server's sort title with numbers by value, and items without a value sort lowest.
- **Collections:** a show is in progress when one of its episodes is partly played, as Plex's filter tests.
- **Interface:** save, run and create buttons sit at the lower right of their row or popup, with resets at the left; Copy comes before Duplicate; each view remembers its own open sections, and only Setup and Content start open; Rename or delete is the last section of a group.
- **Interface:** the criteria field list calls its list and tag sources External.

### Fixed

- **Sync:** Plex titles keep every genre, country, cast member, producer and label; the section listing Overture read shortened or left them out, so criteria on them missed titles.
- **Collections:** the A to Z set preset previews and saves instead of failing.
- **Collections:** Plex show smart collections made in Plex Web (`show.title`, `show.actor`, `show.unwatchedLeaves` and the like) can be adopted, and show resolutions are offered as the values sync stores.
- **Collections:** Plex smart collections no longer offer operators Plex ignores, such as Resolution is not.
- **Interface:** a long summary no longer stretches the poster in the detail header.
- **Interface:** posters link to the media server only while the server holds the item or collection.
- **Media server:** an error answer to one request no longer marks the server unreachable.

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
