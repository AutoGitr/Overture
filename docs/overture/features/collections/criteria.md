---
sidebar_position: 2
title: Criteria
description: Conditions, lists and TMDB facts, and who evaluates them.
---

# Criteria

**Criteria** decide a collection's members. A condition tests item metadata,
such as Genre is Action, Date added in the last 30 days or a TMDB, TVDB or IMDb
ID, or a list, offered under **Lists & tags**: a TMDB franchise, list, chart,
title list or person's credits, MDBList lists, or Radarr and Sonarr tags.
Conditions sit in groups that match **all** or **any** of them, and groups
nest.

## Values

Values are typed, with the library's most common values suggested first; a
TMDB keyword also suggests the keywords TMDB knows, so one no title has yet
can be used too. A TMDB person or franchise is one field: type a name and
search, then pick a result, whose ID takes its place, or type the ID.

Radarr tags and TMDB franchises are offered for movie collections only, Sonarr
tags for show collections only. TMDB title lists take IDs or links without any
key, and with `TMDB_API_KEY` can be searched by name, as MDBList lists can
with `MDBLIST_API_KEY`; each result picked is added to the condition. TMDB has
no list search, so TMDB lists take IDs or links. TMDB list and title
conditions take TMDB links as well as IDs.

MDBList conditions refuse franchise and official-list URLs
(`mdblist.com/franchises/...`, `mdblist.com/lists/official/...`) and say what
to use instead, since MDBList's API serves neither.

Listing the titles a collection's lists hold that its libraries lack needs
`TMDB_API_KEY`. Failed list lookups keep existing members.

## TMDB facts

With `TMDB_API_KEY`, a full Sync also stores what TMDB says about each title,
read again weekly: original language, origin country, TMDB rating and votes,
keywords, production companies, streaming services in the TMDB region, and for
shows their network, status and last air date. The same request fills in IMDb
and TVDB IDs the media server does not name. An incremental poll reads them
for the titles it adds.

## Copy and paste

Each condition and group can be duplicated, or copied and pasted into any
criteria that can test it: those of another library, collection or set, as
long as they offer its field and operator or its list. TMDB title IDs and
charts paste only into criteria of the same media type, since a movie's ID
names another show.

## In a collection

**In a collection** tests whether another collection Overture lists holds a
title, so **In a collection is false** makes a catch-all collection of
everything no other collection holds. A collection never counts itself, so a
catch-all keeps what it caught on its next sync, and **Preview members** of a
saved collection leaves it out too.

## Regular and smart collections on Plex

On Plex, **Collection type** chooses who evaluates the criteria:

- **Regular**, which Overture evaluates on each sync from the metadata, TMDB
  facts and lists it stored.
- **Smart**, a Plex smart collection Plex keeps current with every Plex filter,
  including languages, HDR, codecs and play state for each user.

Conditions Plex has no filter for, such as lists and tags, label the items they
match, such as `overture:tmdb_person:5292:actor`, so Plex can filter on the
labels. Fields Plex has no filter for, such as TMDB facts, original language
or folder, work the same way: Overture labels the items that match the
condition, such as `overture:field:original_language:is:ja`, and refreshes the
labels on each sync.

As the criteria are edited, the editor suggests the type that suits them:
Smart when Plex filters every condition natively, or when a filter only Plex
has needs it, and Regular when lists, tags, TMDB facts, an operator Plex lacks
or a custom order need it.

Jellyfin and Emby have no smart collections, so the choice is not shown there.

Imported Plex smart collections keep their Plex filter until you choose
**Replace the Plex filter with these criteria**.
