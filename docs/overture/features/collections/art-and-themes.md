---
sidebar_position: 6
title: Art and themes
description: Automatic and generated collection art, OvertureDB posters and collection themes.
---

# Art and themes

Collection posters and backgrounds come from OvertureDB, TMDB, local-image
matching against the server's current image, your own uploads, or art Overture
generates from the title; they are uploaded to the media server. Collection themes
use OvertureDB and ThemerrDB in the configured order.

## Art generated from the title

Every collection's poster and background candidates end with a **Generated**
row, one image per style (dark, light and accent) showing its title under its
group's name. Choosing one keeps it in the image cache and uploads it like any
other art, and its source shows as **Generated**.

A poster always shows the title; a grouped collection's is offered under its
group and with the title alone, centred. A background never shows text, as the
media server draws the title over it. Art generated either way is generated again
when the collection's title or group changes.

## Automatic art

**Automatic art** in Settings (global, per group or per collection) decides
what a sync does for a slot no one chose:

- **Off**
- The best art of **OvertureDB**, **TMDB** (the franchise's art, or a listed
  person's photo), or **OvertureDB, then TMDB**, each optionally **else generate**
- **Generate**

The media server's own art is never taken. Generating makes a poster with the
title and a background without text, in the **Generated colours** (dark, light or
accent). A collection whose **Background** is **Not needed** gets no
background: its poster completes its art, as OvertureDB's No theme completes a
theme.

Collections whose criteria list a TMDB person offer that person's photos as
poster candidates.

## OvertureDB posters

**OvertureDB posters**, a collection setting (global, per group or per
collection), chooses which poster OvertureDB gives a TMDB collection:

- **Individual**, its own.
- **Consistent**, one in the layout every consistent poster shares, made with
  the [Coverlabs Silva designer](https://www.coverlabs.studio/designer/silva)
  and hosted on TMDB or ThePosterDB; a collection without a consistent poster
  then gets no OvertureDB poster.

Automatic art, exports and **Contribute issue** follow each collection's
choice, so posters you pick are contributed as the same kind; Consistent
leaves out a poster from any other source and says so. The catalog view
follows the global choice. See
[consistent collection posters](/overturedb/contributing/selection-guidelines#consistent-collection-posters)
in the OvertureDB guidelines.

## Uploaded art and Audit

Collection posters and backgrounds Overture uploaded show from its image cache
in the sidebar and on the collection's page, and **Audit** can compare them
with the server's and upload them again.

## Themes

A collection's automatic theme follows the **Automatic theme** setting, in the
same order of OvertureDB and ThemerrDB the Assets run uses. New collection IDs
imported by a full Sync also use the catalog theme order of an enabled
incremental schedule covering their library. On Jellyfin, BoxSet themes are
written to `JELLYFIN_COLLECTIONS_PATH`.

An inactive collection's art and theme can be chosen; the sync that puts it
back on the server sends them.
