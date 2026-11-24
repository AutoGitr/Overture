---
sidebar_position: 5
title: Operations
description: Sync, Assets, Renamer and Server audit, by hand or on a schedule.
---

# Operations

Operations do the work in bulk for the libraries and folders you pick, and run
in the background, so you can close the browser; **Stop** keeps what has
finished.

| Operation    | What it does                                                                                                                                                               |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sync         | Imports library items, folders, seasons and existing local assets. Full sync also hides items removed from the server and keeps their files.                               |
| Assets       | Fills artwork and themes for monitored items using your chosen sources and order. Runs manually or on a schedule.                                                          |
| Renamer      | Finds nonstandard asset filenames such as `folder.jpg` and renames the ones you select.                                                                                    |
| Server audit | Compares local assets, and optionally the images Overture uploaded to collections, with the server; fixes selected differences and checks whether the changes took effect. |

While a run reads what it will work on, its progress counts what it has read
so far; the total follows once it knows everything.

A run you start keeps its results on screen until you choose **Clear results**
or the next run starts. A scheduled run, including an incremental poll, never
leaves results to clear, whatever its outcome: the schedule's **Last run** sums
it up.

Collections is its own section beside Libraries or Folders in Assets, Sync and
Server audit, with its own **Select all**; in Sync and Assets every collection
includes every group, so unticking one group keeps the rest.

## Sync

Sync schedules can run a full reconciliation or poll for newly added media
(**incremental**). Incremental schedules can also fetch OvertureDB artwork and
OvertureDB or ThemerrDB themes for new items. Run a full Sync first to import
your existing library.

