# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Collections:** **OvertureDB posters**, a collection setting (global, per group or per collection), chooses between a TMDB collection's own OvertureDB poster and a consistent one in a layout every collection shares; automatic art, exports and **Contribute issue** follow each collection's choice, and the catalog view the global one.
- **Collections:** a **Made as** filter shows collections made one at a time or by a set, one per value.
- **Sync:** a full sync can sync chosen collections, picked under **Specific collections** below the groups, besides or instead of whole groups; schedules keep the choice.
- **Collections:** an **In a collection** condition; **In a collection is false** makes a catch-all of every title no other collection holds, and a collection never counts itself.
- **Artwork:** collection art drawn from the title, in a dark, light or accent style, offered as **Generated** candidates and filterable as the **Generated** art source: posters show the title, under the group or alone, and backgrounds never show text; drawn art is drawn again when the title or group changes.
- **Collections:** **Automatic art** (global, group and collection) is one choice: Off; OvertureDB, TMDB, or OvertureDB then TMDB, each optionally else draw; or Draw, which draws a titled poster and a background without text in the **Drawn colours**; **Background: Not needed** makes a poster complete a collection's art. The media server's own art is never taken. The upgrade turns the earlier switches into OvertureDB, then TMDB.
- **Artwork and themes:** removing art or a theme, from its tab or for filtered titles and collections, can forget the selection, delete the local file and delete the media server's copy, in any combination; the dialog offers only what applies and says why the rest cannot. Only JPEG and PNG images and MP3 themes are ever deleted.
- **Collections:** an inactive collection's art and theme can be chosen; the sync that puts it back on the server sends them.
- **Collections:** a Plex group can have a **Separator**, an empty collection titled after the group with a drawn poster showing its name alone, sorted before the group's collections by the group's sort title template, or by `{group} {title}` when none is set.
- **Notifications:** `NOTIFY_URL` hears when runs end, in the format of a Discord, Slack, Telegram, Gotify or ntfy webhook it names, or as the JSON Apprise's API takes for any other service. **Notifications** in the menu chooses, per kind of run, whether failed and stopped runs are announced, which completed ones are (never, always, with changes or with errors) and whether only scheduled runs count, and sends a test notification.
- **API:** `GET /api/media-server/links` returns where the server's web app opens items and collections; `GET /api/collections/{id}/art/{art_type}/generated/{style}` returns art drawn from the collection's title; the database record lists a title's values, such as genres and people.
- **Collections:** a collection can span several libraries, of movies, shows or both, with its own criteria for each. Jellyfin and Emby hold one collection for them all; Plex holds one in each library, which Overture keeps alike. The libraries of a saved collection can change, and a set makes one collection per value across its libraries.
- **Collections:** the icon beside Movies and Shows in the library sidebar lists movie and show collections together, with a **Holds** filter: its first click opens the last view used, Groups or Collections, and later clicks switch between them.
- **Collections:** movie and show collections share groups. On upgrade, same-named groups merge; where their settings differ, the show group is kept as `<name> (Shows)`.
- **Collections:** a set's per-library collections of one value merge into one on upgrade; the next sync folds extra Jellyfin and Emby collections into one, and a Plex copy added later receives the collection's art and theme.
- **Collections:** the sort menu of **Groups** sorts the groups themselves, by name, collections, items, date added or last synced.
- **Collections:** MDBList conditions refuse franchise and official-list URLs (`mdblist.com/franchises/...`, `mdblist.com/lists/official/...`) and say what to use instead, since MDBList's API serves neither.
- **Collections:** `scripts/verify.py` replaces `verify_collections.py`: besides Overture's own checks it reads each media server directly, read only, and compares libraries, items, collections, values and counts with the server's own, loads every collection image, and reports every Plex filter, field, sort and operator and every Jellyfin and Emby filter Overture cannot use. With `--write` it also makes, changes and deletes temporary "zz Overture verify" collections with Overture's own media server clients, to show how each server takes them.
- **OvertureDB:** a library title, collection or catalog draft can be contributed on its own through **Contribute issue**, which opens its OvertureDB form on GitHub filled in.
- **Collections:** sets can be split by production company, TMDB keyword and show status, and on Plex by video codec, audio codec and audio channels.
- **Collections:** Plex smart collections and smart sets can test any field Overture can evaluate, such as original language or TMDB facts, through labels Overture keeps on the matching items and refreshes on each sync.
- **Interface:** smart collections carry a sparkle in the sidebar.
- **Collections:** TMDB list and title conditions take TMDB links as well as IDs.
- **Artwork:** **Upload image** saves a JPEG or PNG from your device into any item, season or collection art slot, and pasting an image on the art tab does the same. Uploads are kept in the image cache, count as saved choices that Assets restores, and filter as the **Upload** art source.
- **Collections:** collection posters and backgrounds Overture uploaded show from its image cache in the sidebar and on the collection's page, and **Audit** can compare them with the server's and upload them again.
- **Collections:** the item filters can show only the titles of one collection.
- **Collections:** TMDB title and MDBList conditions, and a collection's TMDB collection ID, can be searched by name.
- **Collections:** adopting a collection names members without a TMDB ID by their TVDB or IMDb ID before their title, through new **TVDB ID** and **IMDb ID** conditions.
- **Collections:** a **TMDB ID** condition, and **TMDB title list** conditions take IDs and links without `TMDB_API_KEY`.
- **Collections:** creating a set refuses a group that already is one and warns when another set splits the same libraries alike or the group already holds collections; the set preview names values whose title another collection already has.
- **Collections:** a copied condition or group pastes into any criteria that can test it, in another library, collection or set.
- **Statistics:** the storage footprint includes the image cache, with its originals, uploads and thumbnails, and artwork coverage and sizes include collection posters, backgrounds and themes.
- **Interface:** the database record lists every stored column of the record and of the rows that belong to it, such as seasons, art slots and collection libraries, apart from what Overture derives from them.
- **Interface:** every section of the filters popup collapses, and stays as you left it.
- **OvertureDB:** **Browse OvertureDB in the sidebar** explains how browsing helps find gaps and mismatches and contribute them.
- **API:** `GET /api/library/items/{id}/record` and `GET /api/collections/{id}/record` return a record's stored rows and derived values, and the `collection.monitored` event reports a monitoring change on its own.

