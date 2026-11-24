# Changelog

## Unreleased

## 0.5.0 - 2026-11-24

### 🚨 Breaking Changes

- **API:** titles and collections carry their poster, background and theme under `assets`, and seasons their poster under `poster`: each with its selection, the content Overture holds, its status and where it is delivered, per server and folder. This replaces the flat `poster_*`, `background_*`, `theme_*` and `youtube_*` fields; existing choices and files are converted.
- **API:** setting or removing a collection theme returns the theme, and job events carry `log_targets` in place of their outcome counters.
- **API:** WebSocket events carry every field, `null` where it has no value, instead of leaving it out.
- **API:** an asset says whether it is `selected`, `GET /api/collections/{id}/theme` returns the theme as an asset, and Server audit fixes take a collection's theme by `collection_id`.
- **API:** a missing TMDB, Radarr, Sonarr or MDBList setting is answered with 409, as a missing media server is, instead of 503 or 400; season artwork asked of a title without a season, and clearing a kind of result that cannot be cleared, are answered with 422.
- **API:** IDs in paths and bodies are at most 9007199254740991, the largest a JSON client reads exactly.
- **API:** the `collection.theme.updated` event is removed; `collection.updated` reports a theme change.
- **Library:** Overture shows a title's or season's poster and background from the media server only once a full **Sync** has read which images the server shows; run one after upgrading.
- **Operations:** **Replace existing** is gone from Assets; each art and theme source list holds **Current selection** instead, which you drag to decide which sources may replace what a slot already holds: those above it replace, those below only fill empty slots. Saved schedules keep what they did: Current selection first where Replace existing was off, last where it was on. In the API, `overwrite_existing` is removed and `source_order` must include `current_selection`.

### 🔒 Security

- **API:** a request body larger than 1 MiB, or 20 MB for an image upload, is refused with 413 before it is read, so no request, signed in or not, can fill Overture's memory.

### 🚀 Features

- **API:** criteria fields say whether they match values ignoring case (`ignores_case`), and routes that need signing in document their 401 and 403 answers.
- **API:** `GET /api/collections/field-values` without a `library_id` lists the values of every library of the media type; titles and seasons name the version of the image their lead server shows (`server_poster_version`, `server_background_version`); job events count what a run has `read` while it plans; and a collection's `order_type` may be `null` to inherit.
- **API:** the schema documents every answer a route can give: 404 for a path that names nothing, 400 for a body that is not text, 409, 502 and 503 from a route that needs a media server, and a 422 that either lists each issue or says which rule was broken.
- **Collections:** **Resolution** criteria test shows on every server: a show holds each resolution its episodes come in, and a movie each of its versions', so **Resolution is 4K** matches as Plex's smart collections do. Shows gain theirs at the next full **Sync**.
- **Collections:** **Set sort** in Collection operations can return the filtered collections to **Inherit group or global default**, as **Set visibility** can.
- **Collections:** each library's criteria are headed by its server's badge and edged in its colour when several servers are configured.
- **Interface:** hovering a title's or collection's **Poster** or **Background** tab names the servers, or the folder, that do not yet show Overture's image.
- **Interface:** every list of libraries, art sources, theme sources and metadata issues offers **Select all** and **Deselect all** beside the list's name, partly ticked while only some are chosen.
- **Interface:** show filters take in season posters: **Season posters complete**, season posters in **Art resolution** and **Art source**, and season poster source and width in custom filters; **Art resolution** also offers **Any art**.
- **Operations:** Sync, Assets, Renamer and Server audit count what they have read while they plan, instead of showing **Planning...** until the total is known.

### 🌟 Enhancements

