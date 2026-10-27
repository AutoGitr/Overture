# Changelog

All notable changes to Overture are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and Overture adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- TMDB charts as collection lists: Popular, Top rated, Trending, In cinemas, Coming soon, Airing today and Airing this week, read for the new TMDB region setting.
- Collection criteria test what TMDB says about each title: original language, origin country, TMDB rating and votes, TMDB keywords, production companies, streaming services in your region, and for shows their network, status and last air date. Full Sync reads them for every title with a TMDB ID, and again weekly. Plex can also test how many versions a movie has, and every server its folder.
- Collection sets split by edition, network, original language, origin country or streaming service; on Plex, smart sets split by audio or subtitle language. Custom sets list their own collections, each with its own criteria, such as A to Z or Based on a book. Any set can rename or merge values, and can remove collections whose value disappears.
- A collection in several libraries: choose more than one library in Setup and it is kept alike in each.
- A Missing panel lists the titles a collection's lists hold that the library lacks, and requests them from Radarr or Sonarr. Request missing does this after each sync; choose the root folder and quality profile under Settings > Collection defaults.
- Member label and Radarr/Sonarr tag give a collection's members a label or tag and remove it from others. Home order arranges promoted collections on Plex's Home.
- Preview members shows what a collection's criteria select before you save. Save as preset keeps any collection or set as a starting point under Start from.
- Presets for TMDB charts, Most played, Returning series, Christmas, Halloween, Thanksgiving, Valentine's Day, the Marvel and DC universes, and sets for streaming services, languages, origin countries, networks, editions, Based on and A to Z.
- Collections whose criteria list a TMDB person offer the person's photos as poster candidates.
- Plex smart collections can test Dolby Vision, HDR10+, Dolby Atmos, video and audio codec, audio channels and minimum age, and show collections can test resolution, HDR, languages and codecs through their episodes.
- Collection criteria: groups that match all or any of their conditions, nested freely, where a condition tests item metadata or whether a TMDB franchise, TMDB list, TMDB titles, a TMDB person's credits, an MDBList list or Radarr and Sonarr tags hold the item. Values such as genres are suggested from the library, and people and franchises can be found by searching TMDB.
- On Plex, the same criteria can make a Plex smart collection with every Plex filter, including audio and subtitle language, HDR, edition and per-user play state; lists in its criteria become labels Overture keeps current.
- Collection sets create and maintain one collection per decade, year, genre, studio, country, content rating, resolution, label, actor, director, writer, producer or TMDB franchise in a library, with title templates, top values, include and exclude lists, shared conditions and a preview.
- Presets for collection sets and for collections such as Recently added, Top rated, 4K, Short films, Unplayed and Continue watching, offered only where the media server can evaluate them.
- Collections sort by release date, title, date added, critic, audience or user rating, duration, plays, last played, randomly or by custom order, and can keep only the first items in that order.
- The collection sidebar searches by title, group, TMDB collection ID or YouTube link, sorts by title, sort title, item count, date added, last sync or theme length, and filters by art, media server, catalog themes, members, kind, sync status and size like items.
- Rename and delete collection groups, optionally removing their collections from Overture, the media server or both while preserving media files.
- Public TMDB lists as dynamic collection sources, with ordered merging, pagination and movie/show filtering.
- Separate collection group management with shared defaults, explicit overrides and Save & Apply; Assets and full Sync share a Collections target, and unmanaged collection import can be disabled.

- Seasonal calendar windows and summary format templates for collections.

- Collection group defaults for sync, minimum membership, automatic assets, Plex visibility and sort-title templates, with individual rule overrides. Filtered bulk actions and empty-collection maintenance keep media files intact.
- Collection Configure shows TMDB source rosters, including missing franchise movies.

- Create, edit and delete Plex, Jellyfin and Emby collections, manage library members, and select collection posters and backgrounds. Plex supports custom member order, collection visibility and home promotion.
- Scheduled collection sync with inherited defaults and minimum member thresholds. Set `MDBLIST_API_KEY` for MDBList lists.

- Browse the full OvertureDB catalog from the sidebar, filter movies, shows and collections, and save local artwork and theme drafts to contribute through GitHub or the ZIP export.
- Collection pages show their members, explicit TMDB identity and OvertureDB/ThemerrDB theme candidates. Jellyfin 12 collection themes write into a mounted collections directory configured with `JELLYFIN_COLLECTIONS_PATH`.

- Assets can include collection themes for selected libraries or the current collection sidebar, using the configured catalog source order. Newly identified collections can receive catalog themes automatically from an enabled incremental sync policy.

