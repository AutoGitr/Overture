---
sidebar_position: 3
title: Themes
description: Theme songs from OvertureDB, ThemerrDB and YouTube, saved as MP3.
---

# Themes

Choose OvertureDB or [ThemerrDB](https://github.com/LizardByte/ThemerrDB)
picks, search YouTube with a duration limit, or paste a YouTube link. Every
candidate has a preview. Saving a choice downloads it as `theme.mp3` beside the
media, with optional loudness normalization.

## YouTube search

YouTube theme searches show up to 20 results within the theme duration
limits, drawn from the first 50 videos YouTube finds. With **Auto-search
themes on load** (Settings, on by default) a title's themes are searched for as
soon as you open them; turn it off to search only when you choose **Search**.

YouTube blocks addresses that download too fast; `THEME_DOWNLOAD_WORKERS`
keeps parallel downloads low.

## No theme

Some titles have no theme music. In the OvertureDB view, **No theme** drafts
that a title has none; once the catalog carries the flag, the next OvertureDB
sync brings it to your library, where the title's theme counts as complete and
theme runs skip it. **Trust OvertureDB's No theme flag** under
**Settings -> OvertureDB** controls this.

## Remove themes

The clear button on the theme tab, and **Remove themes** for the filtered
titles or collections, work like [removing artwork](artwork.md#remove-artwork):
forget the selection, delete `theme.mp3` from the media folder, delete the
server's copy, or any combination that applies.

## Collection themes

Collections take themes too. Collection themes use OvertureDB and ThemerrDB in
the configured order; YouTube search applies to movies and shows. On Jellyfin,
BoxSet themes are written into the collections directory named by
`JELLYFIN_COLLECTIONS_PATH`.

## Contributing themes

OvertureDB takes themes 20 seconds to 10 minutes long, so contributions leave
out a chosen theme outside that and say why. See the
[theme requirements](/overturedb/contributing/selection-guidelines#theme-requirements).