### Changed

- **Media servers:** changing the media server keeps your collections and groups, with their art, themes and settings. On the next start Overture forgets the collections the earlier server held that it does not manage, lets go of the managed ones' server copies and resets what the new server cannot keep, such as Plex's visibility, smart collections and custom orders on Jellyfin and Emby; the next sync makes them on the new server, or takes over its collection of the same title, and sends their art and themes. Sync schedules sync every library and polling starts over; server audit results are cleared. The upgrade keeps the collections of the server synced last and deletes those kept for earlier servers.
- **API:** collections no longer carry `server_type`; they belong to whichever media server Overture is set up with.
- **Libraries:** when the server stops listing a library and a sync finds its titles in another, collections, sets and schedules move to that library, as after a change of media server.
- **Collections:** a collection without a copy on the server takes over the server's unmanaged collection of its title in that library instead of making a second one.
- **OvertureDB:** OvertureDB is on by default and syncs its catalog on the first start. **Enable OvertureDB**, **Trust OvertureDB's No theme flag** and **Browse OvertureDB in the sidebar** moved to **Settings -> OvertureDB**; the OvertureDB menu entry shows only while it is on.
- **OvertureDB:** Overture reads version 3 of the catalog, which adds consistent collection posters; earlier versions of Overture cannot sync it.
- **OvertureDB:** exports and **Contribute issue** leave out a theme shorter than 20 seconds or longer than 10 minutes, which OvertureDB refuses, and say why.
- **Collections:** only **Sync** under Operations changes collections on the media server. Saving a collection, group or set, editing its members and bulk display edits stay in Overture and never contact the server; **Save and Sync** saves, then opens Sync with only that collection, set or group chosen and every library unticked. `POST /api/collections/{id}/sync`, `POST /api/collections/group-policy/sync` and the `to_server` query of collection writes are removed; a full sync's `collection_ids` takes their place.
- **Operations:** Collections is its own section beside Libraries or Folders in Assets, Sync and Server audit, with its own **Select all**; in Sync and Assets every collection includes every group, so unticking one group keeps the rest.
- **Collections:** saving a collection or group only writes in Overture and returns at once; **Save and Sync** sends it to the media server. A new collection saved without syncing reads its lists on its first sync.
- **Downloads:** art and themes download while a full sync runs, so a choice made then shows at once; each download writes into the folder its title has when it is saved.
- **Collections:** sort titles leave out a leading "The", "A" or "An" of the title and group, as Plex does when it sorts titles itself.
- **Collections:** a smart collection never takes a group's or the default **Custom** order, which Plex cannot apply to it, but the next order the settings give.
- **Artwork:** an Assets run compares OvertureDB's artwork with the local file as local image matching does, so with a looser matching threshold the same picture saved differently is taken instead of skipped.
- **Radarr and Sonarr:** every title Request missing adds is tagged `overture`; a member tag cannot be `overture`.
- **Settings:** **Request missing** sits with the Radarr and Sonarr root folder, quality profile and search, in its own section.
- **Settings:** **Auto-search themes on load**, on by default, searches YouTube as soon as a title's themes open.
- **Interface:** a title's collection link is an icon badge like its other links; removals say exactly what they forget or delete, and every removal, art choice, OvertureDB draft change and run ending shows a notice.
- **Interface:** status filters are evenly spaced.
- **Interface:** runs are named as their Operations tabs are, such as "Assets art run" and "Renamer scan", in notices, notifications and messages.

