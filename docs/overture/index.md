---
sidebar_position: 1
slug: /
title: Introduction
description: What Overture does and how it fits with OvertureDB.
---

# Overture

Overture gives you complete control of your media library's look and sound.
Choose posters, backgrounds, season posters and theme songs yourself, or let
scheduled runs handle it automatically with the community picks in
[OvertureDB](/overturedb).

Your choices are saved as ordinary files beside your media, ready to back up
together and keep through server reinstalls or switches. Artwork and theme
files are written into your existing media folders, named the way your media
server expects, so Plex, Jellyfin and Emby pick them up as local assets.

## Features

- **Artwork in one place.** Compare candidates from your media server, TMDB and
  OvertureDB, sorted by resolution and ranked by visual similarity to your
  existing selection. Filter by aspect ratio and language, paste an image URL,
  or upload an image of your own.
- **Themes with a preview.** Choose OvertureDB or
  [ThemerrDB](https://github.com/LizardByte/ThemerrDB) picks, search YouTube
  with a duration limit, or paste a YouTube link. Save as MP3 with optional
  loudness normalization.
- **Collections that maintain themselves.** Build Plex, Jellyfin and Emby
  collections from criteria, TMDB franchises and lists, MDBList lists and
  people, or one per decade, genre or studio. Overture keeps them in sync on a
  schedule and can request missing titles from Radarr or Sonarr.
- **Everything on one page.** The library, artwork, themes and every tool share
  a single page; no item, view, setting or operation is more than two clicks
  away.
- **Quick manual review.** Filter by missing artwork or themes, advance after
  saving, skip completed items and optionally stop monitoring them. Coverage
  and storage statistics show what still needs attention.
- **Automation you control.** Schedule library syncs and artwork or theme runs.
  Choose sources and their order, limit runs to selected libraries, and
  preserve saved choices by default.
- **Choose ahead of time.** Search TMDB for movies, shows and collections,
  including unreleased titles. Save choices now; Overture downloads them when a
  sync finds their media folders.
- **Keep the library tidy.** Use Renamer to standardize asset filenames and
  Server audit to check whether your server displays and plays the files on disk.
- **Installable app.** Overture is a full progressive web app: install it from
  the browser on desktop or phone for its own window, with Movies and Shows
  shortcuts and updates applied automatically.

## Use cases

- **Hands-off libraries.** Schedule Sync and Assets with OvertureDB as the only
  artwork source and OvertureDB, ThemerrDB or both for themes. Let them import
  new media and fill gaps as the catalog grows. Check in occasionally to run
  Renamer and Server audit, and review the titles outside the catalog.
- **Mix automation and personal choices.** Let the catalog cover most of your
  library and override specific items with your own choices. Assets skips
  saved choices by default, so scheduled runs fill the gaps around your
  selections.
- **Curate everything yourself.** Keep automatic downloads off, choose artwork
  and themes item by item, and keep your selections private. Sync reads your
  existing local files; sharing to OvertureDB is always an explicit action.
- **Organize an existing collection.** Use local-image matching to identify the
  artwork you already have, Renamer to standardize filenames, and Server audit to
  check that your server uses your local assets.
- **Contribute to OvertureDB.** Use the catalog coverage filters to find gaps,
  choose artwork and themes as drafts, and export them as a batch. TMDB search
  lets you curate titles outside your library too.

## Where to go next

- [Install Overture](install/index.md) with Docker or as a Linux service.
- [First steps](features/getting-started.md) after the first start.
- [OvertureDB](/overturedb), the catalog behind the automatic choices.
- [Support](support.md) for what is tested and where to ask for help.
