---
sidebar_position: 1
title: Installation
description: Requirements and the two supported ways to run Overture.
---

# Installation

Choose [Docker](docker.md) or a native [Linux service](linux-service.md). Both
include the web interface and the tools needed to download artwork and themes.

## Requirements

Overture needs a running Plex, Jellyfin or Emby server and one folder per movie
and per show, with season subfolders:

```text
Movies/Inception (2010)/Inception (2010).mkv
Shows/Breaking Bad (2008)/Season 01/Breaking Bad - S01E01.mkv
```

The Overture process needs read and write access to those folders at the exact
paths your media server reports. Keep its database on a local disk; media on a
network share must support locking and atomic renames. Run only one Overture
instance against a given media or config folder.

Each media server also needs its library, metadata and collection
[settings](server-settings.mdx) set for Overture.

:::warning[Set up your media server first]

Without the [Media server settings](server-settings.mdx), a server keeps
showing the images it downloads itself and making its own collections, and
titles without TMDB or IMDb IDs get no OvertureDB artwork. Apply them before
the first sync.

:::

Overture can also run [without a media server](media-servers.mdx#no-media-server)
to curate OvertureDB alone.

## Steps

1. Install with [Docker](docker.md) or the [Linux service](linux-service.md).
2. [Connect your media server](media-servers.mdx) and apply its
   [settings](server-settings.mdx).
3. Set up [authentication](authentication.md), and a
   [reverse proxy](reverse-proxy.md) if you reach Overture over HTTPS.
4. Take the [first steps](../features/getting-started.md): sync the library and
   start choosing.

Every setting that is read at start is listed under
[Environment variables](environment-variables.md); everything else is set in the
web interface.

## What is tested

[Support](../support.md#what-is-tested) lists the platforms, media servers,
browsers and storage each release is tested on.