- **Artwork:** TMDB and OvertureDB each list every candidate they offer; media servers and collection members leave out images already in TMDB, OvertureDB or an earlier server.
- **Collections:** a sync checks the art and theme of every server copy, not just the first, and a collection is complete only once every copy shows them.
- **Collections:** a chosen theme stays chosen when a server plays another; the collection's next sync or an Assets run sends it again.
- **Interface:** dropdowns and menus share one floating list; typing a letter in a dropdown jumps to the choices it starts, and comboboxes narrow their values as you type.
- **Interface:** opening a collection from the sidebar shows its poster, background and art candidates at once while its full details load, and auto-advance preloads the next collection's images.
- **Interface:** saving a collection reads the library's titles again only when its members or TMDB collection change, so editing collections one after another stays quick instead of slowing every page.
- **Interface:** sidebar rows sit square against each other, and Renamer and Server audit results are spaced without a dark band cutting into the flagged rows' edge.
- **Interface:** a criteria value is typed, with the values the libraries hold listed as you type, however many there are, such as every actor; a collection is picked by its title from the same list.
- **Interface:** an image larger than 20 MB is refused before it uploads, saying so.
- **Interface:** a database record names an asset's copy by its server and file, such as `Background on Jellyfin`, and other rows by what they are, such as `Collection rule 19`.
- **Library:** auto-unmonitor counts a title's theme as complete when OvertureDB says it has none and Overture trusts that flag.
- **Operations:** a greyed-out button to start a run says why beside it and when hovered, such as nothing chosen yet or another operation running; **Rename** and **Refresh** say to select something first.
- **Operations:** Server audit compares and fixes collection images and themes exactly as a sync does, and records what it finds on a collection's copies, so the collection's status follows the audit.
- **Operations:** Assets runs decide titles and collections by the same rules: a saved choice is restored wherever a place lacks it, a source replaces a different image or theme only when ranked above **Current selection**, and planning lines count `assets` and `collection assets`.
- **Operations:** a sync logs each collection on each server, in each library: created, how many titles were added and removed, unchanged, deleted and why (such as a library leaving it), or left alone and why, so a run's totals count collections too. Reading the servers logs how many collections each lists, each new one and each one gone.
- **Renovate:** Overture and OvertureDB share one preset, so a dependency both use updates alike in each.
- **Statistics:** the images Overture uploads to collections count in the image cache, not in the artwork sizes.

### 🐛 Bug fixes

- **API:** a list's limit, such as 1,000 collections for a sync, counts every ID sent, so a list padded with repeats is refused as the schema says.
- **API:** a refused method's answer names the allowed ones in `Allow`.
- **API:** an ID too large for the database is refused with 422 instead of failing with 500.
- **Collections:** the bulk sort title template takes as many characters as the sort title format.
- **Collections:** Emby makes new collections again instead of failing with HTTP 500, and Jellyfin and Emby collections of more than about 200 titles sync instead of failing with HTTP 414.
- **Collections:** renaming a Plex collection renames the collection tag its titles carry too, clearing any orphaned tag left by an earlier deletion instead of failing with HTTP 409, so deleting it later no longer makes Plex create it again under its old title.
- **Collections:** uploading a collection background to Jellyfin or Emby replaces its primary backdrop instead of adding behind an existing one.
- **Collections:** a sync never locks the titles in a Jellyfin or Emby collection. Jellyfin and Emby keep a collection's name, and its summary when Overture sets one, through metadata refreshes, by locking those fields alone, so the server no longer renames it after the TMDB collection its name resembles (such as `Foreign` becoming `The Foreign Exchange Student Collection`).
- **Collections:** a collection a server made while failing the request is found by its title at the next sync instead of made again, and a server collection belongs to one Overture collection only, even when Jellyfin gives one made again the ID of one it deleted.
- **Collections:** one server refusing a collection no longer stops the others: its error is logged for that server, the others sync, and a collection made on another server before the refusal is kept instead of made again by every sync. A timed-out membership or details write to Jellyfin or Emby is retried.
- **Collections:** adopting a collection of more than 1,000 titles works; it failed with an internal server error.
- **Collections:** a sync keeps the art Overture uploaded while the server still shows it. Plex changes a collection's image link whenever the collection is edited, which a sync took for a replaced image, so collections lost their complete art and the next Assets run uploaded it again.
- **Interface:** removing one season's poster from a title's record works; it was always refused.
- **Interface:** an OvertureDB entry's art panel stays usable after a choice it cannot save, such as an upload.
- **Interface:** a collection offers to remove its theme only when it has one.
- **Library:** opening a show's season, stepping between seasons and going back to them no longer fails with "Something went wrong".
- **Library:** titles and seasons without a poster or background on the media server no longer ask the server for one, which filled the log with `provider-art -> 502` errors; one the server no longer has is answered with 404.
- **Library:** custom filter conditions offer the values of every library they test, so Collection and other lists are no longer empty when the first library holds none.
- **Operations:** an Assets run that may replace a saved choice downloads it again when its file is missing and no source finds anything, instead of leaving the slot empty.
- **Operations:** a run's log offers its media server filters when it is about more than one server; the log covered them.
- **Operations:** a run's log shows every line it has counted, even while the run is quiet, instead of empty placeholder rows when opened or reconnected mid-run.
- **Operations:** a running collection download shows its stage instead of `undefined/undefined`.
- **Operations:** Server audit no longer reports a collection out of its active dates as having no server copy; its sync took it off the servers on purpose.
- **Operations:** a run's log filters and its notifications count the targets each line names, so `94 collections` counts 94, as the run's totals do.
- **Operations:** log lines name a collection's asset as one, such as `Alien (collection poster)`, so it never reads as the title of the same name; theme lines name the theme.
- **Operations:** a title or collection that leaves the library during an Assets run is skipped, not an error, in every kind of run.
- **Settings:** the global sort title and summary formats take as many characters as a group's or collection's.
- **Sync:** a season the media server could not number, such as Jellyfin's "Season Unknown", is left out instead of being taken for Specials, so a show holding both syncs instead of failing with `UNIQUE constraint failed: seasons.media_item_id, seasons.season_num`.
- **Themes:** searching by YouTube link or video ID finds the video; the IDs were always refused. A link whose ID is longer than 11 characters names no video, instead of the first 11 characters of it.