In full **Sync**, **All collections** refreshes collection metadata and
memberships for the selected libraries, and a group runs its set and syncs its
collections instead; tick collections without a library to sync only them,
under **Specific collections**. Only **Sync** changes collections on the media
server; see [Saving and syncing](collections/index.md#saving-and-syncing).

## Assets

Assets can use OvertureDB and local-image matching for artwork; theme sources
are OvertureDB, ThemerrDB and YouTube search. Local-image matching finds a
source for artwork already on disk.

**Sync** and **Assets** share one checklist that lists **All collections** and
each group below Movies and Shows, and under **Specific collections** each
collection Overture manages; tick every collection, or chosen groups and
collections, now or on a schedule. In **Assets**, one run covers the libraries
and collections you tick; or use **Current sidebar items** from the collection
list to target its filtered rows. Only collections Overture manages are
touched. Collection posters and backgrounds come from OvertureDB, or
local-image matching against the server's current image; the run queues each
choice as a download, and the art lane's worker uploads it to every server's
copy. Collection themes use OvertureDB and ThemerrDB in the configured order;
YouTube search applies to movies and shows.

Each run's log lists **Queued** lines for the downloads it starts, then a
**Downloaded** or **Error** line as each one ends, whether it is art or a
theme, for a title or a collection. Every line names the title and the asset,
such as `Alien (poster)` or `Alien (theme)`; a collection's says so, as
`Alien (collection poster)`. A title or collection that leaves the library
during a run is **Skipped**.

### How Assets treats existing choices and files

Titles and collections follow the same rules. An asset's places are a title's
folder, or each server copy of a collection.

Each art and theme source list holds **Current selection**: what a slot
already holds, its saved choice or a theme in place. It is a place in the list
rather than a source, so it has no switch; drag it to decide what may replace
it. Sources above it may replace what a slot holds;
sources below it only fill slots that hold nothing. First, the default, keeps
everything you have; last lets every source replace it. In between, for
example OvertureDB and ThemerrDB above it and YouTube search below, curated
themes replace yours while a search only fills the gaps.

A saved choice is downloaded again when a place lacks it and no source above
Current selection replaces it: the file is missing, or was replaced by another
program after Overture wrote it, as Radarr's or Sonarr's media upgrades can
do, or a server copy shows another image or theme.

| Slot holds                    | A source above Current selection finds | None finds, or none is above it |
| ----------------------------- | -------------------------------------- | ------------------------------- |
| A saved choice, in place      | Replaced with what it found            | Kept                            |
| A saved choice, missing       | Replaced with what it found            | Downloaded again                |
| A theme Overture did not save | Replaced with what it found            | Kept                            |
| Art Overture did not save     | Every source is asked                  | Every source is asked           |
| Nothing                       | Every source is asked                  | Every source is asked           |

Art in place that nothing selects is identified by the sources: local-image
matching finds where it came from, and OvertureDB's artwork is compared with
it. Ranked below Current selection, OvertureDB adopts an identical image and
replaces a similar one only within the matching threshold; ranked above it,
OvertureDB replaces it outright.

Saved choices include the artwork URLs Sync copies from your media server, so
a run downloads those to the media folder when no local file exists yet. Before
it plans, a run checks the files of the titles with saved choices; an
unchanged file costs one look at its size and modification time and is not
read. To keep a file you put there yourself, clear the saved choice, or upload
the image instead.

A source only ever replaces a choice with something different: an asset that
already holds the art or theme a source picks, such as OvertureDB's, is
skipped without downloading anything. A downloaded file identical to yours is
left untouched. A source image identical to your file is adopted in place.

**Skip recently checked** skips searches within the chosen time window,
whatever Current selection's place. Restoring a saved choice always runs.

When an image host rate-limits Overture, as ThePosterDB often does, runs pause
every request to that host for as long as it asks (at least a minute, doubling
while the limits continue) and then try again, up to three times, instead of
failing the slot. Requests to other hosts carry on meanwhile. Choosing art
yourself while a host is paused says how long to wait instead.

## Renamer

Renamer scans the selected libraries for asset files with other names than the
ones in [Files](files.md) and lists them; you choose which to rename. A
Renamer scan also notices files deleted outside Overture.

## Server audit

Server audit compares the local assets on disk with what the server displays and
plays, and optionally the images and themes Overture holds for collections with the
server's copies. Each server holding a file is compared on its own, with a
line and a result per server. Images and themes are compared the way a sync
compares them, and what an audit finds on a collection's copies is recorded
as a sync records it, so the collection's status shows it at once. Fix the
selected differences, and Server audit checks whether the changes took effect. If a server still shows other artwork,
check its [settings](../install/media-servers.mdx) and the competing file
names in [Files](files.md#where-each-asset-goes-and-how-each-server-takes-it).

## Logs and results

A run's log has a filter for each outcome it logged, counting the targets
its lines name: a line such as `94 collections` counts 94, as the run's totals
and its notifications do. When its lines are about more than one media
server, it also has a filter for each server, by its `MEDIA_SERVERS` name and
coloured by its kind (Plex amber, Jellyfin purple, Emby green); each such line
shows its server the same way. Sync's lines name the server they were read
from, including the collections it reads, and Server audit's and its fixes'
the server compared.

Sync logs each managed collection on each server, in each library:

| Outcome                                                     | Means                                                                                             |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Added                                                       | The server collection was created, with how many titles it holds                                  |
| Updated                                                     | Titles were added or removed, with how many of each and what it holds now                         |
| Unchanged                                                   | It holds the same titles                                                                          |
| Removed                                                     | It was deleted, and why: a library left it, its set or season ended, or it fell below its minimum |
| Skipped                                                     | It was left alone, and why, such as out of season or below its minimum                            |
| Error                                                       | What the server refused; the other collections still sync                                         | Server audit's results can be filtered by server |
| the same way. A renamed server keeps its lines and filters. |

## Schedules

**Schedules** use five-field cron in your time zone (`TZ`). One operation runs
at a time: Sync, Assets, Renamer and Server audit each wait for whichever is running,
and a scheduled run waits its turn. Downloads, such as the art and themes you
choose by hand, run beside any of them.

Schedules keep their choice of libraries, groups and specific collections.
[Notifications](notifications.md) can announce when runs end, and can be
limited to scheduled runs.

## Bulk edits

**Filters & operations** in the library sidebar acts on the filtered titles:
run Assets on them, remove art or themes, and change monitoring. Removing art
or themes asks what to remove, as on an item's own tab; see
[Remove artwork](artwork.md#remove-artwork).
