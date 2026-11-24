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

A title, season or collection shows its local artwork, else the image its
lead media server shows, as the last sync read it.

For titles outside your library, switch the search field to one under **TMDB**
(requires `TMDB_READ_ACCESS_TOKEN`): **Title or ID**, or the titles of a **Person**
(everything they acted in or worked on), a **Company** or a **Keyword** (their
most popular titles), or a public **List**. Each takes a name, a TMDB ID or a
TMDB page link; a list takes its ID or link, since TMDB cannot search lists.
The results say whose titles they are. Choices for these titles are saved and
downloaded when a sync finds their media folder. TMDB results keep TMDB's order
by default and sort by title or year; the filters then choose whether titles
your library or OvertureDB holds are listed.

Every section of the filters popup collapses, and stays as you left it. The
item filters can also show only the titles of one **Collection**. For shows,
**Season posters complete** lists the shows with every season poster saved,
and **Art resolution** and **Art source** can look at the season posters: a
show's season posters are as wide as the narrowest of them, and come from
each of their sources. While
OvertureDB is on, **OvertureDB poster**, **OvertureDB background** and (for
shows) **OvertureDB season posters** under Art, and **OvertureDB theme** under
Theme music, list the titles and collections whose choice for that slot
matches OvertureDB's or differs from it. A choice only your library or only
OvertureDB has is a difference, and a title OvertureDB has no entry for is
listed by neither.

### Custom filters

**Custom filter**, under Libraries in the movie and show filters, keeps saved
filters of your own, like smart collections that only filter the list. Choose
**New**, name it, and add conditions on anything Overture knows about a title:
the same metadata collection criteria test (genre, actor, director, studio,
resolution, HDR, codecs, ratings, runtime, keywords, streaming services and
more), TMDB lists, people, charts and MDBList lists, and each title's status
in the library: monitored, art, poster, background, season poster and theme
status, art and theme source (season posters included), poster, background
and season poster width, aspect ratio, theme length, metadata issues,
OvertureDB coverage and how each choice compares with OvertureDB's. The
conditions are edited as in collection
[criteria](collections/criteria.md#values), and suggest the values every
library of the media type holds, as the filter tests them all. A filter offers
what Overture stores and each title's status; a collection offers no status
but, on Plex, what only smart collections test. Conditions match together (**all**) or apart
(**any**), and groups nest for anything in between; **is not** and **does not
contain** exclude.

Pick a saved filter to apply it with the other filters; **Edit**, **Save as
new** and **Delete** manage them. Saved filters are kept on the server, so
every browser sees them, and each is offered for movies, shows or both,
wherever all its conditions apply; one naming titles by TMDB ID stays with the
media type it was made for. **Add saved filter...** in any criteria, a
collection's included, adds a saved filter that fits them as a group. Status conditions follow every
download and choice at once; metadata conditions update after each sync.

## Install as an app

Overture is a progressive web app. To install it, open it in Chrome, Edge or
Safari and choose **Install** in the address bar (on iOS: **Share > Add to Home
Screen**). The app gets its own window, Movies and Shows shortcuts, and updates
itself.

Browsers offer this only over HTTPS, so serve Overture through a
[reverse proxy](../install/reverse-proxy.md) with a certificate, or open it on
`localhost`.

## Statistics

The storage footprint includes the image cache, with its originals and
thumbnails, and your uploads. Artwork coverage includes collection posters,
backgrounds and themes, so the numbers show what still needs attention; the
images Overture uploads to collections are kept in the image cache and counted
there, not in the artwork sizes.

Statistics count what Overture keeps, not what each server holds. A title on
several servers is one title, with one set of files, and a collection on
several servers or libraries is one collection. The same film in two folders,
such as a 4K and an HD copy, is two titles, since each folder needs its own
files. A season poster written under each server's name counts its size once.

## Database record

Every item and collection has a database record view that lists every stored
column of the record and of the rows that belong to it, such as seasons, its
assets and each server's copy, apart from what Overture derives from them.
Each row is named by what it holds, such as **Background**, **Season 2
poster** or **Copy in Plex · Movies**. Downloads and other jobs are work done
for a record rather than part of it, so they are left out.
The same data is available through the [REST API](api.md).
