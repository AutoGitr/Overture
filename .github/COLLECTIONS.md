# Collections and Kometa equivalents

Overture configures collections through **Collections > + Create collection**
and **Collection groups**. It covers most of what a Kometa configuration does
with its own forms; it does not import Kometa YAML or run Kometa defaults files.

| Kometa | Overture |
| --- | --- |
| `smart_filter` with `all` / `any` | Criteria evaluated by **Plex (smart)** |
| `plex_search`, `filters` | Criteria evaluated by **Overture** |
| `smart_label` | Lists in Plex smart criteria; Overture keeps their labels |
| `tmdb_collection`, `tmdb_list`, `tmdb_movie`, `tmdb_show` | TMDB franchise, list and title conditions |
| `tmdb_popular`, `tmdb_top_rated`, `tmdb_trending_*`, `tmdb_now_playing`, `tmdb_upcoming`, `tmdb_airing_today`, `tmdb_on_the_air` | **TMDB chart** condition, in the **TMDB region** |
| `tmdb_actor`, `tmdb_director`, `tmdb_writer`, `tmdb_producer` | TMDB person condition with roles |
| `tmdb_company`, `tmdb_network` | **Production company** and **Network** conditions, from TMDB |
| `mdb_list` | MDBList condition |
| `radarr_taglist`, `sonarr_taglist` | Radarr and Sonarr tag conditions |
| `original_language`, `origin_country`, `tmdb_vote_average`, `tmdb_vote_count`, `tmdb_keyword`, `tmdb_status`, `last_episode_aired`, `versions`, `filepath` | Criteria fields of the same meaning |
| `.not` modifiers, exclusions | **is not** and **not in** conditions |
| `sort_by`, `collection_order` | **Sort** (custom keeps the first list's order) |
| `limit` | **Limit** |
| `minimum_items`, `delete_below_minimum`, `sync_mode` | **Settings** at every level |
| `collection_mode`, `collection_filtering`, `visible_*` | **Settings** (Plex) |
| `hub_priority` | **Home order** (Plex) |
| `sort_title`, `summary`, `tmdb_biography`, `tmdb_description`, `tmdb_summary` | **Sort title** and **Summary** templates with `{source_summary}` |
| `schedule`, `schedule: range(...)`, `delete_not_scheduled` | **Sync schedule** (cron), active dates and **When inactive** |
| `show_missing` | **Missing** under Members |
| `radarr_add_missing`, `sonarr_add_missing` and their folder, profile and search | **Request missing**, with the folder and profile in Settings |
| `item_label`, `item_radarr_tag`, `item_sonarr_tag` | **Member label** and **Radarr/Sonarr tag** |
| `dynamic_collections` | A **collection set** on a group |
| `type: custom`, `key_name_override`, `title_override`, `addons`, `include`, `exclude` | Custom sets, renamed and merged values, Only these and Skip these values |
| Libraries sharing one collection file | One collection in several **Libraries** |
| `templates`, defaults files | Presets, saved presets and group defaults |

Overture reads TMDB, MDBList, Radarr and Sonarr; it does not read IMDb,
Letterboxd or Trakt lists. To use one, mirror it in MDBList.

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

Overture: create a collection, choose **Plex (smart)**, set **Match all of the
following**, and add **Audio language is not English**, **Country is not
Canada** and **Country is not United States of America**. Set **Sort** to Title
(A to Z). Each condition lists the values Plex knows for the library.

The **Unplayed**, **Recently played** and **Continue watching** presets set
**Collection filtering** to User's library, so each user sees their own.

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
Plex shows each user the requests they have not watched.

## Charts and requests

Kometa:

```yaml
Trending:
  tmdb_trending_weekly: 50
  collection_order: custom
  radarr_add_missing: true
```

Overture: start from the **Trending** preset, or add a **TMDB chart** condition
set to Trending this week with 50 titles, and turn on **Request missing**. Each
sync asks Radarr for the trending movies the library lacks, with the root
folder and quality profile chosen under **Settings > Collection defaults**.
**Missing** under Members lists them and requests them on demand.

## One collection per decade, language or anything you list

1. **+ Create collection**, choose the libraries, and **Start from** Decades,
   Original languages, Streaming services, A to Z or another set, which
   switches **Create** to **One per value**. Name the group, or leave it blank
   to name it after the values.
2. In **Content**, adjust what it **Splits by**, the most common values only,
   values to include or skip, text to remove from names, values to rename or
   merge, and the conditions every collection needs. A **Custom** split lists
   its collections, each with its own criteria.
3. **Preview collections** lists each collection and its size; values below the
   minimum are left out.
4. Set the group's defaults in **Settings** and **Schedule**, then **Save and
   Create**. **Save** keeps the set in Overture until you sync its group.

On its schedule the set creates collections for new values, renames and updates
its collections when you change the set, and removes collections whose value
disappears when the set says so. Kometa's `dynamic_collections` with
`type: tmdb_collection`, `remove_prefix`, `remove_suffix` and `exclude` is a
TMDB franchises set with those options.

## Groups, overrides and deletion

A collection's explicit choice overrides its group, and the group overrides
**Settings > Collection defaults**. **Default** inherits and names the value it
inherits. **Save and Apply** sends the group's display settings at once,
keeping members and explicit overrides.

**Collection groups > Rename or delete** renames or deletes a group. Deleting
just the group leaves its collections ungrouped; you can also remove its
collections from Overture, the media server, or both. Media files are always
kept.

See the [collection guide](README.md#collections) for every option.
