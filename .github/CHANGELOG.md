# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Collections:** a collection can span several libraries, of movies, shows or both, with its own criteria for each. Jellyfin and Emby hold one collection for them all; Plex holds one in each library, which Overture keeps alike. The libraries of a saved collection can change, and a set makes one collection per value across its libraries.
- **Collections:** the library sidebar has a **Collections** tab listing movie and show collections together, with a **Holds** filter.
- **Collections:** movie and show collections share groups. On upgrade, same-named groups merge; where their settings differ, the show group is kept as `<name> (Shows)`.
- **Collections:** a set's per-library collections of one value merge into one on upgrade; the next sync folds extra Jellyfin and Emby collections into one, and a Plex copy added later receives the collection's art and theme.
- **Collections:** the sort menu of **Groups** sorts the groups themselves, by name, collections, items, date added or last synced.
- **Collections:** MDBList conditions refuse franchise and official-list URLs (`mdblist.com/franchises/...`, `mdblist.com/lists/official/...`) and say what to use instead, since MDBList's API serves neither.
- **Collections:** `scripts/verify.py` replaces `verify_collections.py`: besides Overture's own checks it reads each media server directly, read only, and compares libraries, items, collections, values and counts with the server's own, loads every collection image, and reports every Plex filter, field, sort and operator and every Jellyfin and Emby filter Overture cannot use.
- **OvertureDB:** a library title, collection or catalog draft can be contributed on its own through **Contribute issue**, which opens its OvertureDB form on GitHub filled in.
- **Collections:** sets can be split by production company, TMDB keyword and show status, and on Plex by video codec, audio codec and audio channels.
- **Collections:** Plex smart collections and smart sets can test any field Overture can evaluate, such as original language or TMDB facts, through labels Overture keeps on the matching items and refreshes on each sync.
- **Interface:** smart collections carry a sparkle in the sidebar.
- **Collections:** TMDB list and title conditions take TMDB links as well as IDs.

### Changed

- **Collections:** collection links moved from `/movies/collections` and `/shows/collections` to `/collections`; old links redirect.
- **API:** collection and group endpoints no longer take `media_type`. A rule holds `libraries`, each with its `library_id` and `criteria`; a collection reports `media_types` and `library_ids`; and `/collections/preview` answers per library.
- **Collections:** only Setup and Content open by default on a collection's page and no section does in a group, and neither remembers what was open.
- **Collections:** sort options that say nothing about a collection are gone: art size and shape, theme length, Group inside a group, and Home order outside Plex.
- **Operations:** Clear Results sits on the right of the footer.
- **Filters:** Collection operations no longer offer Sync; sync a collection from its page or a group from **Collection groups**.

- **Collections:** a new collection starts from **Create**, then, for a set, **Split by**, which names the group and its title template and fills in the names and order that suit its values, adding no minimum or **Most common only** of its own; **Start from** and **Save as preset** are gone, and the migration drops saved presets.
- **Collections:** Overture never deletes a collection it manages unless you do: below its minimum, out of season, or left out by its set, a collection only leaves the media server, and **Below minimum** offers **Remove from server** or **Keep on server**. A managed collection deleted on the server stays in Overture and its next sync recreates it.
- **Sync:** a full sync with Collections selected also syncs every managed collection, sending members, titles, sort titles, summaries and display settings, and no longer overwrites what Overture manages with the server's copy; with libraries chosen, groups sync only their collections in those libraries.
- **Collections:** without a summary template a collection takes its list's description, so TMDB franchises get TMDB's overview.
- **Collections:** Collection filtering is offered only for smart collections, the only ones Plex filters per user.
- **Interface:** the sidebar's Groups view lists every group, empty ones too; Ungrouped and Unmanaged appear only while they hold a collection.
- **Interface:** collection operations and their target groups are listed alphabetically, and groups are renamed and deleted only in Collection groups.
- **Database:** movies store every director; the migration keeps each stored director as the first and reads the rest on the next sync.
- **Interface:** TMDB charts, person roles, Radarr and Sonarr tags, root folders and quality profiles, the bulk sort list and the sidebar's art source, theme source and metadata issue filters are listed alphabetically.
- **Collections:** the editor suggests Smart or Regular as the criteria change, without a preview, and suggests Smart whenever Plex can filter every condition natively.
- **Interface:** a theme's length, title and source are no longer shown under the detail header; only a running download is.
- **Settings:** new installs start with the Art & Themes workflow, auto-advance through slots and items, auto-unmonitor once art and theme are complete, the theme search `{title} {year} main theme music`, theme durations of 20 to 600 seconds, collections of at least 2 members that leave the server below it and when inactive, no scheduled collection sync, and Radarr and Sonarr searches off when titles are added. Saved settings are kept.
- **Collections:** regular collections now evaluate and order criteria as Plex does: an unknown number or release date matches no condition (`is not` included), a title never played counts as last played before any date, durations compare whole minutes on both sides, titles sort by the server's sort title with numbers by value, and items without a value sort lowest.
- **Collections:** a show is in progress when one of its episodes is partly played, as Plex's filter tests.
- **Interface:** save, run and create buttons sit at the lower right of their row or popup, with resets at the left; Copy comes before Duplicate; the filters and Collection groups remember their open sections, while each collection opens with only Setup and Content expanded; Rename or delete is the last section of a group.
- **Interface:** the criteria field list calls its list and tag sources External.

### Fixed

- **Security:** the container image is built on a Python base with `apt` 3.0.4, fixing CVE-2026-109518.
- **Library:** TVDB links open by ID, so titles whose TVDB slug differs from their name no longer lead to a missing page.

- **Collections:** changing **Split by** to a dimension Overture counts no longer leaves a set evaluated by Plex when Plex had only been required by the previous dimension.
- **Collections:** collection art runs compare each collection's current server image with TMDB's, not only images Overture uploaded, and decide while planning the slots no source can serve, reporting them together.
- **Interface:** an edit to a group's settings, or a TMDB ID list being typed, is no longer undone when the group is fetched again or the field loses focus.
- **Sync:** Plex collection sync asks Plex for less: no lookup of a collection's library, only the members out of a custom order move, and smart collections update only the labels that change.

- **Collections:** a poster uploaded to a Plex collection shows in Overture instead of the placeholder, and uploading a background no longer fails with a 502.
- **Collections:** deleting an empty group asks only to confirm, instead of waiting for a choice about collections it does not have.
- **Collections:** a set of smart collections is refused on Jellyfin and Emby, which have none.
- **Media servers:** an unsuccessful media server response names its HTTP status.
- **Sync:** Plex titles keep every genre, country, cast member, producer and label; the section listing Overture read shortened or left them out, so criteria on them missed titles.
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
