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
each group below Movies and Shows; tick every collection or chosen groups, now
or on a schedule. In **Assets**, one run covers the libraries and collections
you tick; or use **Current sidebar items** from the collection list to target
its filtered rows. Only collections Overture manages are touched. Collection
posters and backgrounds come from OvertureDB, or local-image matching against
the server's current image, and are uploaded to the media server. Collection
themes use OvertureDB and ThemerrDB in the configured order; YouTube search
applies to movies and shows.

### How Assets treats existing choices and files

By default, Assets skips slots that already have a saved choice and keeps
every file it did not write for one. It downloads the saved choice again when
its file is missing, or was replaced by another program after Overture wrote
it, as Radarr's or Sonarr's media upgrades can do.
This happens whichever sources the run uses, since the saved choice is never
looked for again:

| Saved choice | Local file                    | Default                   | Replace existing |
| ------------ | ----------------------------- | ------------------------- | ---------------- |
| Yes          | The one Overture wrote for it | Skip                      | Search again     |
| Yes          | Missing, or replaced since    | Download the saved choice | Search again     |
| No           | Either                        | Search                    | Search again     |

Saved choices include the artwork URLs Sync copies from your media server, so
a run downloads those to the media folder when no local file exists yet. Before
it plans, a run checks the files of the titles with saved choices; an
unchanged file costs one look at its size and modification time and is not
read. To keep a file you put there yourself, clear the saved choice, or upload
the image instead.

**Replace existing** also replaces existing theme files; a downloaded file
identical to yours is left untouched. A source image identical to your file is
adopted in place. OvertureDB's artwork is compared with your file as local
image matching compares its candidates: by default only an identical file is
taken, and a looser matching threshold also takes the same picture saved
differently, replacing your unsaved file with OvertureDB's.

**Skip recently checked** skips searches within the chosen time window, also
with Replace existing. Restoring a saved choice always runs.

## Renamer

Renamer scans the selected libraries for asset files with other names than the
ones in [Files](files.md) and lists them; you choose which to rename. A
Renamer scan also notices files deleted outside Overture.

## Server audit

Server audit compares the local assets on disk with what the server displays and
plays, and optionally the images Overture uploaded to collections with the
server's copies. Fix the selected differences, and Server audit checks whether the
changes took effect. If the server shows old artwork, run Server audit and check the
server's local-assets setting.

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