- **Collections:** collection syncs run on **Sync** schedules under Operations, which can sync chosen groups; the per-group and global collection sync schedules are gone, and the upgrade turns each enabled one into a Sync schedule of its groups.
- **Collections:** a group's **Save** also sends its display settings to its collections on the server; **Save and Apply** is gone.
- **Collections:** separators are no longer listed among the collections; their group keeps them.
- **Collections:** a collection's members are grouped by library, movie libraries first, each kind by title.
- **Interface:** Settings sections collapse, and stay as you left them.
- **Themes:** YouTube searches show up to 20 results within the duration limits, rather than at most 10 before the limits filtered them.
- **API:** the art and theme removal routes take `forget`, `delete_file` and `delete_from_server`; `POST /api/art/removal-options` says what each would change; bulk `clear_artwork` and `clear_themes` are `remove_artwork` and `remove_themes` with a `removal`.
- **Database:** the library sync records the server's libraries, so their names show while the server cannot be reached; titles hold their genres, people, labels and TMDB facts as shared values; movies and shows keep only their own fields and only shows have seasons; collections reference their group and every group is kept until deleted; JSON settings are checked to be valid JSON. The upgrade converts existing data.
- **Collections:** a group stays listed after its last collection leaves it, until it is deleted in **Collection groups**.
- **Interface:** links that open a title or collection in the media server follow the server's current address.
- **Backups:** **Back up now** says which older backups the retention removed, saving **Backups to keep** applies it to the existing backups at once, the backup list shows where backups are saved and dates each backup by the time in its name, the same time retention uses.
- **Interface:** the sidebar's Movies, Shows and Collections tabs display their name above their icon and count, at any width.
- **Interface:** the filters popup lines every filter's name up in one column with its choices filling the rest of the row, puts filters offering the same choices together, the most used first, and on a phone moves a filter's choices under its name rather than cutting them short.
- **Interface:** every collapsible section, filter section, database record row and saved schedule opens and closes from anywhere across its header; a saved schedule's summary line replaces its eye button.
- **Interface:** collection settings fill as many columns as the page has room for, a collection condition on a phone gives its field a row of its own, and labels and buttons use sentence case throughout.
- **Interface:** the database record leaves out link rows, such as which collections hold an item, and the artwork fields that only repeat the art slot rows shown above them.
- **API:** `POST /api/backups` also returns `removed`, the backups the retention removed; `GET /api/backups` also returns `directory`; collection responses carry `poster_phash` and `background_phash` like item responses.
- **Packaging:** Overture installs only the parts of uvicorn's `standard` extra it uses, so PyYAML and watchfiles are no longer installed.
- **Collections:** the sidebar's Groups, Collections and Items mode switches are gone; the collections icon beside Movies and Shows replaces them and the separate Collections tab.
- **Collections:** the libraries of a new collection list movie libraries, then show libraries, and a collection's members are listed by library, reordered only within one.
- **Collections:** deleting a collection leaves the sidebar where it was, such as inside its group.
- **OvertureDB:** the catalog is downloaded from its gzip file only.

