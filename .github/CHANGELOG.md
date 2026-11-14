# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-11-14

### Added

- **Collections:** a collection can span several movie and show libraries, with its own criteria for each. Jellyfin and Emby hold one collection for them all; Plex holds one per library, kept alike. Movie and show collections share groups, listed together under the collections icon beside Movies and Shows.
- **Collections:** new conditions: **In a collection** (false makes a catch-all of every title no other collection holds), **TMDB ID**, **TVDB ID** and **IMDb ID**. TMDB conditions take links as well as IDs, TMDB and MDBList conditions can be searched by name, and a copied condition or group pastes into any criteria that can test it.
- **Collections:** sets can be split by production company, TMDB keyword and show status, and on Plex by video codec, audio codec and audio channels. Creating a set warns when another set already splits the same libraries alike.
- **Collections:** Plex smart collections can test any field Overture evaluates, such as original language or TMDB facts, through labels Overture keeps on the matching items.
- **Collections:** a Plex group can have a **Separator**, an empty collection titled after the group that sorts before its collections.
- **Collections:** **Automatic art** takes OvertureDB's art, TMDB's, or OvertureDB's then TMDB's, each optionally falling back to generated art, or always generates. **OvertureDB posters** chooses between each collection's own poster and a consistent layout every collection shares.
- **Artwork:** collection posters and backgrounds generated from the title in a dark, light or accent style, offered as **Generated** candidates and generated again when the title or group changes.
- **Artwork:** **Upload image**, or pasting an image, saves your own JPEG or PNG into any item, season or collection art slot; uploads count as saved choices Assets restores.
- **Artwork and themes:** removing art or a theme, for one title or for filtered titles and collections, can forget the choice, delete the local file and delete the media server's copy, in any combination.
- **Collections:** art Overture uploaded to collections shows from its image cache, and **Server audit** can compare it with the server's and upload it again. An inactive collection's art and theme can be chosen before the sync that puts it back on the server.
- **Sync:** a full sync can sync chosen collections besides or instead of whole groups, and schedules keep the choice.
- **Notifications:** `NOTIFY_URL` announces finished runs to Discord, Slack, Telegram, Gotify, ntfy or any service Apprise's API supports. **Notifications** in the menu chooses which runs of each kind are announced and sends a test.
- **OvertureDB:** **Contribute issue** opens the OvertureDB form for one library title, collection or catalog draft on GitHub, filled in.
- **Interface:** the database record of a title or collection lists every stored column of it and of its rows; the item filters can show one collection's titles; collections can be filtered by **Made as** and groups sorted by name, size, date added or last sync.
- **API:** `GET /api/library/items/{id}/record` and `GET /api/collections/{id}/record` return a record's stored rows, `GET /api/media-server/links` where the server's web app opens titles, and `GET /api/collections/{id}/art/{art_type}/generated/{style}` art generated from a collection's title.

### Changed

