---
sidebar_position: 1
title: Collections
description: Plex, Jellyfin and Emby collections built from criteria, lists and franchises, kept in sync by Overture.
---

# Collections

Overture builds collections from criteria, TMDB franchises and lists, MDBList
lists and people, or one per decade, genre or studio, and keeps them on the
media server on a schedule. Every collection Overture creates has criteria;
collections made outside Overture stay untouched until you adopt them.

Set `TMDB_API_KEY` for TMDB lists, charts, titles, people, franchises and
facts, `MDBLIST_API_KEY` for MDBList, and the Radarr or Sonarr URL and API key
for their tags, requests and member tags.

## The collection sidebar

Collections open from the icon beside Movies and Shows in the library sidebar,
with movie and show collections together. The first click opens the view you
used last, **Groups** (a folder icon: collections inside their groups) or
**Collections** (a layers icon: all in one list); each further click switches
between them, and hovering it shows the icon of the view it switches to. Its
count is what it lists: groups or collections.

Movies and shows share groups. **Holds**, a status filter, narrows the list to
either or to collections of both; **Made as** narrows it to collections made
one at a time (**One collection**) or by a set (**One per value**). In the
OvertureDB catalog, the same icon beside Movies opens its collections.

**Groups** lists every group, empty ones too; **Ungrouped** and **Unmanaged**
appear only while they hold a collection. A sparkle marks smart collections.
The sort menu of **Groups** sorts the groups themselves, by name, collections,
items, date added or last synced.

## The Configure page

**+ Create collection** opens a Configure page, the one place to create
anything: **One collection**, or **One per value** (a
[collection set](sets.md)). Both kinds share the same sections, in the same
order:

1. **Setup**: what to **Create** first; for a set, what it **Splits by** next,
   which names its group and its title template, and fills in what suits the
   values, such as release order and names without "The" and "Collection" for
   TMDB franchises. A dimension adds no minimum or **Most common only** of its
   own. Then the libraries, the title (a set's title template, where
   `{value}s` turns 1990 into 1990s) and the group. A collection can span
   several libraries, of movies, shows or both, and the libraries of a saved
   collection can change: see
   [Collections across libraries](across-libraries.md).
2. **Content**: who evaluates the [criteria](criteria.md), and the criteria
   themselves, with one box for each library, and **Preview members**. A set
   instead chooses its values and the conditions every collection needs, with
   **Preview collections**.
3. **Members** (a saved collection): its members, and **Missing**, the titles
   its lists hold that the library lacks, which **Request** sends to Radarr or
   Sonarr.
4. **Settings**: sort and limit, Sync mode (Sync removes members that stop
   matching, Append keeps them), minimum, [Automatic art](art-and-themes.md),
   Generated colours, Background (Not needed makes a poster complete the
   collection's art), automatic theme, Request missing, Member label, Radarr or
   Sonarr tag, Plex's collection mode, filtering (smart collections only: Plex
   evaluates a smart filter, such as Unplayed, for each user; a regular
   collection shows everyone the same members, and Jellyfin and Emby have no
   such choice), Home and recommended promotion and Home order, sort title and
   summary templates, and the TMDB collection ID.
5. **Active dates**: the dates a collection is on the server, which repeat
   yearly and can cross New Year, and whether an inactive collection leaves the
   server. An inactive collection's art and theme can still be chosen:
   Overture keeps them, and the sync that puts the collection back sends them.

A collection's page opens with Setup and Content expanded and the rest closed,
and a group in **Collection groups** with every section closed, each time;
neither remembers what was open.

## Saving and syncing

**Save** (or Enter) saves in Overture only and never contacts the media
server, so it is instant; a new collection's lists are read on its first sync.
Only **Sync** under [Operations](../operations.md) changes the server, so every
sync runs, and is scheduled, in one place.

**Save and Sync** saves, then opens **Sync** in Operations with only this
collection chosen, or a new set's group, and every library unticked; **Run
now** creates or updates it on the server, then picks art and themes, labels
and tags members, requests missing titles and orders Home rows as its settings
say. Members you add, remove or reorder also wait for the next sync. A
collection with changes the server does not have shows **Unsynced**, and a
library sync keeps those changes.

Every collection sync, scheduled or run now, is a **Sync** under Operations,
which can sync every collection, chosen groups, or chosen collections under
**Specific collections**.

## Templates

Summary templates take `{title}`, `{group}`, `{start_date}`, `{end_date}`,
`{summary}` (the server's) and `{source_summary}`, the description of the
first list or a person's biography. Without a template, a collection keeps its
own summary, or takes its list's description, so each TMDB franchise gets
TMDB's overview.

Sort titles leave out a leading "The", "A" or "An" of the title and group, as
Plex does when it sorts titles itself.

## Minimum members and active dates

**Minimum members** and **When inactive** decide only whether a collection is
on the media server: below its minimum, out of season or left out by its set,
**Remove from server** takes the server copy away and a later sync puts it
back. Overture keeps every collection it manages until you delete it; a
managed collection deleted on the server is recreated by its next sync. Only
unmanaged collections disappear from Overture, when the server no longer lists
them.

## Pages in this section

- [Criteria](criteria.md): conditions, lists, TMDB facts and Plex smart
  collections.
- [Collection sets](sets.md): one collection per value.
- [Groups](groups.md): shared settings, defaults and separators.
- [Collections across libraries](across-libraries.md).
- [Art and themes](art-and-themes.md): automatic and generated art, OvertureDB
  posters.
- [Managing collections](managing.md): adopt, orphan, delete, requests and
  tags.