### 📚 Documentation

- **Docs:** a Media server settings page lists the library, metadata, collection and theme music settings each server needs, and installation warns to apply them first.

## 0.4.0 - 2026-11-20

### 🚀 Features

- **API:** library items and collections list their `metadata_issues`; `/api/library/filters` lists, matches and saves custom filters.
- **Collections:** **Theme** (global, per group or per collection) can be **Not needed**: the theme counts as complete without one and none is chosen automatically.
- **Collections:** **Generated poster group** (global, per group or per collection) chooses whether generated posters show the collection's group above its title.
- **Collections:** the **Background** tab also offers the members' TMDB backgrounds, up to 10 each and 100 in all, fetched when the tab opens.
- **Collections:** Plex smart collections test **Subtitle codec**, **File size (GB)** and **Bitrate (Mbps)**, for shows also **Episode added** and **Episode last played**, and order shows by **Latest episode added** and **Unplayed episodes**.
- **Interface:** **Custom filter** in the movie and show filters saves named filters that test any metadata collection criteria test, TMDB and MDBList sources, and each title's library status (art, theme and OvertureDB status, sources, widths, metadata issues), in nested groups. **Add saved filter...** adds one to any criteria.
- **Interface:** the sidebar's TMDB search also finds the titles of a person, company, keyword or public list, by name, TMDB ID or link.
- **Media servers:** several Plex, Jellyfin and Emby servers at once, named in `MEDIA_SERVERS` and configured with `MEDIA_SERVER_<NAME>_*` variables. Titles are shared across servers, files are written under every name their servers read, collections span libraries on any server (a smart collection is smart in its Plex libraries and regular elsewhere), and `PATH_MAP` maps folders a server sees elsewhere.
- **Operations:** job logs and Server audit results can be filtered by media server; lines and filters name the server and are coloured by its kind.
- **Operations:** Assets can run **Specific collections**, beside groups and libraries, now or on a schedule.
- **OvertureDB:** the catalog view shows your library's file when the linked title or collection has the same art chosen, instead of fetching it.

### 🌟 Enhancements

