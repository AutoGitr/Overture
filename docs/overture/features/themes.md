---
sidebar_position: 3
title: Themes
description: Theme songs from OvertureDB, ThemerrDB and YouTube, saved as MP3.
---

# Themes

Choose OvertureDB or [ThemerrDB](https://github.com/LizardByte/ThemerrDB)
picks, search YouTube with a duration limit, or paste a YouTube link. Every
candidate has a preview. Saving a choice downloads it as `theme.mp3` beside the
media, with optional loudness normalization. Each media server app plays it
once its theme music setting is on; see
[Media server settings](../install/server-settings.mdx).

## YouTube search

YouTube theme searches show up to 20 results within the theme duration
limits, chosen from the first 50 videos YouTube finds. With **Auto-search
themes on load** (Settings, on by default) a title's themes are searched for as
soon as you open them; turn it off to search only when you choose **Search**.

YouTube blocks addresses that download too fast; `THEME_DOWNLOAD_WORKERS`
keeps parallel downloads low.

## Themes that failed to download

When a theme run's download of a video fails, such as when YouTube refuses it,
later runs pass that video over for that title and try the next source, saying
"the ThemerrDB theme failed to download before" (or OvertureDB, or the
YouTube search's top result). A video is passed over until a later download of
it for that title succeeds, as choosing it again on the title's theme tab
does, or until the failed download ages out of the download history after 30
days.

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
BoxSet themes are written into the collections directory named by the
server's `COLLECTIONS_PATH`.

## Contributing themes

OvertureDB takes themes 20 seconds to 10 minutes long, so contributions leave
out a chosen theme outside that and say why. See the
[theme requirements](/overturedb/contributing/selection-guidelines#theme-requirements).