- **Collections:** only **Sync** under Operations changes collections on the media server. Saving a collection, group or set stays in Overture and returns at once, and **Save and Sync** saves, then opens Sync with only that collection chosen. Collection syncs run on **Sync** schedules; the upgrade turns each enabled per-group or global collection schedule into one.
- **Collections:** Overture never deletes a collection it manages unless you do. Below its minimum, out of season or left out by its set, a collection only leaves the media server; one deleted on the server is made again by its next sync, and one without a server copy takes over the server's unmanaged collection of its title.
- **Media servers:** changing the media server, or a library moving on it, keeps your collections and groups with their art, themes and settings; the next sync makes them on the new server and resets what it cannot keep, such as Plex's visibility on Jellyfin and Emby.
- **Collections:** regular collections evaluate and sort criteria as Plex does, a show is in progress when one of its episodes is partly played, and sort titles leave out a leading "The", "A" or "An", as Plex does.
- **Collections:** a new collection starts from **Create** and, for a set, **Split by**, which fills in the names and order that suit its values; **Start from** and presets are gone, and the upgrade drops saved presets.
- **Collections:** without a summary template a collection takes its list's description; a smart collection never takes a **Custom** order, which Plex cannot apply to it; **Collection filtering** is offered only for smart collections; Radarr and Sonarr tags are written in the lowercase form they accept.
- **OvertureDB:** OvertureDB is on by default and syncs its catalog on the first start; its settings are under **Settings -> OvertureDB**. Overture reads version 3 of the catalog, which earlier versions cannot sync, and leaves out of exports themes OvertureDB refuses, shorter than 20 seconds or longer than 10 minutes.
- **Operations:** Collections is its own section in Assets, Sync and Server audit; art and themes download while a full sync runs; and runs are named after their Operations tab, such as "Assets art run", in notices, notifications and messages.
- **Artwork:** an Assets run compares OvertureDB's artwork with the local file as local image matching does, so with a looser threshold the same picture saved differently is taken instead of skipped.
- **Radarr and Sonarr:** every title **Request missing** adds is tagged `overture`, and its settings sit with the root folder, quality profile and search in their own section.
- **Settings:** new installs start with the Art & Themes workflow, auto-advance, auto-unmonitor once art and theme are complete, **Auto-search themes on load**, theme lengths of 20 to 600 seconds and collections of at least 2 members. Saved settings are kept.
- **Interface:** collections open at `/collections`; the sidebar, filters popup and settings fill their space at any width and on a phone; sections collapse from anywhere on their header and remember their state; lists are alphabetical; labels use sentence case.
- **Backups:** **Back up now** and saving **Backups to keep** apply the retention at once and say which backups it removed, and the backup list shows where backups are saved.
- **Database:** the upgrade converts stored data: titles keep their genres, people, labels and TMDB facts as shared values and movies every director, the server's libraries are recorded so their names show while it is offline, and OvertureDB's tables, job and schedule are named `catalog`.
- **API:** item art and theme routes move under `/api/library/items/{id}/art` and `/api/library/items/{id}/theme`, as collections' are; `/api/public-dataset` is `/api/catalog`, with `catalog.*` events. Collections drop `server_type` and `media_type`, a rule holds `libraries`, and a full sync's `collection_ids` replaces the collection and group sync routes, `GET /api/collections/{id}/sources` and the `to_server` query. Removals take `forget`, `delete_file` and `delete_from_server`.

### Fixed

- **Assets:** a saved choice whose file was replaced outside Overture, such as a `poster.jpg` from Radarr or Sonarr metadata, or deleted since the last sync, is downloaded again.
- **Performance:** collection syncs, previews and library loading read only the values they need, so a collection syncs in moments instead of minutes and large libraries no longer run out of memory, and a burst of live updates no longer slows the page.
- **Sync:** Plex titles keep every genre, country, cast member, producer and label, so criteria on them no longer miss titles; Plex collection syncs send only what changed.
- **Collections:** Plex show smart collections made in Plex Web can be adopted, and operators Plex ignores, such as **Resolution is not**, are no longer offered.
- **Collections:** a set of smart collections is refused on Jellyfin and Emby, which have none, and TMDB facts no longer give movies a show status, last air date or networks.
- **Collections:** a poster uploaded to a Plex collection shows in Overture, and uploading a background no longer fails with a 502.
- **Collections:** **Delete group** asks what happens to the group's collections instead of doing nothing, and edits to a group's settings are no longer undone when the group is fetched again.
- **Artwork:** Assets runs that adopt perfect matches find a byte-identical candidate whose preview differs slightly from the original, and a season's local poster shows when its show has no media folder.
- **Interface:** auto-advance follows the sidebar in the order it showed when you reached a title, even when saving moves the title.
- **Interface:** reloading the page no longer announces runs that had already finished.
- **Interface:** a long summary no longer stretches the poster, and posters link to the media server only while the server holds the item.
- **Library:** TVDB links open by ID, so titles whose TVDB slug differs from their name no longer lead to a missing page.
- **Media servers:** an error answer to one request no longer marks the server unreachable, and an unsuccessful response names its HTTP status.

### Security

- **Container:** the image applies Debian's security updates when it is built and leaves out `apt`, PyYAML and watchfiles, which Overture never uses.

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
