---
sidebar_position: 8
title: Presets, import and export
description: Adding OvertureDB's ready-made collections, and moving collections between installs.
---

# Presets, import and export

**Presets** in the collection sidebar opens three tabs: OvertureDB's preset
gallery, importing a file, and exporting collections to one.

## Adding a preset

The **OvertureDB** tab lists the presets OvertureDB publishes, such as
Holidays, Decades, Franchises and TMDB charts. Each says what it holds and
which integration it needs that is not set up, such as **Needs tmdb**; a
preset that needs a newer Overture cannot be added until you upgrade.

**Add…** asks for a library of each media type the preset holds, and
**Preview** lists what adding it does:

- **Adds**: a group, set or collection it will create.
- **Skips**: a group of that name exists already; its settings stay as they
  are, and the preset's collections join it.
- **Cannot add**: something the chosen libraries or their servers refuse, such
  as a title one of them already has or a TMDB chart that does not exist for
  shows.

**Add** creates the groups and sets first, then the collections, each on its
own, so one that is refused leaves the rest added. A collection whose
starting art could not be set is added without it. Run a **Sync** to put the
new collections on the server.

Adding a preset copies it. The collections are yours: change them as you like.

## Newer versions

When OvertureDB changes a preset you added, the gallery marks it **Newer
version** and lists what changed, such as **Changes Christmas**, **Adds
Easter** or **Drops Halloween**. Nothing changes here until you choose
**Update…**, whose preview shows:

- **Updates**: a collection or group the preset added and has since changed.
  It takes the preset's new criteria and settings, replacing changes you made
  to them; it keeps its title, group and libraries, and its art.
- **Adds**: something new in the preset.
- **Skips**: what is unchanged, and what the preset no longer holds, which
  stays as it is.

Untick anything you would rather keep as it is; an update you skip, or one a
server refuses, is offered again with the next update. A collection you
deleted is added again only if you tick it.

## Exporting and importing

**Export** saves the groups and collections you choose as
`overture-collections.json`. A group brings its set and the collections it
holds that its set does not make. The file names media types instead of
libraries, so another install can add it from **Import file**, which works as
adding a preset does.

An export leaves out, and says why:

- collections that test folders or pick collections by ID, which only this
  install has;
- collections whose libraries of one media type have different criteria;
- collections a set makes, which come with their group instead;
- uploaded and generated art, which stays on this install.

It warns about collections that test labels another install may lack, or that
request missing titles or write labels or tags.

## Contributing a preset

After an export, the GitHub button beside it opens OvertureDB's preset form
with the file's details; attach the file there. See
[Presets](/overturedb/contributing/presets) in the OvertureDB guide for what a
preset may hold.
