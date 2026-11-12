---
sidebar_position: 7
title: OvertureDB
description: Using the community catalog in Overture, browsing it, and contributing back.
---

# OvertureDB in Overture

[OvertureDB](/overturedb) is a community catalog of hand-picked artwork sets
and themes. It is on by default: Overture downloads the catalog on its first
start and keeps it up to date. Turn it off under **Settings -> OvertureDB**,
which also hides its menu entry. It also carries imported ThemerrDB theme
choices. Catalog-only runs still download images and audio from their linked
sources; coverage and availability depend on those sources.

Overture reads version 3 of the catalog, which adds consistent collection
posters.

## Settings

**Settings -> OvertureDB** holds:

- **Enable OvertureDB**
- **Trust OvertureDB's No theme flag**, so a title the catalog marks as having
  no theme counts as theme-complete and theme runs skip it.
- **Browse OvertureDB in the sidebar**, which explains how browsing helps find
  gaps and mismatches and contribute them. Without browsing, the catalog
  switch and the links to OvertureDB entries are hidden, and an OvertureDB
  page that was open returns to the library.

The OvertureDB popup shows the catalog's status, collection and draft counts.

## Browsing the catalog

Flip the switch beside the logo down to browse the full local catalog,
including movies, shows and movie collections outside your library. Filter by
artwork, season posters, either theme source, local drafts or library
membership. Catalog links use TMDB, TVDB or IMDb identities, for example
`/overturedb/shows/tvdb-81189`.

Item, collection, season and member images in the OvertureDB view always use
the catalog, with drafts overriding it everywhere. Missing images show a
placeholder, even when TMDB or your library has artwork. TMDB still supplies
editing candidates, season details and collection membership. The Overture
icon opens a linked item or collection in your library.

## Drafts

Artwork and theme choices in this view become local drafts. They do not
change library selections or download files. Catalog pages share the library's
artwork, season and theme views, including status badges with clear buttons
on hover. Before a draft exists, artwork candidates come from TMDB. After you
make a draft, the OvertureDB section also offers the original catalog artwork.
Draft artwork and titles appear in the sidebar as well as on the page.

**Discard draft** restores the catalog entry. **No theme** in this view drafts
that a title has no theme music; once the catalog carries the flag, the next
OvertureDB sync brings it to your library.

## Contributing

Use the **OvertureDB Status** filter set to **Incomplete** to find titles that
still need selections, choose artwork and a theme, and contribute them:

- **Contribute issue** on a title, collection or OvertureDB draft opens its
  movie, show or collection form on GitHub filled in with its selections, and
  warns about anything the form needs from you.
- **OvertureDB -> Export selections** gathers all local drafts, library
  selections and matched collection themes into a ZIP to attach to a
  [bulk contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml).

Overture checks image formats, dimensions and links against the catalog
rules. OvertureDB takes themes 20 seconds to 10 minutes long, so contributions
leave out a chosen theme outside that and say why. Uploads cannot be
contributed, since the catalog takes public links only. Collection posters are
contributed as the kind the collection's
[OvertureDB posters](collections/art-and-themes.md#overturedb-posters) setting
names.

Review and submit the issue on GitHub; a maintainer approves it before it joins
the catalog. Imported ThemerrDB choices are maintained upstream in ThemerrDB.
See [Contribute to OvertureDB](/overturedb/contributing) and its
[selection guidelines](/overturedb/contributing/selection-guidelines).