- **API:** library IDs name their server (`1:2`); titles and collections list their `copies` per server instead of one `server_item_id`; settings list `media_servers`; capabilities, server links and server audit results are per server.
- **API:** collection field values carry a `label` and fields a `by_id` flag; job log lines carry `server_id`, `log_servers` is keyed by server number and `hide_server` takes numbers; download events name collection art and themes as one `collection` target.
- **Art:** perceptual hashes compare 256 points instead of 64, so another scan or grade of a poster no longer matches at distance 0. Existing fingerprints are taken again: a title's on its next refresh, a collection's from the image Overture keeps.
- **Backups:** a backup taken before a database upgrade is named after the version it was taken of (`overture_<time>_before_<version>.db`), and retrying the same upgrade replaces it rather than adding a copy.
- **Collections:** a **Collection** condition names the collection by ID, so it keeps matching after a rename, in Plex smart collections too. Saved criteria, saved filters and sets are converted; a title several collections shared becomes a group testing each.
- **Collections:** **Automatic art** and **OvertureDB posters** are ordered lists you tick and drag: Automatic art tries OvertureDB, TMDB and Generate in your order, and a collection takes the first OvertureDB poster style available. Saved choices keep what they did. **Contribute to OvertureDB as** starts from the first style ticked.
- **Collections:** generated posters are 2000×3000 with dithered gradients; collections get them again on their next sync.
- **Collections:** a smart collection tests a show's **Network** as TMDB names it, as a regular one does.
- **Collections:** **In the last** and **not in the last** count back from the moment they are tested, as Plex does.
- **Collections:** the **Missing** section is shown only for collections whose criteria use TMDB or MDBList lists, and **Automatic theme** stays visible, switched off, while **Theme** is **Not needed**.
- **Interface:** library lists are grouped under their media server; messages name the field, media type and server they are about; the database record leaves out jobs and names each server copy.
- **Interface:** saved filters are shared between movies and shows wherever their conditions apply; same-named filters that agree become one.
- **Interface:** criteria list a field's fixed values and those your library holds; IDs, TMDB keywords and labels stay typed.
- **Interface:** the filters popup is wider with **Custom filter** under Libraries; **Auto-match art on load** and **Auto-search themes on load** moved to Workflow in Settings.
- **Interface:** a page or popup that fails to draw shows the error with **Try again**, and an item's link to its OvertureDB collection uses the collection icon.
- **Operations:** an Assets run queues collection art in the art download lane, so its log shows it **Queued** and then **Downloaded**; Server audit logs one line per media server compared.
- **OvertureDB:** the **Contribute issue** link leaves **Reason for modification** for you to write, and its tooltip names what the issue replaces.
- **Storage:** uploaded images are kept for good in `uploads/` in the config folder, apart from the image cache, which moves from `cache/images` to `cache/`. Uploads in the cache move there at startup, each kept in the cache until its copy is verified. **Statistics** show uploads separately.
- **Storage:** every file Overture writes (images, artwork, themes, uploads, settings, backups) is on disk before it replaces the previous one, so a power cut leaves the old file or the new one.

### 🚨 Breaking Changes

- **Settings:** `TMDB_API_KEY` is removed. Set `TMDB_READ_ACCESS_TOKEN` to the **API Read Access Token** under **Settings -> API** on themoviedb.org; it is sent in a header, never in a URL. Until it is set, TMDB features are off.
- **Settings:** `MEDIA_SERVER`, `MEDIA_SERVER_URL`, `MEDIA_SERVER_API_KEY`, `MEDIA_SERVER_VERIFY_TLS` and `JELLYFIN_COLLECTIONS_PATH` are removed. Name the server instead: `MEDIA_SERVERS=Plex` with `MEDIA_SERVER_PLEX_TYPE=plex`, `MEDIA_SERVER_PLEX_URL`, `MEDIA_SERVER_PLEX_API_KEY` and, for Jellyfin, `MEDIA_SERVER_<NAME>_COLLECTIONS_PATH`. With the same type and URL, your library, choices and collections carry over.

### 🐛 Bug fixes

- **Collections:** renaming a group keeps it in the Sync and Assets schedules and selections that run it.
- **Collections:** Jellyfin 12 creates, edits, lists and syncs collections, including their members, which it shows only to a user.
- **Collections:** a Jellyfin or Emby library that groups movies into collections lists the movies, not the collection; syncing collections deleted such a collection.
- **Collections:** a managed collection takes over the collection Jellyfin or Emby made for the same TMDB collection under another name, instead of making a second one.
- **Collections:** a collection's images, kind and theme come from its copy on the first server in `MEDIA_SERVERS`.
- **Collections:** a new server copy of a collection gets its chosen art, instead of the sync failing with "Overture has uploaded no image to it"; Server audit's fix sends it the same way.
- **Collections:** syncing a collection whose server copy was deleted makes it again instead of failing.
- **Collections:** a managed Jellyfin collection gets its theme on its next sync when its BoxSet folder has none.
- **Collections:** Plex smart collections select actors and other values Plex leaves off its library list.
- **Collections:** Plex smart collections with an apostrophe in a text condition sync; Plex cannot match such text exactly, so **is** matches text starting and ending with it.
- **Collections:** a collection that needs no theme reports its theme complete after one is chosen or removed.
- **Collections:** a collection no server holds shows no server art instead of a broken image.
- **Collections:** **Jump to** in the configure view puts the section's header at the top, also for the last sections and while content above is loading.
- **Interface:** a tab left open while Overture is updated shows **Overture was updated** with **Reload** instead of becoming unresponsive, and over HTTPS keeps working until then; a page that cannot be loaded says so.
- **Media servers:** Jellyfin and Emby show the background Overture writes; the backgrounds they downloaded are removed first.
- **Media servers:** Emby keeps a collection's sort title through refreshes.
- **Operations:** a busy Assets run no longer fails with "QueuePool limit of size 5 overflow 0 reached".
- **Operations:** an Assets scan of a large library takes the same time per folder however many there are.
- **Operations:** a collection theme's log line says it was uploaded to the media server.
- **OvertureDB:** a collection's **Contribute issue** link includes the choices made since the collection was opened.
- **Themes:** a theme that failed to download is tried again once a download of it for that title has succeeded.

