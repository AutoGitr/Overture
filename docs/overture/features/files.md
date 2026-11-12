---
sidebar_position: 6
title: Files
description: Where Overture writes artwork and themes, and what it names them.
---

# Files

Overture names files the way your `MEDIA_SERVER` expects. Images are `.jpg`,
`.jpeg` or `.png`; saving one format removes the others for that slot.

| File                                    | Plex                         | Jellyfin                     | Emby                         |
| --------------------------------------- | ---------------------------- | ---------------------------- | ---------------------------- |
| Poster                                  | `poster.jpg`                 | `poster.jpg`                 | `poster.jpg`                 |
| Background                              | `background.jpg`             | `background.jpg`             | `background.jpg`             |
| Season poster, in the season folder     | **`Season01.jpg`**           | `poster.jpg`                 | `poster.jpg`                 |
| Specials poster, in the specials folder | `season-specials-poster.jpg` | `season-specials-poster.jpg` | `season-specials-poster.jpg` |
| Theme song                              | `theme.mp3`                  | `theme.mp3`                  | `theme.mp3`                  |

Files for a collection go to the media server itself, since a collection has
no folder; a Jellyfin BoxSet theme goes to the collections directory named by
`JELLYFIN_COLLECTIONS_PATH`.

## Renamer

**Renamer** finds nonstandard asset filenames such as `folder.jpg` and renames
the ones you select, so an existing library ends up with one naming scheme.
See [Operations](operations.md).

## The config directory

Beside the media, Overture keeps its own state in the config directory
(`/config` in Docker, `/var/lib/overture` for the service):

| Path           | Contents                                                                               |
| -------------- | -------------------------------------------------------------------------------------- |
| `overture.db`  | The database: library, choices, collections, schedules and settings                    |
| `backups/`     | Database backups; see [Backup and restore](../administration/backup-and-restore.md)    |
| `cache/images` | Every image Overture shows, by the hash of its bytes, including uploads and thumbnails |

Your media folders hold the files; the database holds what was chosen and why.
