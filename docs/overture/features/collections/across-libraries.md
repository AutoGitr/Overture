---
sidebar_position: 5
title: Collections across libraries
description: One collection drawing from several libraries, and what each server holds.
---

# Collections across libraries

Choosing several libraries in Setup makes one collection, listed once, with
its own criteria for each library. What the server holds depends on the
server:

| Server         | On the server                                                                                                      | Kept alike                                                       |
| -------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| Jellyfin, Emby | One collection holding every library's members, movies and shows together                                          | Nothing to keep alike                                            |
| Plex           | One collection in each library with the same title, because Plex keeps a collection inside one library of one type | Overture sends each the same title, summary, sort, art and theme |

Settings, the group, art and theme belong to the whole collection; **Limit**
applies to each library, and **Minimum members** to the whole. On Plex a
smart collection is smart in every library.

A library with nothing to hold gets no server collection until it has, and a
library taken out of a saved collection leaves the server at the next sync. A
collection set makes one collection per value across its libraries, in the
same way, and offers the fields and dimensions all of them share.

Orphaning a Plex collection keeps its first copy as this collection; the next
library sync lists the others on their own.

## When libraries change

When the server stops listing a library and a sync finds its titles in
another, collections, sets and schedules move to that library, as after a
[change of media server](../../install/media-servers.mdx#change-media-server).

A collection without a copy on the server takes over the server's unmanaged
collection of its title in that library instead of making a second one.
