---
sidebar_position: 1
title: First steps
description: What to do after the first start.
---

# First steps

1. Run a full **Sync** to import movies, shows and your Plex, Jellyfin or Emby
   collections. With Collections selected, a full sync reads the server's
   collections, then syncs every collection Overture manages, sending its
   members, titles, sort titles, summaries and display settings; choosing
   groups syncs only theirs. Movies keep every director the server credits.
2. [OvertureDB](overturedb.md) is on by default; open an item to compare
   artwork and preview themes, with the community picks beside your server's
   own. Saving a choice downloads it.
3. Work through items manually, run **Assets** in bulk, or save schedules for
   Sync and Assets. Select the libraries, sources and replacement options you
   want each run to use. See [Operations](operations.md).

## The library

The sidebar offers search, sorting and completeness filters. An artwork slot
is complete when a choice is saved and its file exists; a show also needs a
poster for every season with videos.

For titles outside your library, switch the search field to **TMDB** (requires
`TMDB_API_KEY`). Choices for these titles are saved and downloaded when a sync
finds their media folder.

Every section of the filters popup collapses, and stays as you left it. The
item filters can also show only the titles of one **Collection**.

## Install as an app

Overture is a progressive web app. To install it, open it in Chrome, Edge or
Safari and choose **Install** in the address bar (on iOS: **Share > Add to Home
Screen**). The app gets its own window, Movies and Shows shortcuts, and updates
itself.

Browsers offer this only over HTTPS, so serve Overture through a
[reverse proxy](../install/reverse-proxy.md) with a certificate, or open it on
`localhost`.

## Statistics

The storage footprint includes the image cache, with its originals, uploads
and thumbnails. Artwork coverage and sizes include collection posters,
backgrounds and themes, so the numbers show what still needs attention.

## Database record

Every item and collection has a database record view that lists every stored
column of the record and of the rows that belong to it, such as seasons, art
slots and collection libraries, apart from what Overture derives from them.
The same data is available through the [REST API](api.md).
