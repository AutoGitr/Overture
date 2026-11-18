---
sidebar_position: 6
title: Files
description: Where Overture writes artwork and themes, and what it names them.
---

# Files

Overture names files the way your media servers expect. Where the servers
holding a title read different names, it writes the file under each, so a
season of a show on Plex and Jellyfin gets both `Season01.jpg` and
`poster.jpg`. Images are `.jpg`, `.jpeg` or `.png`; saving one format removes
the others for that slot.

| File                                    | Plex                         | Jellyfin                     | Emby                         |
| --------------------------------------- | ---------------------------- | ---------------------------- | ---------------------------- |
| Poster                                  | `poster.jpg`                 | `poster.jpg`                 | `poster.jpg`                 |
| Background                              | `background.jpg`             | `background.jpg`             | `background.jpg`             |
| Season poster, in the season folder     | **`Season01.jpg`**           | `poster.jpg`                 | `poster.jpg`                 |
| Specials poster, in the specials folder | `season-specials-poster.jpg` | `season-specials-poster.jpg` | `season-specials-poster.jpg` |
| Theme song                              | `theme.mp3`                  | `theme.mp3`                  | `theme.mp3`                  |

Files are written to the folders the servers report, as each server's
[path map](../install/media-servers.mdx#path-maps) translates them.

Files for a collection go to each media server holding it, since a collection
has no folder; a Jellyfin BoxSet theme goes to the collections directory named
by that server's `COLLECTIONS_PATH`.

## Where each asset goes, and how each server takes it

After Overture writes or removes an asset, it asks every server holding the
title or collection to pick the change up, so each server shows the same
choice.

| Asset                            | Plex                                                                           | Jellyfin                                                                                                                           | Emby                                    |
| -------------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Title poster and background      | File in the title's folder; Overture unlocks the field and refreshes the title | File in the title's folder; for a background, Overture first removes the backgrounds Jellyfin downloaded, then refreshes the title | As Jellyfin                             |
| Season poster                    | `Season01.jpg` in the season folder; unlocked and refreshed with the show      | `poster.jpg` in the season folder; refreshed with the show                                                                         | As Jellyfin                             |
| Title theme                      | `theme.mp3` in the title's folder; unlocked and refreshed                      | `theme.mp3` in the title's folder; refreshed                                                                                       | As Jellyfin                             |
| Collection poster and background | Uploaded to each library's copy of the collection                              | Uploaded to the one BoxSet                                                                                                         | Uploaded to the one BoxSet              |
| Collection theme                 | Uploaded to each library's copy                                                | `theme.mp3` in the BoxSet's folder under `COLLECTIONS_PATH`, then the BoxSet is refreshed                                          | Emby does not support collection themes |

Plex takes an item's local files on a refresh only for fields that are not
locked; Overture unlocks just the fields it changed, so an asset you locked in
Plex for another reason stays as it is.

Jellyfin and Emby pick a folder's image by name, in a fixed order. A poster
named after the video file (`Movie (2000).jpg`) comes before `poster.jpg`, and
`fanart.jpg` comes before `background.jpg`, so remove or rename such files
(**Renamer** lists them) when the server shows one of them instead of
Overture's. See [server settings](../install/media-servers.mdx) for how to
keep the servers from saving them.

Every download, a collection's art and theme included, runs in the download
queue: one lane for art and one for themes, each with its own number of
workers (`ART_DOWNLOAD_WORKERS`, `THEME_DOWNLOAD_WORKERS`).

## Renamer

**Renamer** finds nonstandard asset filenames such as `folder.jpg` and renames
the ones you select, so an existing library ends up with one naming scheme.
See [Operations](operations.md).

## The config directory

Beside the media, Overture keeps its own state in the config directory
(`/config` in Docker, `/var/lib/overture` for the service):

| Path          | Contents                                                                            |
| ------------- | ----------------------------------------------------------------------------------- |
| `overture.db` | The database: library, choices, collections, schedules and settings                 |
| `backups/`    | Database backups; see [Backup and restore](../administration/backup-and-restore.md) |
| `uploads/`    | The images you uploaded, by the hash of their bytes; Overture never deletes them    |
| `cache/`      | A copy of every other image Overture shows, and the thumbnails; safe to delete      |

Your media folders hold the files; the database holds what was chosen and why;
`uploads/` holds the images nothing else has. Keep `uploads/` with the
database: deleting the cache only costs fetching, drawing generated art and
rendering thumbnails again, but a lost upload has to be uploaded again.
