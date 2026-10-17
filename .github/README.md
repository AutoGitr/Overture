<!-- prettier-ignore -->
<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../frontend/public/brand/overture-logo-stacked-dark.svg" />
  <img src="../frontend/public/brand/overture-logo-stacked-light.svg" alt="Overture" width="260" />
</picture>

_Artwork and theme manager for Plex, Jellyfin and Emby_

[![Release](https://img.shields.io/github/v/release/AutoGitr/Overture?color=2ea44f&label=Release)](https://github.com/AutoGitr/Overture/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/AutoGitr/Overture/ci.yml?label=CI)](https://github.com/AutoGitr/Overture/actions)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Svelte](https://img.shields.io/badge/Svelte-FF3E00?logo=svelte&logoColor=white)](https://svelte.dev)
[![License](https://img.shields.io/badge/License-AGPL--3.0-337ab7)](../LICENSE)

[Features](#features) • [Using Overture](#using-overture) • [Install](#install) • [Configuration](#configuration) • [Authentication](#authentication) • [Maintenance](#maintenance) • [Contributing](#contributing)

</div>

Overture finds posters, backgrounds, season posters and theme songs for your
library and saves your choices as plain files next to your media. Plex, Jellyfin
and Emby all read those files, so your artwork and themes:

- **work on every server**, including several at once, and survive a reinstall, a switch and media upgrades;
- **are backed up with your media** by the backups you already run;
- **never put your media at risk**: Overture writes only its own artwork files
  and `theme.mp3`, and never creates folders or touches video, audio or subtitle
  files.

## Features

- **Best match first.** Your media server, TMDB and OvertureDB side by side,
  ranked by perceptual likeness to the file you already have. Hide images with
  the wrong aspect ratio or language, or paste any image link.
- **Any title, even unreleased.** Search TMDB for any movie, show or collection
  and choose its artwork and theme before it is in your library, or before it
  is out. Overture downloads them when a sync finds the folder.
- **Theme songs.** From OvertureDB, [ThemerrDB](https://github.com/LizardByte/ThemerrDB)
  or a YouTube search within the length you set, or paste a YouTube link.
  Preview in place and save as MP3 at an even loudness, for movies, shows and
  Plex collections.
- **[OvertureDB](https://github.com/AutoGitr/OvertureDB).** A community catalog
  of hand-picked artwork sets and themes. Share your choices for one title with
  a click, or for your whole library in one export.
- **A fast review flow.** Work through artwork, themes or both, item by item.
  Overture moves on after every save, skips what is complete and can stop
  monitoring finished items.
- **Hands-off libraries.** Fill whole libraries on demand or on a schedule, and
  give new media artwork and a theme as soon as it arrives.
- **Builds on what you have.** Sync reads the artwork and themes already on
  disk, and a source image identical to your file is adopted instead of
  downloaded again.
- **Clean-up and audit.** Rename stray files such as `folder.jpg`, and confirm
  that your server shows and plays what is on disk.
- **Coverage at a glance.** Status badges on every item, and statistics on
  artwork and theme coverage and storage.
- **Secure self-hosting.** Password or OpenID Connect sign-in, a non-root,
  read-only container and scheduled database backups.

## Using Overture

A **Sync** imports your movies and shows, and Plex collections with **Enable
Collections** on. The sidebar lists them with filters, search and sorting, and
badges mark each item as complete, partial or missing. An artwork slot is
complete when a choice is saved and its file exists; a show also needs a poster
for every season with videos.

Open an item to compare its candidates; saving a choice downloads it. To reach
a title outside your library, set the search field to **TMDB** (this needs
`TMDB_API_KEY`). A choice for a title without a folder is kept and downloaded by
the sync that finds the folder.

### Operations

Operations do the work in bulk for the libraries and folders you pick, and run
in the background, so you can close the browser; **Stop** keeps what has
finished.

| Operation | What it does                                                                                                                                                                                                                                                                                                          |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sync      | Imports libraries, IDs, folders, seasons and the artwork and themes already on disk. A full sync hides items the server no longer has; it never deletes files. An incremental sync only adds new items, and can fetch OvertureDB artwork and OvertureDB or ThemerrDB themes for them. Runs manually or on a schedule. |
| Assets    | Fills artwork and themes for monitored items, trying the sources you enable in your order: OvertureDB and a match for your local file for artwork; OvertureDB, ThemerrDB and a YouTube search for themes. Runs manually or on a schedule.                                                                             |
| Renamer   | Finds incorrectly named files such as `folder.jpg` and renames the ones you select.                                                                                                                                                                                                                                   |
| Audit     | Compares the artwork and themes on disk to what your media server actually shows and plays, refreshes the ones you select and checks again until the server shows them.                                                                                                                                               |

Assets never replaces a file with different content by default, and skips slots
that already have a saved choice:

| Saved choice | Local file | Default | Retry saved downloads     | Overwrite existing |
| ------------ | ---------- | ------- | ------------------------- | ------------------ |
| Yes          | Yes        | Skip    | Skip                      | Search again       |
| Yes          | No         | Skip    | Download the saved choice | Search again       |
| No           | Either     | Search  | Search                    | Search again       |

An existing theme file is kept unless Overwrite existing is on. A source image
identical to your file is adopted without downloading. **Skip recently checked**
skips anything searched within the chosen time.

**Schedules** use five-field cron in your time zone. Runs of one kind wait for
each other, and a full sync never overlaps Assets, Renamer or Audit.

### Files

Overture names files the way your `MEDIA_SERVER` expects. Images are `.jpg`,
`.jpeg` or `.png`; saving one format removes the others for that slot.

| File                                    | Plex                         | Jellyfin                     | Emby                         |
| --------------------------------------- | ---------------------------- | ---------------------------- | ---------------------------- |
| Poster                                  | `poster.jpg`                 | `poster.jpg`                 | `poster.jpg`                 |
| Background                              | `background.jpg`             | `background.jpg`             | `background.jpg`             |
| Season poster, in the season folder     | `Season01.jpg`               | `poster.jpg`                 | `poster.jpg`                 |
| Specials poster, in the specials folder | `season-specials-poster.jpg` | `season-specials-poster.jpg` | `season-specials-poster.jpg` |
| Theme song                              | `theme.mp3`                  | `theme.mp3`                  | `theme.mp3`                  |

### OvertureDB

Enable OvertureDB in the **OvertureDB** menu to use the catalog's
artwork and themes as sources.

To contribute one title, select the GitHub icon on its page, shown when your
choices differ from the catalog's. It opens a
[movie](https://github.com/AutoGitr/OvertureDB/issues/new?template=movie.yml) or
[show](https://github.com/AutoGitr/OvertureDB/issues/new?template=show.yml)
issue filled in with the title's IDs and your choices. For many titles, use
**OvertureDB -> Export selections** and attach the ZIP to a
[bulk contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml).

### REST API

The REST API is described in [`openapi/overture.json`](../openapi/overture.json)
and served at `/api/docs` for authenticated users.

## Install

Overture needs a running Plex, Jellyfin or Emby server and one folder per movie
and per show, with season subfolders:

```text
Movies/Inception (2010)/Inception (2010).mkv
Shows/Breaking Bad (2008)/Season 01/Breaking Bad - S01E01.mkv
```

<details open>
<summary><b>Docker</b> (Linux <code>amd64</code> and <code>arm64</code>)</summary>

1. Download [`compose.yaml`](../compose.yaml) and [`.env.example`](../.env.example),
   and rename `.env.example` to `.env`.
2. Configure your environment in `.env` (see [Configuration](#configuration)).
3. In `compose.yaml`, map your paths under volumes:

   ```yaml
   services:
      overture:
        volumes:
          - "./config:/config"
          # The container path must be the one your media server reports for your media.
          - "/path/to/media:/media"
   ```

   > [!IMPORTANT]
   > The container volume paths must match the exact paths your media server reports (for example, if Plex sees `/movies/Inception (2010)`, mount your movie directory to `/movies` in the container).

4. Create the config directory owned by the container user (`1000:1000` by default):

   ```sh
   mkdir -p config && sudo chown 1000:1000 config
   ```

5. When using password authentication (`AUTH_MODE=password` or `both`), generate a password hash and set `APP_PASSWORD_HASH` in `.env`:

   ```sh
   docker run --rm -it ghcr.io/autogitr/overture password hash
   ```

6. Start Overture and open `http://localhost:5885`:

   ```sh
   docker compose up -d
   ```

</details>

<details>
<summary><b>Linux service</b> (x86_64 with systemd)</summary>

The archive contains its own Python, web interface, FFmpeg and Deno, so
installing downloads nothing. It needs glibc 2.28 or newer, as in Debian 12+,
Ubuntu 22.04+, RHEL 8+, Fedora or Arch; the installer checks this.

1. Download the archive and its `.sha256` file from the
   [latest release](https://github.com/AutoGitr/Overture/releases/latest), then
   check and install it. Each archive also has a Sigstore bundle for
   `cosign verify-blob`.

   ```sh
   sha256sum --check overture-<version>-linux-x86_64.tar.gz.sha256
   tar -xzf overture-<version>-linux-x86_64.tar.gz
   sudo bash overture-<version>-linux-x86_64/install.sh
   ```

   Setup asks for your [media server](#connect-your-media-server), its key, the
   sign-in method and the address to listen on. The default, `127.0.0.1:5885`,
   is reachable only from this machine; choose `0.0.0.0` to open it to your
   network. To skip the questions, create `/etc/overture/overture.env` first.

2. The service runs as the `overture` user, which needs read and write access to
   your media. Add it to a group with `--media-group <group>` when installing,
   or use an ACL:

   ```sh
   sudo setfacl -R -m u:overture:rwX -m d:u:overture:rwX /srv/media
   ```

3. Manage it with `systemctl` and `journalctl -u overture`.
   `sudo -u overture overture check` tests settings, tools and permissions.

| Path                         | Contents                                        |
| ---------------------------- | ----------------------------------------------- |
| `/etc/overture/overture.env` | Settings, readable only by root and the service |
| `/var/lib/overture`          | Database, backups and caches                    |
| `/opt/overture/<version>`    | The installed and previous release              |

To uninstall, run `sudo bash /opt/overture/current/uninstall.sh`. This keeps your
settings, database, backups and the `overture` user. To remove them too, copy
any backups you want to keep and run `sudo rm -rf /etc/overture /var/lib/overture`
and `sudo userdel overture`.

</details>

### Connect your media server

<details>
<summary><b>Plex</b></summary>

1. Open any item in Plex Web, choose **Get Info -> View XML**, and copy the
   `X-Plex-Token` value from the address bar.
2. Set `MEDIA_SERVER=plex`, `MEDIA_SERVER_URL=http://<server>:32400` and
   `MEDIA_SERVER_API_KEY=<token>`.
3. In each library's **Advanced** settings, turn on **Use local assets**.

Overture follows Plex's secure `*.plex.direct` address when the server uses one.

</details>

<details>
<summary><b>Jellyfin</b></summary>

1. Create a key under **Dashboard -> API Keys**.
2. Set `MEDIA_SERVER=jellyfin`, `MEDIA_SERVER_URL=http://<server>:8096` and
   `MEDIA_SERVER_API_KEY=<key>`.
3. In each library, keep local images ahead of online image fetchers.

</details>

<details>
<summary><b>Emby</b></summary>

1. Create a key under **Dashboard -> Advanced -> API Keys**.
2. Set `MEDIA_SERVER=emby`, `MEDIA_SERVER_URL=http://<server>:8096` (include a
   base path such as `/emby` if you use one) and `MEDIA_SERVER_API_KEY=<key>`.
3. In each library, keep local images ahead of online image fetchers.

</details>

## Configuration

These variables set up the connection, sign-in and runtime; everything else is
set in the web interface. Docker reads them from `.env`, and the
[Linux service](#linux-service) from its settings file. Empty values count as
unset.

| Variable                  | Required           | Default                   | Description                                                                                                                |
| ------------------------- | ------------------ | ------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `MEDIA_SERVER`            | Yes                |                           | `plex`, `jellyfin` or `emby`                                                                                               |
| `MEDIA_SERVER_URL`        | Yes                |                           | Server address with protocol, port and any base path, without credentials                                                  |
| `MEDIA_SERVER_API_KEY`    | Yes                |                           | Server token or API key                                                                                                    |
| `MEDIA_SERVER_VERIFY_TLS` | No                 | `true`                    | Set to `false` when using https in the media server URL with a self-signed certificate                                     |
| `TMDB_API_KEY`            | No                 |                           | Enables TMDB artwork and title/collection search directly in the sidebar; recommended for Plex                             |
| `AUTH_MODE`               | No                 | `password`                | Authentication mode: `password`, `oidc`, `both`, or `none`                                                                 |
| `APP_PASSWORD_HASH`       | `password`, `both` |                           | [Password](#password) hash; required for `password` and `both` modes                                                       |
| `SESSION_EXPIRY_DAYS`     | No                 | `7`                       | How long a sign-in session lasts (in days)                                                                                 |
| `OIDC_ISSUER_URL`         | `oidc`, `both`     |                           | Exact [OIDC](#sso-with-openid-connect) issuer, with any path and trailing slash (Authentik: `.../application/o/overture/`) |
| `OIDC_CLIENT_ID`          | `oidc`, `both`     |                           | OIDC client ID                                                                                                             |
| `OIDC_CLIENT_SECRET`      | `oidc`, `both`     |                           | OIDC client secret                                                                                                         |
| `OIDC_DISPLAY_NAME`       | No                 | `Sign in with SSO`        | Sign-in button text, up to 80 characters                                                                                   |
| `OIDC_AUTO_LOGIN`         | No                 | `false`                   | Send visitors straight to the provider; `/?autologin=0` shows the login page                                               |
| `APP_URL`                 | `oidc`, `both`     |                           | The public origin behind a [reverse proxy](#reverse-proxy); required for OIDC                                              |
| `TRUSTED_PROXY_CIDRS`     | No                 |                           | Comma-separated proxy addresses or networks allowed to send `X-Forwarded-For`                                              |
| `TZ`                      | No                 | `UTC`                     | IANA time zone for logs and schedules                                                                                      |
| `LOG_LEVEL`               | No                 | `info`                    | `debug`, `info`, `warning`, `error` or `critical`                                                                          |
| `LOG_COLOUR`              | No                 | `true` (service: `false`) | Colour log lines; set `false` for plain text                                                                               |
| `PHASH_WORKERS`           | No                 | `1`                       | Image hashing processes (1-32); more use more memory                                                                       |
| `ART_DOWNLOAD_WORKERS`    | No                 | `1`                       | Parallel artwork downloads (1-16); keep low to avoid rate limits and to be nice                                            |
| `THEME_DOWNLOAD_WORKERS`  | No                 | `1`                       | Parallel theme downloads (1-16); keep low to avoid rate limits and to be nice                                              |

### Linux service

The service reads `/etc/overture/overture.env`. Edit it with `sudoedit` and
restart the service, or run `sudo overture setup` again while the service is
stopped (Enter keeps a saved secret). Variables set in the systemd unit
override the file; add them with `sudo systemctl edit overture`. The unit sets
`LOG_COLOUR=false`, since the journal stores plain text.

The service also has these additional variables:

| Variable               | Required | Default                      | Description                                                |
| ---------------------- | -------- | ---------------------------- | ---------------------------------------------------------- |
| `OVERTURE_HOST`        | No       | `127.0.0.1`                  | Listening address: an IP address or `localhost`            |
| `OVERTURE_PORT`        | No       | `5885`                       | Listening port                                             |
| `OVERTURE_CONFIG_DIR`  | No       | `/var/lib/overture`          | Database, backups and caches                               |
| `OVERTURE_CONFIG_FILE` | No       | `/etc/overture/overture.env` | Settings file; set it in the unit, or pass `--config-file` |

The Docker image sets its own address and config folder; change the published
port in `compose.yaml` instead.

## Authentication

Overture supports four authentication modes configured with `AUTH_MODE`:

| Mode                 | Login Form | SSO Button | Required Settings                                                    | Notes                                                               |
| -------------------- | ---------- | ---------- | -------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `password` (default) | Yes        | No         | `APP_PASSWORD_HASH`                                                  | Password sign-in form only                                          |
| `oidc`               | No         | Yes        | `APP_URL`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | OpenID Connect SSO only; supports `OIDC_AUTO_LOGIN`                 |
| `both`               | Yes        | Yes        | Password hash and OIDC credentials                                   | Password form with a secondary SSO button                           |
| `none`               | No         | No         | None                                                                 | Bypasses login entirely and hides logout UI; logs a startup warning |

> [!WARNING]
> Running with `AUTH_MODE=none` disables all authentication and leaves your instance open to anyone who can reach its port. Never expose an unprotected instance to the internet.

### Password

When `AUTH_MODE` is `password` or `both`, a password hash is required.

`overture password hash` asks for a password twice and prints a line such as
`APP_PASSWORD_HASH='$argon2id$...'`. Paste the whole line, quotes included, in
place of the old one. Any non-empty password up to 1,024 bytes works; use 15
characters or more. Hashes from other Argon2id tools also work.

```sh
docker run --rm -it ghcr.io/autogitr/overture password hash # Docker
```

```sh
overture password hash # Linux service
```

To read the password from a file or secret manager instead of a prompt, add
`--password-stdin` (and use `-i` instead of `-it` for Docker). Apply a new
password with `docker compose up -d --force-recreate` or
`sudo systemctl restart overture`; this signs out all password sessions.

### SSO with OpenID Connect

When `AUTH_MODE` is `oidc` or `both`, OIDC authentication is enabled.
Every signed-in user has full access, so limit who may use the client in your
identity provider.

1. Register a confidential web client using the authorization code flow with
   PKCE and `client_secret_basic`, scopes `openid profile email`, and these URIs:
   - Redirect: `https://overture.example.com/api/auth/oidc/callback`
   - Post-logout redirect: `https://overture.example.com/?autologin=0`
2. Set `APP_URL`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`,
   and optionally `OIDC_DISPLAY_NAME` and `OIDC_AUTO_LOGIN`.

The issuer, client ID and secret go together; a partial setup stops Overture
from starting.

### Reverse proxy

1. Set `APP_URL` to the exact public origin, such as `https://overture.example.com`.
2. Set `TRUSTED_PROXY_CIDRS` to the address the proxy connects from.
3. Pass WebSocket upgrades on `/ws` and keep the browser's `Origin` header.
4. Serve HTTP/2, so the browser loads many images at once.

Leave both settings empty when you open Overture directly on your network.

<details>
<summary><b>Caddy, Nginx and Traefik examples</b></summary>

```caddy
overture.example.com {
    reverse_proxy 127.0.0.1:5885
}
```

```nginx
server {
    listen 443 ssl http2;
    server_name overture.example.com;
    ssl_certificate /etc/letsencrypt/live/overture.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/overture.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5885;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 1d;
    }
}
```

```yaml
services:
  overture:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.overture.rule=Host(`overture.example.com`)"
      - "traefik.http.routers.overture.entrypoints=websecure"
      - "traefik.http.routers.overture.tls.certresolver=letsencrypt"
      - "traefik.http.services.overture.loadbalancer.server.port=5885"
```

</details>

### Docker secrets

Any setting can come from a
[Compose secret](https://docs.docker.com/compose/how-tos/use-secrets/) named after
it in lowercase. Leave the setting empty in `.env`.

```yaml
services:
  overture:
    secrets: [media_server_api_key]
secrets:
  media_server_api_key:
    file: ./secrets/media_server_api_key
```

## Maintenance

### Upgrade

Read the [release notes](https://github.com/AutoGitr/Overture/releases) first.

- **Docker:** run `docker compose pull && docker compose up -d`.
- **Linux service:** extract the new archive and run its `install.sh`. If the new
  version fails to start, the service stays stopped: read the journal, fix the
  cause and run the installer again. The previous version is kept.

The database upgrades on start, after a backup. An older version cannot open an
upgraded database, so to go back, restore that backup and run the old version:
its version tag in place of `latest` in `compose.yaml` for Docker, or
`sudo ln -sfn /opt/overture/<previous-version> /opt/overture/current` for the
service.

### Backup and restore

Backups go to `backups` in the config folder (`config/backups` for Docker,
`/var/lib/overture/backups` for the service), by schedule or from the **Backup**
menu. Overture also makes one before every database upgrade. They hold your
library and choices, not media files, so copy them off the host now and then.

To restore, stop Overture, copy a backup over `overture.db` and delete its
`-wal` and `-shm` files. Copy the current database first if you may need it.
Backups contain no sign-ins, so you sign in again.

```sh
# Docker
docker compose down
cp config/backups/overture_<time>.db config/overture.db
rm -f config/overture.db-wal config/overture.db-shm
docker compose up -d

# Linux service
sudo systemctl stop overture
cd /var/lib/overture
sudo -u overture cp backups/overture_<time>.db overture.db
sudo rm -f overture.db-wal overture.db-shm
sudo systemctl start overture
```

### Logs and health

`docker compose logs -f overture` or `journalctl -u overture -f` shows changes,
job progress and errors; set `LOG_LEVEL=debug` for more. Errors in the web
interface include a request ID that also appears in the log. `/api/health`
reports liveness and `/api/ready` returns 503 until Overture can serve requests.

### Troubleshooting

| Problem                            | Check                                                                      |
| ---------------------------------- | -------------------------------------------------------------------------- |
| Overture exits at start            | The log, required settings, and permissions                                |
| `/api/ready` returns 503           | Media server URL, key, certificate and network                             |
| Sign-in loops or live updates fail | `APP_URL`, proxy WebSocket setup, `TRUSTED_PROXY_CIDRS`                    |
| Library is empty                   | The media's path in the container matches the media server's               |
| Files cannot be written            | The container or `overture` user can write and rename in each media folder |
| The server shows old artwork       | Run Audit; check the server's local-assets setting                         |

Keep the database on a local disk. Media on a network share must support
locking and atomic renames. Never run multiple Overture instances on the same media
or config folder.
