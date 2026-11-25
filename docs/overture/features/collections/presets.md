---
sidebar_position: 8
title: Presets, import and export
description: Starting collections from OvertureDB's presets, and moving collections between installs.
---

# Presets, import and export

## Starting from a preset

**Create** in the collection sidebar opens a new collection, whose **Setup**
starts with **Presets**. It lists every collection and set in the presets
OvertureDB publishes, such as Holidays, Decades, Franchises and TMDB charts,
grouped by category. Choosing one fills in the form as if you had typed it:

- A set chooses **One per value** and fills in what it splits by, its title
  template, its group and the group's defaults.
- A collection chooses **One collection** and fills in its title, group,
  criteria and settings.

Either starts in every library, on every server, that holds its media type.
Untick the libraries you do not want, change anything else, then **Save**. What
you save is an ordinary collection or set; nothing links it to the preset.

Below the choice, Overture names anything the preset needs that is not set up,
such as **Set TMDB_READ_ACCESS_TOKEN to use TMDB**. A preset that needs a newer
Overture is not listed.

Some presets give the group their collections join defaults of its own, such as
Holidays' Automatic art. Saving such a collection gives the group those
defaults wherever the group leaves a setting at **Default**; a setting the
group already has stays as it is.

## Exporting and importing

**Export**, the download icon on a group's or a collection's page, saves it as
a file; **Export as a file** under the Filters popup's collection operations
saves every collection the filters, search and open group match. A group brings
its set and the collections it holds that its set does not make. The file names media types instead of
libraries, so another install can use it: **Load file** beside **Presets**
adds the file's collections and sets to the list, under **From file**, and each
fills in the form as a preset does. A collection's art links come with it and
are chosen once it is saved.

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