## 0.3.0 - 2026-11-15

### 🚀 Features

- **Interface:** **OvertureDB poster**, **OvertureDB background**, **OvertureDB season posters** and **OvertureDB theme** filters list the titles and collections whose choice for that slot matches OvertureDB's or differs from it; a choice only one side has is a difference.
- **Interface:** searching TMDB keeps sorting (relevance, title or year) and filters by whether your library or OvertureDB holds a title.
- **OvertureDB:** **Poster style** in the catalog's filters shows and edits a collection's individual, matte or overlay poster.
- **Collections:** `{source_summary}` and collections without a summary template take an MDBList list's description too, beside TMDB franchise and list overviews and TMDB people's biographies.
- **Collections:** **Contribute to OvertureDB as** on a collection's Poster tab picks whether the poster you choose is an individual, matte or overlay poster; OvertureDB offers all three of a collection's posters, each labelled with its style.

### 🌟 Enhancements

- **Interface:** art sources are named TPDb and TVDB on candidates, filters and messages; **Automatic art** lists the single sources before their combinations, and the art panel shows TMDB right after matched candidates and OvertureDB last.
- **Collections:** **OvertureDB posters** offers **Individual**, **Matte** and **Overlay** collection poster styles, and Overture reads version 4 of the OvertureDB catalog (`poster_url_individual`, `poster_url_matte` and `poster_url_overlay`).
- **OvertureDB:** the catalog's collections open at `/overturedb/collections` and are listed beside both Movies and Shows.
- **Interface:** database record rows are named by what they hold, such as **Background**; checkbox lists fit their labels.
- **Notifications:** titles name the run without an "Overture:" prefix.

### 🐛 Bug fixes

- **Notifications:** **Run now** on a schedule is a run you started, so rules limited to scheduled runs leave it out and the job panel no longer names the schedule.
- **OvertureDB:** clearing all art of a catalog movie or collection draft is saved instead of refused.
- **Interface:** auto-advance moves through TMDB results that open as catalog entries or collections, and counts a catalog collection's poster of the shown style.
- **Interface:** the sidebar search field shows no inner outline, and its search-by button fills the field's height.
- **OvertureDB:** a collection poster is exported and contributed as the style it was chosen as; changing **OvertureDB posters** no longer moves every chosen poster to the new style. Posters chosen before keep the style OvertureDB holds them as, else Individual.
- **Interface:** the sidebar's sort, group and shortcut labels and small caps headings are drawn at the type scale's smallest size instead of 10-12px, so they no longer look blocky at 100% zoom.
- **Assets:** runs wait out an image host's rate limit, such as ThePosterDB's, and try again instead of reporting the slot as an error; collection art is fetched once, without a separate request to measure it first.
- **Assets:** **Replace existing** skips a slot whose file is already the art a source picks instead of downloading it again and reporting it as downloaded.
- **Artwork:** matched candidates name their source, such as TMDB or ThePosterDB, and every candidate names a known source by its name.

### 🔒 Security

- **Authentication:** sign-in rate limiting reads the client address only from the `X-Forwarded-For` entries trusted proxies add, so a forged entry cannot share one limit between every client, and trusts a proxy reached over an IPv4-mapped IPv6 address by its IPv4 network.

## 0.2.0 - 2026-11-14

### 🚀 Features

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

### 🌟 Enhancements

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

### 🐛 Bug fixes

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

### 🔒 Security

- **Container:** the image applies Debian's security updates when it is built and leaves out `apt`, PyYAML and watchfiles, which Overture never uses.

## 0.1.0 - 2026-11-03

The first public release of Overture: artwork, collections and theme songs for
Plex, Jellyfin and Emby, kept as ordinary files beside your media.

### 🚀 Features

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
