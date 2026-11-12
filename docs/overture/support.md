---
sidebar_position: 6
title: Support
description: Where to get help, which releases get fixes, and how to report security problems.
---

# Support

## Getting help

Open a [GitHub issue](https://github.com/AutoGitr/Overture/issues/new/choose)
for bugs and suggestions, with your version, how Overture is installed, your
media server and browser, and redacted log lines around the problem. Leave out
API keys, password hashes and private URLs.

Catalog corrections, dead links and wrong IDs go to
[OvertureDB](/overturedb/contributing#changing-an-existing-entry) instead.

## Security

To report a vulnerability or security problem, create a new
[security advisory](https://github.com/AutoGitr/Overture/security/advisories/new)
rather than a public issue. Fixes ship in a new release of the latest version;
older versions are not patched.

## Supported releases

The latest minor release of the latest major version gets security and bug
fixes. Compatibility of settings, the database and the API is kept across
minor and patch releases.

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
