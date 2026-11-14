---
sidebar_position: 3
title: Linux service
description: Install Overture as a systemd service from the self-contained archive.
---

# Linux service

For Linux `x86_64` with systemd.

The archive bundles its own Python, web interface, FFmpeg and Deno, so
installation runs offline. It needs glibc 2.28 or newer, as in Debian 12+,
Ubuntu 22.04+, RHEL 8+, Fedora or Arch; the installer checks this. Generated
collection art lays out Arabic and Hebrew titles with the system's FriBiDi
library (`libfribidi0` or `fribidi`), which most distributions install.

## Steps

1. Download the archive and its `.sha256` file from the
   [latest release](https://github.com/AutoGitr/Overture/releases/latest), then
   check and install it. Each archive also has a Sigstore bundle to
   [verify](../administration/verify-a-release.md) it with.

   ```sh
   sha256sum --check overture-<version>-linux-x86_64.tar.gz.sha256
   tar -xzf overture-<version>-linux-x86_64.tar.gz
   sudo bash overture-<version>-linux-x86_64/install.sh
   ```

   Setup asks for your [media server](media-servers.mdx), its key, the sign-in
   method and the address to listen on. The default, `127.0.0.1:5885`, is
   reachable only from this machine; choose `0.0.0.0` to open it to your
   network. To skip the questions, create `/etc/overture/overture.env` first.

2. The service runs as the `overture` user, which needs read and write access
   to your media. Add it to a group with `--media-group <group>` when
   installing, or use an ACL:

   ```sh
   sudo setfacl -R -m u:overture:rwX -m d:u:overture:rwX /srv/media
   ```

3. Open `http://localhost:5885` on the host, or use its network address if you
   changed the listening address. The installer enables and starts the service.

## Paths

| Path                         | Contents                                        |
| ---------------------------- | ----------------------------------------------- |
| `/etc/overture/overture.env` | Settings, readable only by root and the service |
| `/var/lib/overture`          | Database, backups and caches                    |
| `/opt/overture/<version>`    | The installed and previous release              |

## Settings file

The service reads `/etc/overture/overture.env`. Edit it with `sudoedit` and
restart the service, or run `sudo overture setup` again while the service is
stopped (Enter keeps a saved secret). Variables set in the systemd unit
override the file; add them with `sudo systemctl edit overture`. The unit sets
`LOG_COLOUR=false`, since the journal stores plain text.

Besides the [environment variables](environment-variables.md) every
installation reads, the service also reads these:

| Variable               | Required | Default                      | Description                                                |
| ---------------------- | -------- | ---------------------------- | ---------------------------------------------------------- |
| `OVERTURE_HOST`        | No       | `127.0.0.1`                  | Listening address: an IP address or `localhost`            |
| `OVERTURE_PORT`        | No       | `5885`                       | Listening port                                             |
| `OVERTURE_CONFIG_DIR`  | No       | `/var/lib/overture`          | Database, backups and caches                               |
| `OVERTURE_CONFIG_FILE` | No       | `/etc/overture/overture.env` | Settings file; set it in the unit, or pass `--config-file` |

## Managing the service

Use `systemctl` to start, stop or restart Overture, and `journalctl -u overture -f`
to follow its log. `sudo -u overture overture check` tests the configuration,
bundled tools and permissions. See [Logs and health](../administration/logs-and-health.md).