### Changed

- Collections sync on a schedule like Overture's other jobs: a cron expression at the collection, group or global level replaces the interval in hours, which is converted. Scheduled sync can now be inherited by a collection like its other settings.
- Collection settings look the same everywhere: a collection's Settings and Schedule, a group's in the Collection groups popup and the global defaults under Settings use the same fields and names, and each Default names the value it inherits. One collection and One per value share Setup, Content, Settings and Schedule; a set's title template is in Setup.
- Summary templates take {source_summary}, the description of the first list or a person's biography, which replaces the person condition's Biography as summary. Existing biography summaries are converted.
- A set's collections are now removed when their value disappears only if the set says so, separately from Below minimum.
- Collections save in Overture only with Save (or Enter); Save and Create or Save and Sync also updates the media server. Members edited in Members wait for the next sync, a library sync keeps changes not yet synced, and a collection or set never created waits for Save and Create instead of the scheduler. Unsynced collections show an Unsynced badge.
- Collection pages keep both tab rows in every view: the art tabs always sit in the lower row next to links to Setup, Content, Members, Settings and Schedule, which open Configure at that section. A new collection has no tab rows and saves from the bottom of the form.
- Collection Display is now Settings and also holds Sort, Limit, Sync mode, the minimum and automatic art and theme; Content keeps only how members are chosen and the criteria. Groups are created in the Collection groups popup, which Create new group in the Group list opens; its buttons are Save, Save and Apply and Save and Sync.
- Theme status moved from the tab row into the Themes view, and labels across collections and groups now match, such as Sync mode, Collection mode, Active from and Active until.
- Appearance: Theme offers System, Light and Dark, and System (the new default) follows your device as it switches. The palette is rebuilt so text meets WCAG AA contrast in both modes and the accent looks the same in each; a new Increase contrast option strengthens secondary text and outlines. Controls, menus and cards share one modern style.
- Collection creation lists collection and set presets together under Start from, picking a set preset switches to One per value, and a set's group defaults to what it splits by, such as Decades.
- Collection criteria suggest title, studio and edition values from the library, as they already did for tags.
- Collection field, source, set and sort dropdowns list their options alphabetically within their groups, and field values are listed alphabetically. Hand-picked collections are labelled Manual.
- Collection sections collapse independently, with Setup and Content expanded initially; inherited choices use Default and text fields show inherited placeholders.
- Collection forms use full-width sections, and Sort title and Summary each accept text or templates in one field. Existing collection metadata is preserved on upgrade.

- Collection creation and editing share Setup for the library, a collection or a set, a preset, the title and the group, with content, members, display and schedule sections adapted to your choices. New collections open directly at Setup without an empty poster.
- Collection rules, Plex smart filters and TMDB franchise discovery groups are converted on upgrade to criteria and collection sets; orders become their nearest sort. Run a full Sync afterwards so ratings, plays, editions and Jellyfin and Emby tags are available to criteria. Jellyfin and Emby tags are now labels.
- Configure, filters and bulk operations offer only the fields, sources, sorts and options the media server supports, and say why a source is unavailable.

- Example Docker Compose configuration delegates all environment variables directly to `.env`.

- Collection groups hide their contents until opened, and share sidebar browsing with TMDB franchises. Art/theme badges and detail controls now share status and clear behavior; Emby collections hide unsupported theme badges.
- Creating a collection opens a fresh Configure page with library selection instead of a popup. Collection TMDB IDs are explicit and survive membership changes; existing IDs are preserved on upgrade, and automatic voting/matching controls are removed.
- Detail header boxes size to their contents with consistent button spacing and icon-only record actions. Collections without TMDB IDs skip artwork candidate requests.

- Item and collection headers use two continuous, stable boxes. Collections consolidate metadata, builder rules, explicit TMDB IDs and live members into Configure, with shared Save Changes and Sync Now controls.

- Plex and Jellyfin collections and their members are stored locally and refreshed on full syncs. Set an explicit TMDB collection ID for franchise artwork and catalog theme suggestions.
- Local artwork is cached under `<config>/cache/images/{originals,thumbs}` by BLAKE3 hash and served as AVIF display thumbnails across the UI, with cached originals used when opening posters at full size.

### Removed

- The Background Color appearance setting; each mode now has one tuned background. A saved background colour is ignored.
- Legacy collection preset generator, single-source rules, separate builders, managed Plex labels and group TMDB discovery, in favor of criteria and collection sets.
- Collection matching endpoints and automatic member voting. Set `tmdb_collection_id` through collection creation or update instead.
- The Plex-only Enable Collections setting. Collection navigation follows the configured server's capability.

