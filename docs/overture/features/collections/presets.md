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
you save is an ordinary collection or set, yours to change; a set's collections
appear in Overture as soon as it is saved, as a collection does, and a sync puts
them on the server.

**Choose several** beside **Presets** lists them all with a box each instead;
**Add** saves every one you tick as choosing it alone and saving would, without
stopping at the form, and opens their group, or the collections when they join
several. One that cannot be saved, such as a collection whose title a library
already has, is named, and the rest are added.

Below the choice, Overture names anything the preset needs that is not set up,
such as **Set TMDB_READ_ACCESS_TOKEN to use TMDB**. A preset that needs a newer
Overture is not listed.

A preset says what its collections are: their criteria, titles, order, minimum
and active dates. How they are shown, their art and themes, and what they
request or label follow your own defaults and the group's, as for any
collection you make. Some presets give the group their collections join
defaults of its own, such as Holidays' active dates; saving such a collection
gives the group those defaults wherever the group leaves a setting at
**Default**, and a setting the group already has stays as it is.

## When OvertureDB changes a preset

Overture remembers the preset each collection and set came from, as OvertureDB
had it then. When OvertureDB changes it, the collection's or group's **Setup**
says what changed, such as **criteria** or **active dates**:

- **Take changes** applies just those parts. Whatever else you changed stays
  as you have it, and a set keeps its libraries.
- **Keep mine** leaves it as it is.

Either way, only OvertureDB's next change shows again. If OvertureDB stops
publishing the item, **Stop tracking** forgets where it came from; what you
saved stays. A collection or set made from a loaded file is not tracked.

## Exporting and importing

**Export**, the download icon on a group's or a collection's page, saves it as
a file; **Export as a file** under the Filters popup's collection operations
saves every collection the filters, search and open group match. A group brings
its set and the collections it holds that its set does not make. The file names
media types instead of libraries, so another install can use it: **Load file**
beside **Presets** adds the file's collections and sets to the list, under
**From file**, and each fills in the form as a preset does. A collection's art
links come with it and are chosen once it is saved.

The file is written as a preset is: only what each collection and set is,
as you chose it. A setting it inherits, and how it is shown, its art and themes,
requests and labels, stay behind for the install adding it to decide, so a
collection that only names its title, group and criteria reads as just that:

```json
{
  "title": "Christmas",
  "collection_group": "Holidays",
  "active_start_mmdd": "12-01",
  "active_end_mmdd": "12-26",
  "criteria": {
    "movie": {
      "conditions": [
        { "kind": "field", "field": "tmdb_keyword", "operator": "is", "value": "christmas" }
      ]
    }
  }
}
```

An export leaves out, and says why:

- collections that test folders or pick collections by ID, which only this
  install has;
- collections whose libraries of one media type have different criteria;
- collections a set makes, which come with their group instead;
- uploaded and generated art, which stays on this install.

It warns about collections that test labels another install may lack.

## Contributing a preset

After an export, the GitHub button beside it opens OvertureDB's preset form
with the file's details; attach the file there. See
[Presets](/overturedb/contributing/presets) in the OvertureDB guide for what a
preset may hold.
