---
sidebar_position: 2
title: Backup and restore
description: Scheduled and manual database backups, retention, and how to restore one.
---

# Backup and restore

Backups go to `backups` in the config folder (`config/backups` for Docker,
`/var/lib/overture/backups` for the service), by schedule or from the
**Backup** menu. Overture also makes one before every database upgrade. They
hold your library and choices; your media folders hold the files. Copy
backups off the host now and then.

## Retention

**Backups to keep** decides which backups stay: the latest few, plus the
newest backup of each recent day, week and month. Every backup, scheduled or
manual, applies it once it is written, and so does saving it, so a new backup
can leave the count unchanged when it replaces one the rules no longer keep.
**Back up now** names any backup it removed. Backups made before an upgrade
never remove others.

## Restore

To restore, stop Overture, copy a backup over `overture.db` and delete its
`-wal` and `-shm` files. Copy the current database first if you may need it.
Restoring signs everyone out.

```sh
# Docker
docker compose down
cp config/backups/overture_<time>.db config/overture.db
rm -f config/overture.db-wal config/overture.db-shm
docker compose up -d
```

```sh
# Linux service
sudo systemctl stop overture
cd /var/lib/overture
sudo -u overture cp backups/overture_<time>.db overture.db
sudo rm -f overture.db-wal overture.db-shm
sudo systemctl start overture
```

A backup made by a newer version opens only in that version or newer; see
[Upgrade](upgrade.md).
