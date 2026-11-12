---
sidebar_position: 7
title: Managing collections
description: Adopting, orphaning and deleting collections, requesting missing titles, and tagging members.
---

# Managing collections

## Unmanaged collections

Collections made outside Overture are listed only under the virtual
**Unmanaged** group, and Overture changes nothing about them, not even their
group, art or theme, until it adopts them. Their page offers only **Adopt**,
with the group to join; **Adopt unmanaged** in Collection operations does the
same for many.

Adopting gives a collection criteria that keep what it holds today: a regular
collection keeps its members, or, when they all belong to one TMDB
collection, follows that franchise; a Plex smart collection keeps its filter
when every Plex filter has an equivalent condition; otherwise Overture lists
the filters it cannot read. Adopting names members without a TMDB ID by their
TVDB or IMDb ID before their title.

**Orphan** (the unlink icon on a collection's page, or **Orphan managed** in
Collection operations) is the reverse: Overture forgets the criteria, group
and schedule, the server keeps the collection as it is, and it is listed
under Unmanaged again.

## Deleting

A collection's delete action asks where to delete it:

- **From the media server only** keeps its Overture configuration, which a
  manual or scheduled sync can use to recreate the server collection.
- **From Overture and the media server** removes both.
- **Orphan** stops managing it and keeps it on the server.

Deleting filtered collections in Collection operations asks the same way. A
collection its group's set made leaves only with its set, so it offers neither
delete nor orphan. Collections Overture does not manage are never deleted.
Media files are always kept.

## Missing titles and requests

**Members** on a saved collection lists **Missing**, the titles its lists hold
that the library lacks, which **Request** sends to Radarr or Sonarr. Request
missing and where requested titles go are under **Settings > Collections**, in
the **Radarr and Sonarr** section. Overture tags every title Request missing
adds with `overture`, so Radarr and Sonarr show which titles it requested.

## Member tags and labels

A member tag is written as Radarr and Sonarr accept tags, in lowercase letters,
digits and dashes (`{title}` gives `star-wars-collection`); members get it and
other titles lose it, unless a collection whose tag comes out the same holds
them, so collections can share a tag. `overture` is not one.

On Plex, a **Member label** labels each member on the server, and Overture's
own `overture:` labels carry conditions Plex has no filter for; see
[Criteria](criteria.md#regular-and-smart-collections-on-plex).

## Bulk operations

**Collection operations** in the sidebar act on the filtered collections:
assign a group, adopt, orphan, delete, remove art or themes, and run Assets on
**Current sidebar items**. Only collections Overture manages are touched.