### Fixed

- Emby collection sort titles now apply; Emby ignored the field Overture sent.
- Emby tags now sync, so Tag conditions on Emby match; run a full Sync to fetch them.
- Plex smart collections with "is" or "is not" on text fields, such as Title is 12 Angry Men, now match exactly instead of matching titles containing "=12 Angry Men".
- Creating a Plex smart collection no longer fails with "Media server returned an unsuccessful response" and no longer leaves the collection in Plex when a later step fails.
- Saving a collection no longer empties and locks its sort title or summary on Plex, Jellyfin and Emby when you have not set one; an unset sort title is left to the media server.
- Adding a source label to Plex items no longer removes the labels they already had. Source labels now name their source, such as `overture:tmdb_person:5292:actor`; the old hashed labels are removed on the next sync.
- Plex collection posters that Plex composes from members load instead of failing with 502, and a missing background returns 404.
- Plex smart collections test decades correctly when negated, match studios, editions and content ratings whose names Plex encodes, match every Plex key of a language, and test a show's unplayed and in-progress episodes. "Is not" is rejected for resolution, which Plex cannot negate, and critic and audience rating are offered only as sort orders, since Plex cannot filter on them.
- Collections can be deleted from Overture when they have already been removed from the media server.
- Plex smart collections work: filters use the keys Plex lists for tags such as genres, labels and languages, the operators Plex documents, exact number bounds and explicit and/or groups. Plex smart collections show server-controlled members without manual editing.
- Plex collection filtering (admin or user) is saved to the preference Plex reads, and imported Plex collections keep their visibility, sort and filtering.
- Unwatched Plex movies count as unplayed, and Jellyfin and Emby countries and tags are read during sync, so collection criteria on them match.

- Collection member ordering supports row-wide drag-and-drop and Up/Down controls, collection artwork links follow the selected slot, and create/generate selections stay consistent when changing libraries.

- OvertureDB item, collection, season and member images now show only catalog artwork or local draft overrides. Missing images use placeholders, and poster cards share consistent typography and spacing.
- OvertureDB pages reuse library artwork, season and theme views, with consistent links and clearable status badges. Draft artwork appears in the sidebar, and the original catalog artwork is offered only after a draft exists.
- Full Sync reports collection lookups, respects the selected libraries, and stops pending requests promptly when Stop is selected.
- Collection members appear in a linked poster grid. TMDB identity is available only for movie collections.
- Collection routes and queued downloads use stable database IDs, with migrated history and cascading cleanup. Jellyfin theme files retain their hashes and source provenance independently of Plex theme IDs.
- Unavailable Jellyfin mounts preserve saved state, and listed BoxSets keep their explicit IDs even when none of their members are visible locally.
- Catalog drafts stay editable after correcting their only identifier. Collection theme exports preserve ThemerrDB attribution, and catalog counts no longer require downloading the entire catalog.

- When YouTube or an artwork source such as ThePosterDB rate-limits Overture, Overture pauses its requests to that service, for longer each time the limit repeats. Theme and artwork downloads and bulk runs wait the pause out; theme searches, artwork matching, choosing artwork and media-server previews in the UI say when to try again.
- Assets runs that use only OvertureDB or ThemerrDB report artwork slots and themes the catalog has nothing for as No match, instead of skipping them as a saved selection that Overwrite existing would search again. Saved choices include the artwork URLs Sync copies from your media server, so this affected most items the catalog covers only partly.
- Assets logs say exactly why the catalogs had nothing: no OvertureDB entry, no artwork of that kind or no theme in the entry, or a theme that failed to download before. They also say whether a skipped saved choice is already the catalog's or differs from it. While OvertureDB is disabled, its targets are reported as Skipped because OvertureDB is disabled, instead of as No match.
- Failed theme downloads, YouTube searches and artwork downloads now say why, such as YouTube's own error or the HTTP status an artwork source returned, instead of a generic or truncated message.

## [1.1.0] - 2026-10-22

### Added

First stable public release of Overture

- Choose artwork and theme songs for Plex, Jellyfin and Emby
  libraries from your media server, TMDB, OvertureDB, ThemerrDB and YouTube,
  saved as files beside your media.
- Scheduled syncs and artwork and theme runs, along with renaming and audit functionality.
- Multi-platform container images on GHCR and Docker Hub, tagged with the full,
  minor and major version, and a native Linux archive with a systemd service.
