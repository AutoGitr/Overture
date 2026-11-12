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

Overture can also run [without a media server](media-servers.mdx#no-media-server)
to curate OvertureDB alone.

## Steps

1. Install with [Docker](docker.md) or the [Linux service](linux-service.md).
2. [Connect your media server](media-servers.mdx).
3. Set up [authentication](authentication.md), and a
   [reverse proxy](reverse-proxy.md) if you reach Overture over HTTPS.
4. Take the [first steps](../features/getting-started.md): sync the library and
   start choosing.

Every setting that is read at start is listed under
[Environment variables](environment-variables.md); everything else is set in the
web interface.

## What is tested

| Area          | Tested                                                                                                 | Not supported                            |
| ------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------- |
| Docker        | Linux `amd64` and `arm64` images, started and exercised before each release                            | Kubernetes, Helm and Podman are untested |
| Native        | x86_64 Linux with systemd, tested on Ubuntu 22.04 and 26.04, and Debian 12 and 13                      | Windows, macOS, ARM, musl or no systemd  |
| Media servers | Contract tests against pinned Plex, Jellyfin and Emby API specs, plus manual tests of current releases | One media server at a time               |
| Browsers      | Chromium on desktop and mobile                                                                         | Firefox and Safari are best effort       |
| Storage       | Database on a local disk; media on disks or shares with locking and atomic renames                     | Two Overture instances on the same files |

TMDB, OvertureDB and YouTube are external services. Overture's handling of a
supported service is in scope; the service's own availability is not.
