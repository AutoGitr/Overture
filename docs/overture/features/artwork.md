---
sidebar_position: 2
title: Artwork
description: Choosing, uploading and removing posters, backgrounds and season posters.
---

# Artwork

Open an item to compare poster, background and season poster candidates from
your media server, TMDB and OvertureDB, sorted by resolution and ranked by
visual similarity to your existing selection. Filter by aspect ratio and
language, paste an image URL, or upload an image of your own. Saving a choice
downloads it beside the media, named the way your server expects (see
[Files](files.md)).

Set `TMDB_API_KEY` to get TMDB candidates and to search TMDB for titles
outside your library.

## Upload an image

Besides choosing a candidate or pasting a link, **Upload image** beside
**Paste URL** saves a JPEG or PNG from your device into any art slot, of an
item, a season or a collection; pasting an image on the art tab does the same.

An upload is kept in the image cache (`cache/images` in the config directory,
by the hash of its bytes, like every image Overture shows) and written beside
the media like any other artwork; a collection's goes to the media server.
Uploads count as saved choices, show as the **Upload** art source in the
filters, and cannot be contributed to OvertureDB, which takes public links
only.

## Remove artwork

The clear button on an art tab, and **Remove art** for the filtered titles or
collections in **Filters & operations**, ask what to remove, in any
combination:

- **Forget the selection**
- **Delete the local file** (the art in the media folder)
- **Delete from the media server**

Each choice says how many it applies to, or why it cannot: no selection, no
file, no server copy, or a server whose API cannot delete it. Plex's API
cannot delete artwork, so on Plex delete the local file: Plex shows its
agent's art after the refresh that follows.

Overture only ever deletes JPEG and PNG images and MP3 themes, checked by name
and contents, inside the title's folder; any other file stays.

## Local-image matching

Artwork already on disk can be identified by matching it against the
candidates Overture knows, so your existing files get a source and a saved
choice. **Assets** uses the same matching to decide whether a catalog image is
the one you already have; see
[How Assets treats existing choices and files](operations.md#how-assets-treats-existing-choices-and-files).

## Review quickly

Filter by missing artwork, and turn on auto-advance in Settings to move from
poster to background to theme to the next item as you save. Completed items
can be skipped, and optionally stop being monitored, so bulk runs leave them
alone.
