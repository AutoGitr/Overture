---
sidebar_position: 1
title: Upgrade
description: Moving to a new release, and back again.
---

# Upgrade

Read the [changelog](../changelog.md) first; each
[release](https://github.com/AutoGitr/Overture/releases) carries its section.

- **Docker:** run `docker compose pull && docker compose up -d`.
- **Linux service:** extract the new archive and run its `install.sh`. If the
  new version fails to start, the service stays stopped: read the journal, fix
  the cause and run the installer again. The previous version is kept.

The database upgrades on start, after a
[backup](backup-and-restore.md). An upgraded database opens only in that
version or newer, so to go back, restore that backup and run the old version:
its version tag in place of `0` in `compose.yaml` for Docker, or
`sudo ln -sfn /opt/overture/<previous-version> /opt/overture/current` for the
service.

## Version lines

Overture follows [Semantic Versioning](https://semver.org/). Compatibility of
settings, the database and the API is kept across minor and patch releases; a
major release may change them, and says so in the changelog. The supplied
Compose file follows the `0` tag, which gets every update without a breaking
change. See [Support](../support.md) for which releases get fixes.
