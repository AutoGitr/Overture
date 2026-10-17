# Support

## Getting help

Open a [GitHub issue](https://github.com/AutoGitr/Overture/issues/new/choose) for
bugs and suggestions. Report security problems as described in
[SECURITY.md](SECURITY.md).

## Supported releases

The latest minor release of the latest major version gets security and bug
fixes. Compatibility of settings, the database and the API is kept across minor
and patch releases.

## What is tested

| Area | Tested | Not supported |
| --- | --- | --- |
| Docker | Linux `amd64` and `arm64` images, started and exercised before each release | Kubernetes, Helm and Podman are untested |
| Native | x86_64 Linux with systemd ([requirements](README.md#install)), tested on Ubuntu 22.04 and 26.04, and Debian 12 and 13 | Windows, macOS, ARM, musl or no systemd |
| Media servers | Contract tests against pinned Plex, Jellyfin and Emby API specs, plus manual tests of current releases | One media server at a time |
| Browsers | Chromium on desktop and mobile | Firefox and Safari are best effort |
| Storage | Database on a local disk; media on disks or shares with locking and atomic renames | Two Overture instances on the same files |

TMDB, OvertureDB and YouTube are external services. Overture's handling of a
supported service is in scope; the service's own availability is not.
