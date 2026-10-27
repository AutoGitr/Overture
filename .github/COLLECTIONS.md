# Collections and Kometa equivalents

Overture configures collections through **Collections > + Create collection**
and **Manage groups**. It covers most of what a Kometa configuration does with
its own forms; it does not import Kometa YAML or run Kometa defaults files.

| Kometa | Overture |
| --- | --- |
| `smart_filter` with `all` / `any` | Criteria evaluated as a **Plex smart collection** |
| `plex_search`, `filters` | Criteria **Synced by Overture** |
| `smart_label` | Lists in Plex smart criteria; Overture keeps their labels |
| `tmdb_collection`, `tmdb_list`, `tmdb_movie`, `tmdb_show` | TMDB franchise, list and title conditions |
| `tmdb_actor`, `tmdb_director`, `tmdb_writer`, `tmdb_producer`, `tmdb_biography` | TMDB person condition with roles and **Biography as summary** |
| `mdb_list` | MDBList condition |
| `radarr_taglist`, `sonarr_taglist` | Radarr and Sonarr tag conditions |
| `.not` modifiers, exclusions | **is not** and **not in** conditions |
| `sort_by`, `collection_order` | **Sort** (custom keeps the first list's order) |
| `limit` | **Limit** |
| `minimum_items`, `delete_below_minimum`, `sync_mode` | Content and group defaults |
| `collection_mode`, `collection_filtering`, `visible_*` | **Display** (Plex) |
| `sort_title`, `summary` with template variables | **Sort title** and **Summary** templates |
| `schedule: range(...)`, `delete_not_scheduled` | Seasonal dates and **When inactive** |
| `dynamic_collections` | A **Collection set** on a group |
| `templates`, defaults files | Presets and group defaults |

Overture's lists are TMDB, MDBList, Radarr and Sonarr; it does not read IMDb,
Letterboxd or Trakt lists. To use one, mirror it in MDBList. Collections do not
add missing titles to Radarr or Sonarr.

## Smart collections from your Kometa smart filters

Kometa:

```yaml
Foreign:
  smart_filter:
    all:
      audio_language.not: English
      country.not: [Canada, United States of America]
    sort_by: title.asc
```

Overture: create a collection, choose **Plex smart collection**, set **Match all
of the following**, and add **Audio language is not English**, **Country is not
Canada** and **Country is not United States of America**. Set **Sort** to Title
(A to Z). Each condition lists the values Plex knows for the library.

The **Unplayed**, **Recently played** and **Continue watching** presets set
**Collection filtering** to User library, so each user sees their own.

## Lists combined with live filters

Kometa's `smart_label` labels the results of its builders and filters the label
in a smart collection. In Overture, put the list in the smart collection's
criteria:

```text
Match all of the following
  Radarr tags   in  request
  Unplayed      is  true
Sort: Date added (newest first)
```

Overture labels the tagged movies `overture:radarr_tag:...` on each sync, and
Plex shows each user the requests they have not watched. Lists can sit in any
group, with **in** or **not in**, like any other condition.

## One collection per decade, genre or franchise

1. **+ Create collection** and choose the library.
2. **Start from** Decades (or Genres, Directors, TMDB franchises and so on),
   which switches **Create** to **One per value**, and name the group, or leave
   it blank to name it after the values, such as `Decades`.
3. Adjust the set: the title template, the most common values only, values to
   include or skip, text to remove from names, conditions every collection
   needs, and whether to create Plex smart collections.
4. **Preview collections** lists each collection and its size; values below the
   group's minimum are left out.
5. Set the group's defaults under **Defaults**, such as a `01_{title}` sort title
   and the sync interval, then **Create set**.

On its schedule the set creates collections for new values, renames and updates
its collections when you change the set, and removes the collections of values
it no longer produces when **Below minimum** deletes. Kometa's
`dynamic_collections` with `type: tmdb_collection`, `remove_prefix`,
`remove_suffix` and `exclude` is a TMDB franchises set with those options.
TMDB franchise sets need `TMDB_API_KEY` and the franchise memberships a full Sync
imports, and skip franchises held by collections outside the group.

## Groups, overrides and deletion

A collection's explicit choice overrides its group, and the group overrides
**Settings > Collection defaults**. **Default** inherits. **Save & Apply**
updates the group's display settings at once, keeping members and explicit
overrides.

**Manage groups > Manage group** renames or deletes a group. Deleting just the
group leaves its collections ungrouped; you can also remove its collections from
Overture, the media server, or both. Server-only removal keeps the configuration
with scheduled sync disabled. Media files are always kept.

See the [collection guide](README.md#collections) for every option.