- **Collections:** collection links moved from `/movies/collections` and `/shows/collections` to `/collections`.
- **API:** collection and group endpoints no longer take `media_type`. A rule holds `libraries`, each with its `library_id` and `criteria`; a collection reports `media_types` and `library_ids`; and `/collections/preview` answers per library.
- **Collections:** only Setup and Content open by default on a collection's page and no section does in a group, and neither remembers what was open.
- **Collections:** sort options that say nothing about a collection are gone: art size and shape, theme length, Group inside a group, and Home order outside Plex.
- **Operations:** **Clear results** sits on the right of the footer.
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
- **Interface:** the criteria field list groups its list and tag sources under **Lists & tags**.
- **Collections:** deleting a group offers **Orphan them** for its collections, as orphaning one collection does, instead of removing them from Overture; collections a set made can be neither deleted nor orphaned while the set exists.
- **Collections:** Radarr and Sonarr tags are written as Radarr and Sonarr accept them, in lowercase letters, digits and dashes, and collections whose tags come out the same share the tag instead of taking it from each other's members.
- **Library:** libraries are listed movies first, then by name, everywhere; a collection's criteria follow that order whatever order its libraries were chosen in.
- **Library:** sorting by Title follows the media server's sort title, so leading articles such as "The" and "A" are left out as the server leaves them out.
- **Interface:** Movies, Shows and the collections icon share the sidebar's width, each with its count and with its name where there is room; the collections icon names what it lists, groups or collections, and shows the view a click switches to.
- **Interface:** the filters popup lists **Holds** under Status, and **Collection** between Theme music and Metadata issues.
- **Interface:** the detail tabs and actions wrap as separate bars, so no row is wider than its buttons; shows use the TV icon and seasons an icon of their own.
- **Interface:** the sidebar's search box takes the room the filter and reset buttons give up.
- **Collections:** toggling a collection's monitoring updates it in place, and opening a collection no longer reloads its members, which the library already lists.
- **API:** a collection reports `member_ids` instead of `members`, and `server_poster_version` and `server_background_version` instead of `thumb_url` and `art_url`; items report `sort_title`, seasons `poster_source`; a group deleted with `collections: "orphan"` orphans its collections, replacing `"overture"`; statistics add `image_cache` and `art.collections`.

### Fixed

- **Assets:** a saved choice whose file was replaced after Overture wrote it, such as a `poster.jpg` from Radarr or Sonarr metadata, or deleted since the last sync, is downloaded again, as one whose file is missing already was. A run checks the files of saved choices before it plans, reading only files whose size or modification time changed.
- **Artwork:** drawn collection art renders every character of a title, such as dashes, curly quotes, accented letters, Greek, Cyrillic, Chinese, Japanese, Korean, Arabic, Hebrew, Devanagari, Thai, symbols and emoji, with bundled Noto fonts.
- **Interface:** reloading the page no longer announces runs that had already finished.
- **Collections:** a library sync kept turning separators into regular collections, which then showed in the sidebar, failed to open and kept their group's next separator from being made ("A collection with this title already exists in this library"); the upgrade makes such collections separators again.
- **Interface:** a burst of live updates no longer slows a large library.

- **Artwork:** Assets runs that adopt perfect matches only find a byte-identical candidate whose preview differs slightly from the original, for items and collections.
- **Interface:** auto-advance goes through the sidebar in the order it showed when you reached a title, even when a selection moves the title, such as when sorting by poster shape.
- **Interface:** the Status filters are no longer parted by rules.
- **Performance:** collection syncs, previews and library loading read only the values they need, so a collection syncs in moments instead of minutes and large libraries no longer run the app out of memory. Upgrading rebuilds the stored genre and people links once.
- **Artwork:** automatic art no longer replaces an uploaded collection image after a sync, and a new server copy of a collection receives its uploaded image.
- **Artwork:** collections without a TMDB collection ID offer the art of the person their criteria list.
- **Collections:** TMDB facts no longer give movies a show status, last air date or networks.
- **Interface:** the reset button beside active filters no longer covers the outline around them, and a section header no longer covers its accent rule while hovered.
- **Collections:** **Delete group** in Collection groups asks what happens to the group's collections instead of doing nothing.
- **Artwork:** an uploaded poster, background or season poster can be cleared like a linked one.
- **Artwork:** a season's local poster shows even when its show has no media folder.

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

### Security

- **Container:** the image applies Debian's security updates when it is built, so fixes such as zlib's and apt's reach it before the official Python image is rebuilt with them.
- **Container:** the image no longer contains `apt`, which it never uses at runtime, so its vulnerabilities do not apply to it.

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
