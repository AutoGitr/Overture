---
sidebar_position: 6
title: Uninstall
description: Removing Overture and what stays behind.
---

# Uninstall

**Docker:** run `docker compose down`. Your bind-mounted config and media
remain on disk.

**Linux service:** run `sudo bash /opt/overture/current/uninstall.sh`. This
keeps your settings, database, backups and the `overture` user. To remove them
too, copy any backups you want to keep and run
`sudo rm -rf /etc/overture /var/lib/overture` and `sudo userdel overture`.

The artwork and theme files Overture wrote beside your media are ordinary
files, named for your media server, and stay in place either way.
