<!-- prettier-ignore -->
<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/AutoGitr/Overture/main/frontend/public/brand/overture-logo-stacked-dark.svg" />
  <img src="https://raw.githubusercontent.com/AutoGitr/Overture/main/frontend/public/brand/overture-logo-stacked-light.svg" alt="Overture" width="260" />
</picture>

_Artwork, collections & themes for Plex, Jellyfin and Emby_

[![Release](https://img.shields.io/github/v/release/AutoGitr/Overture?color=2ea44f&label=Release)](https://github.com/AutoGitr/Overture/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/AutoGitr/Overture/ci.yml?label=CI)](https://github.com/AutoGitr/Overture/actions)
[![Python](https://img.shields.io/badge/Python-3.15-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Svelte](https://img.shields.io/badge/Svelte-5-FF3E00?logo=svelte&logoColor=white)](https://svelte.dev)
[![License](https://img.shields.io/badge/License-AGPL--3.0-337ab7)](https://github.com/AutoGitr/Overture/blob/main/LICENSE)

[Features](#features) &#9679; [Use cases](#use-cases) &#9679; [Installation](#installation) &#9679; [Using Overture](#using-overture) &#9679; [Maintenance](#maintenance) &#9679; [Contributing](#contributing)

</div>

Overture gives you complete control of your media library's look and sound.
Choose posters, backgrounds, season posters, and theme songs yourself, or let
scheduled runs handle it automatically by using
[OvertureDB](https://github.com/AutoGitr/OvertureDB).

Your choices are saved as ordinary files beside your media, ready to back up
together and keep through server reinstalls or switches. The artwork and theme
files are written into your existing media folders, named according to your
media server's asset naming scheme.

## Features

- **Artwork in one place.** Compare candidates from your media server, TMDB and
  OvertureDB, sorted by resolution and ranked by visual similarity to your existing
  selection. Filter by aspect ratio and language, or paste an image URL.
- **Themes with a preview.** Choose OvertureDB or
  [ThemerrDB](https://github.com/LizardByte/ThemerrDB) picks, search YouTube with
  a duration limit, or paste a YouTube link. Save as MP3 with optional loudness
  normalization.
- **Everything on one page.** The library, artwork, themes and every tool share
  a single page; no item, view, setting or operation is more than two clicks away.
- **Quick manual review.** Filter by missing artwork or themes, advance after
  saving, skip completed items and optionally stop monitoring them. Coverage
  and storage statistics show what still needs attention.
- **Automation you control.** Schedule library syncs and artwork or theme runs.
  Choose sources and their order, limit runs to selected libraries, and
  preserve saved choices by default.
- **Choose ahead of time.** Search TMDB for movies, shows and collections,
  including unreleased titles. Save choices now; Overture downloads them when
  a sync finds their media folders.
- **Keep the library tidy.** Use Renamer to standardize asset filenames and
  Audit to check whether your server displays and plays the files on disk.
- **Installable app.** Overture is a full progressive web app: install it from
  the browser on desktop or phone for its own window, with Movies and Shows
  shortcuts and updates applied automatically.

## Use cases

- **Hands-off libraries.** Schedule Sync and Assets with OvertureDB as the only
  artwork source and OvertureDB, ThemerrDB or both for themes. Let them import
  new media and fill gaps as the OvertureDB catalogs grow. Check in occasionally
  to run Renamer and Audit, and review the titles outside the catalogs.
- **Mix automation and personal choices.** Let the catalogs cover most of your
  library and override specific items with your own choices. Assets skips saved
  choices by default, so scheduled runs can fill gaps around your selections.
- **Curate everything yourself.** Keep automatic downloads off, choose artwork
  and themes item by item, and keep your selections private. Sync reads your
  existing local files; sharing to OvertureDB is always an explicit action.
- **Organize an existing collection.** Use local-image matching to identify the
  artwork you already have, Renamer to standardize filenames, and Audit to
  check that your server uses your local assets.
- **Contribute to OvertureDB.** Use the catalog coverage filters to find gaps,
  choose artwork and themes, and open prefilled contribution issues or export
  a batch. TMDB search lets you curate titles outside your library too; setup
  still needs a media server connection.

## Installation

Choose [Docker](#docker) or a native [Linux service](#linux-service). Both include
the web interface and the tools needed to download artwork and themes.

Overture needs a running Plex, Jellyfin or Emby server and one folder per movie
and per show, with season subfolders:

```text
Movies/Inception (2010)/Inception (2010).mkv
Shows/Breaking Bad (2008)/Season 01/Breaking Bad - S01E01.mkv
```

The Overture process needs read and write access to those folders at the exact
paths reported by your media server. Keep its database on a local disk; media
on a network share must support locking and atomic renames. Run only one
Overture instance against a given media or config folder.

### Docker

For Linux `amd64` and `arm64`. The image is `ghcr.io/autogitr/overture`, also
on Docker Hub as `autogitr/overture`. A tag such as `1.2.3` is one release,
`1.2` and `1` follow the newest release in that line, and `latest` follows the
newest release. The supplied Compose file uses `1`, which gets every update
without a breaking change.

1. Download [`compose.yaml`](https://github.com/AutoGitr/Overture/blob/main/compose.yaml).
2. Download [`.env.example`](https://github.com/AutoGitr/Overture/blob/main/.env.example), save it as `.env`, and configure your environment (see [Configuration](#configuration)).
3. In `compose.yaml`, map your paths under `volumes`. Each container path must
   match the path your media server reports: if Plex sees
   `/media/Movies/Inception (2010)`, mount the folder that holds `Movies` at
   `/media`.

   ```yaml
   services:
     overture:
       volumes:
         - "./config:/config"
         - "/path/to/media:/media"
   ```

4. Create the config directory owned by the container user (`1000:1000` by default),
   and give that user read and write access to your media folders. If you change
   `user:` in Compose, use the same UID and GID here:

   ```sh
   mkdir -p config && sudo chown 1000:1000 config
   ```

5. Set up [authentication](#authentication). The default is password sign-in;
   generate and save `APP_PASSWORD_HASH` as described under [Password](#password).

6. Start Overture and open `http://localhost:5885`:

   ```sh
   docker compose up -d
   ```

   The supplied Compose file binds to localhost. To access it from another
   machine, change the port mapping to `"5885:5885"` or configure a
   [reverse proxy](#reverse-proxy). Keep authentication enabled.

### Linux service

For Linux `x86_64` with systemd.

The archive bundles its own Python, web interface, FFmpeg and Deno, so
installation runs offline. It needs glibc 2.28 or newer, as in Debian 12+,
Ubuntu 22.04+, RHEL 8+, Fedora or Arch; the installer checks this.

1. Download the archive and its `.sha256` file from the
   [latest release](https://github.com/AutoGitr/Overture/releases/latest), then
   check and install it. Each archive also has a Sigstore bundle to
   [verify](#verify-a-release) it with.

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

3. Open `http://localhost:5885` on the host, or use its network address if you
   changed the listening address. The installer enables and starts the service.

| Path                         | Contents                                        |
| ---------------------------- | ----------------------------------------------- |
| `/etc/overture/overture.env` | Settings, readable only by root and the service |
| `/var/lib/overture`          | Database, backups and caches                    |
| `/opt/overture/<version>`    | The installed and previous release              |

### Connect your media server

<details>
<summary><b>Plex</b></summary>

1. Open any item in Plex Web, choose **Get Info -> View XML**, and copy the
   `X-Plex-Token` value from the address bar.
2. Set `MEDIA_SERVER=plex`, `MEDIA_SERVER_URL=https://<server-ip>:32400` and
   `MEDIA_SERVER_API_KEY=<token>`. Keep `MEDIA_SERVER_VERIFY_TLS=true`:
   Overture connects through Plex's verified `*.plex.direct` address, so every
   **Secure connections** setting works, including **Required**.
3. In each library's **Advanced** settings, turn on **Use local assets**.

If your router's DNS rebinding protection blocks `plex.direct`, allow that
domain.

</details>

<details>
<summary><b>Jellyfin</b></summary>

1. Create a key under **Dashboard -> API Keys**.
2. Set `MEDIA_SERVER=jellyfin`, `MEDIA_SERVER_URL=http://<server>:8096` and
   `MEDIA_SERVER_API_KEY=<key>`.
3. In each library, keep local images ahead of online image fetchers.

</details>

<details>
<summary><b>No media server</b></summary>

Set `MEDIA_SERVER=none` to curate OvertureDB without a media server; leave
`MEDIA_SERVER_URL` and `MEDIA_SERVER_API_KEY` unset. Sync, Audit and
Collections are hidden, the sidebar opens on OvertureDB, and nothing reports
the server as down.

| Feature                                       | With `TMDB_API_KEY` | Without |
| --------------------------------------------- | ------------------- | ------- |
| Browse the catalog, drafts, export and issues | Yes                 | Yes     |
| Pasted art URLs and YouTube theme search      | Yes                 | Yes     |
| TMDB art candidates and TMDB-only titles      | Yes                 | No      |

</details>

<details>
<summary><b>Emby</b></summary>

1. Create a key under **Dashboard -> Advanced -> API Keys**.
2. Set `MEDIA_SERVER=emby`, `MEDIA_SERVER_URL=http://<server>:8096` (include a
   base path such as `/emby` if you use one) and `MEDIA_SERVER_API_KEY=<key>`.
3. In each library, keep local images ahead of online image fetchers.

</details>

### Configuration

These variables set up the connection, sign-in and runtime; everything else is
set in the web interface. Docker reads them from `.env` or
[Docker secrets](#docker-secrets), and the [Linux service](#linux-service) from
its [settings file](#native-service-settings). Empty values count as unset.

<details>
<summary><b>Environment variable reference</b></summary>

| Variable                    | Required           | Default                   | Description                                                                                                                 |
| --------------------------- | ------------------ | ------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `MEDIA_SERVER`              | Yes                |                           | `plex`, `jellyfin`, `emby` or `none`                                                                                        |
| `MEDIA_SERVER_URL`          | Unless `none`      |                           | Server address with protocol, port and any base path.                                                                       |
| `MEDIA_SERVER_API_KEY`      | Unless `none`      |                           | Server token or API key                                                                                                     |
| `MEDIA_SERVER_VERIFY_TLS`   | No                 | `true`                    | Set to `false` only for a self-signed certificate; keep it on for Plex                                                      |
| `JELLYFIN_COLLECTIONS_PATH` | No                 |                           | Local mount of Jellyfin's collections directory, used to write BoxSet themes                                                |
| `MDBLIST_API_KEY`           | No                 |                           | Enables dynamic collection membership from MDBList JSON lists; kept on the backend                                          |
| `TMDB_API_KEY`              | No                 |                           | Enables TMDB artwork and title/collection search directly in the sidebar; recommended for Plex                              |
| `RADARR_URL`                | No                 |                           | Radarr server URL with protocol, port and base path (e.g. `http://192.0.2.10:7878`); enables Radarr tag collection builders |
| `RADARR_API_KEY`            | If using Radarr    |                           | Radarr API key; kept on the backend                                                                                         |
| `RADARR_VERIFY_TLS`         | No                 | `true`                    | Set to `false` only for self-signed certificates                                                                            |
| `SONARR_URL`                | No                 |                           | Sonarr server URL with protocol, port and base path (e.g. `http://192.0.2.10:8989`); enables Sonarr tag collection builders |
| `SONARR_API_KEY`            | If using Sonarr    |                           | Sonarr API key; kept on the backend                                                                                         |
| `SONARR_VERIFY_TLS`         | No                 | `true`                    | Set to `false` only for self-signed certificates                                                                            |
| `AUTH_MODE`                 | No                 | `password`                | Authentication mode: `password`, `oidc`, `both`, or `none`                                                                  |
| `APP_PASSWORD_HASH`         | `password`, `both` |                           | [Password](#password) hash; required for `password` and `both` modes                                                        |
| `OIDC_ISSUER_URL`           | `oidc`, `both`     |                           | Exact [OIDC](#sso-with-openid-connect) issuer, with any path and trailing slash (Authentik: `.../application/o/overture/`)  |
| `OIDC_CLIENT_ID`            | `oidc`, `both`     |                           | OIDC client ID                                                                                                              |
| `OIDC_CLIENT_SECRET`        | `oidc`, `both`     |                           | OIDC client secret                                                                                                          |
| `OIDC_DISPLAY_NAME`         | No                 | `Sign in with SSO`        | Sign-in button text, up to 80 characters                                                                                    |
| `OIDC_AUTO_LOGIN`           | No                 | `false`                   | Send visitors straight to the provider; `/login?autologin=0` opens the login page                                           |
| `APP_URL`                   | `oidc`, `both`     |                           | The public origin behind a [reverse proxy](#reverse-proxy); required for OIDC                                               |
| `SESSION_EXPIRY_DAYS`       | No                 | `7`                       | How long a sign-in session lasts (in days)                                                                                  |
| `TRUSTED_PROXY_CIDRS`       | No                 |                           | Comma-separated proxy addresses or networks allowed to send `X-Forwarded-For`                                               |
| `TZ`                        | No                 | `UTC`                     | IANA time zone for logs and schedules                                                                                       |
| `LOG_LEVEL`                 | No                 | `info`                    | `debug`, `info`, `warning`, `error` or `critical`                                                                           |
| `LOG_COLOUR`                | No                 | `true` (service: `false`) | Colour log lines; set `false` for plain text                                                                                |
| `PHASH_WORKERS`             | No                 | `1`                       | Image hashing processes (1-32); more use more memory, and more than the CPU count gains nothing                             |
| `ART_DOWNLOAD_WORKERS`      | No                 | `1`                       | Parallel artwork downloads (1-10); keep low to avoid rate limits and to be nice                                             |
| `THEME_DOWNLOAD_WORKERS`    | No                 | `1`                       | Parallel theme downloads (1-4); YouTube blocks addresses that download too fast                                             |

</details>

#### Docker secrets

Any setting can come from a
[Compose secret](https://docs.docker.com/compose/how-tos/use-secrets/) named after
it in lowercase. Leave the setting empty in `.env`.
Overture validates required settings after loading the mounted secrets.

```yaml
services:
  overture:
    secrets: [media_server_api_key]
secrets:
  media_server_api_key:
    file: ./secrets/media_server_api_key
```

#### Native service settings

The service reads `/etc/overture/overture.env`. Edit it with `sudoedit` and
restart the service, or run `sudo overture setup` again while the service is
stopped (Enter keeps a saved secret). Variables set in the systemd unit
override the file; add them with `sudo systemctl edit overture`. The unit sets
`LOG_COLOUR=false`, since the journal stores plain text.

The service also reads these variables:

| Variable               | Required | Default                      | Description                                                |
| ---------------------- | -------- | ---------------------------- | ---------------------------------------------------------- |
| `OVERTURE_HOST`        | No       | `127.0.0.1`                  | Listening address: an IP address or `localhost`            |
| `OVERTURE_PORT`        | No       | `5885`                       | Listening port                                             |
| `OVERTURE_CONFIG_DIR`  | No       | `/var/lib/overture`          | Database, backups and caches                               |
| `OVERTURE_CONFIG_FILE` | No       | `/etc/overture/overture.env` | Settings file; set it in the unit, or pass `--config-file` |

The Docker image sets its own address and config folder; change the published
port in `compose.yaml` instead.

### Authentication

Choose sign-in with `AUTH_MODE`:

| Mode                 | Sign-in            | Required settings                                                    |
| -------------------- | ------------------ | -------------------------------------------------------------------- |
| `password` (default) | Password           | `APP_PASSWORD_HASH`                                                  |
| `oidc`               | OpenID Connect SSO | `APP_URL`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` |
| `both`               | Password or SSO    | Both sets above                                                      |
| `none`               | Open access        |                                                                      |

> [!WARNING]
> `AUTH_MODE=none` opens your instance to anyone who can reach its port. Use it only on a trusted network or behind a proxy that handles sign-in. Never expose an unprotected instance to the internet.

#### Password

When `AUTH_MODE` is `password` or `both`, a password hash is required.

`overture password hash` asks for a password twice and prints a line such as
`APP_PASSWORD_HASH='$argon2id$...'`. In `.env` or `overture.env`, paste the
whole line, quotes included, in place of the old one. Any
non-empty password up to 1,024 bytes works; use 15 characters or more. Hashes
from other Argon2id tools also work.

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

#### SSO with OpenID Connect

When `AUTH_MODE` is `oidc` or `both`, OIDC authentication is enabled.
Every signed-in user has full access, so limit who may use Overture in your
identity provider.

1. Register a confidential web client using the authorization code flow with
   PKCE and `client_secret_basic`, scopes `openid profile email`, and these URIs:
   - Redirect: `https://overture.example.com/api/auth/oidc/callback`
   - Post-logout redirect: `https://overture.example.com/login?autologin=0`
2. Set `APP_URL`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`,
   and optionally `OIDC_DISPLAY_NAME` and `OIDC_AUTO_LOGIN`.

Set the issuer, client ID and secret together; Overture starts only with all
three.

### Reverse proxy

1. Set `APP_URL` to the exact public origin, such as `https://overture.example.com`.
2. Set `TRUSTED_PROXY_CIDRS` to the address the proxy connects from.
3. Pass WebSocket upgrades on `/ws` and keep the browser's `Origin` header.
4. Serve HTTP/2, so the browser loads many images at once.

For direct HTTP access with password sign-in, leave `APP_URL` and
`TRUSTED_PROXY_CIDRS` empty. OIDC still requires `APP_URL` and HTTPS, except
on loopback.

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

## Using Overture

1. Run a full **Sync** to import movies, shows and your Plex, Jellyfin or Emby collections.
   Collections and their members refresh when Collections is selected for a full sync.
2. Enable [OvertureDB](#overturedb) if you want community picks, then open an
   item to compare artwork and preview themes. Saving a choice downloads it.
3. Work through items manually, run **Assets** in bulk, or save schedules for
   Sync and Assets. Select the libraries, sources and replacement options you
   want each run to use.

The sidebar offers search, sorting and completeness filters. An artwork slot
is complete when a choice is saved and its file exists; a show also needs a
poster for every season with videos.

For titles outside your library, switch the search field to **TMDB** (requires
`TMDB_API_KEY`). Choices for these titles are saved and downloaded when a sync
finds their media folder.

To install Overture as an app, open it in Chrome, Edge or Safari and choose
**Install** in the address bar (on iOS: **Share > Add to Home Screen**).
Browsers offer this only over HTTPS, so serve Overture through a
[reverse proxy](#reverse-proxy) with a certificate, or open it on `localhost`.

### Collections

Plex, Jellyfin and Emby collections appear under **Collections** in the library
sidebar. **+ Create collection** opens a Configure page, the one place to create
anything: **One collection**, or **One per value** (a collection set), from
scratch, from a preset or from a preset you saved, under **Start from**.

Both kinds share the same sections, in the same order:

1. **Setup**: the libraries, the preset, what to create, the title (a set's
   title template, where `{value}s` turns 1990 into 1990s) and the group. One
   collection in several libraries becomes a set with that collection in each,
   kept alike. **Save as preset** keeps the form for later.
2. **Content**: whether members are chosen by hand or by criteria, who
   evaluates them, and the criteria, with **Preview members**. A set instead
   chooses what it **Splits by**, its values and the conditions every
   collection needs, with **Preview collections**.
3. **Members** (a saved collection): its members, and **Missing**, the titles
   its lists hold that the library lacks, which **Request** sends to Radarr or
   Sonarr.
4. **Settings**: sort and limit, Sync mode (Sync removes members that stop
   matching, Append keeps them), minimum, automatic art and theme, Request
   missing, Member label, Radarr or Sonarr tag, Plex's collection mode,
   filtering, Home and recommended promotion and Home order, sort title and
   summary templates, and the TMDB collection ID.
5. **Schedule**: Scheduled sync, the sync schedule (a cron expression with
   presets), the active dates, which repeat yearly and can cross New Year, and
   whether an inactive collection leaves the server.

A group's settings in **Collection groups** and the global defaults under
**Settings > Collection defaults** use the same fields and names. **Default**
inherits, from the group and then the global default, and names the value it
inherits. A group can hold regular and smart collections; a custom order applies
to its regular ones only.

Collections made outside Overture, without criteria, are also listed under the
virtual **Unmanaged** group. **Take over all** there, or **Take over** in Bulk
operations, gives each criteria that keep what it holds today: a regular
collection keeps its members, and a Plex smart collection keeps its filter when
every Plex filter has an equivalent condition. Otherwise Overture lists the
filters it cannot read; edit the criteria and choose **Replace the Plex filter
with these criteria**. Saving criteria on an unmanaged collection also takes it
over. `Unmanaged` cannot name a group. Turn on **Require a group for every
managed collection** under **Settings > Collection defaults** to keep every
managed collection in one.

**Criteria** decide a collection's members. A condition tests item metadata,
such as Genre is Action or Date added in the last 30 days, or a list: a TMDB
franchise, list, chart, titles or person's credits, MDBList lists, or Radarr and
Sonarr tags. Conditions sit in groups that match **all** or **any** of them, and
groups nest. With `TMDB_API_KEY`, Full Sync also stores what TMDB says about
each title, read again weekly: original language, origin country, TMDB rating
and votes, keywords, production companies, streaming services in the TMDB
region, and for shows their network, status and last air date. Values are
suggested from the library, and TMDB people and franchises can be searched.

On Plex, **Evaluated by** chooses Overture, which tests the metadata the last
sync stored, or **Plex (smart)**, a Plex smart collection Plex keeps current
with every Plex filter, including languages, HDR, codecs and play state for
each user. Lists in smart criteria become labels Overture keeps on their items,
such as `overture:tmdb_person:5292:actor`. TMDB facts are tested by Overture
only.

A **collection set** creates one collection per value in its libraries: each
decade, year, genre, studio, network, country, origin country, original
language, streaming service, content rating, resolution, edition, label, actor,
director, writer or producer, or TMDB franchise; on Plex smart sets also each
audio or subtitle language. A **custom** set lists its collections, each with
its own criteria, such as A to Z or Based on a book. Sets can keep the most
common values, include or skip values, remove text from names, and rename or
merge values. Values below the minimum are removed when **Below minimum**
deletes, and collections whose value disappears when the set says so. A set's
collections take their criteria and titles from the set; edit it in
**Collection groups**. A set runs on its schedule once it has been synced.

**Save** (or Enter) saves in Overture only and never changes the media server.
**Save and Create** saves and creates the collection or set on the server;
**Save and Sync** saves an existing collection and makes the server match it,
then picks art and themes, labels and tags members, requests missing titles and
orders Home rows as its settings say. Members you add, remove or reorder also
wait for the next sync. A collection with changes the server does not have
shows **Unsynced**, and a library sync keeps those changes.

Summary templates take `{title}`, `{group}`, `{start_date}`, `{end_date}`,
`{summary}` (the server's) and `{source_summary}`, the description of the first
list or a person's biography. Collections whose criteria list a TMDB person
offer that person's photos as poster candidates.

Set `TMDB_API_KEY` for TMDB lists, charts, titles, people, franchises and facts,
`MDBLIST_API_KEY` for MDBList, and the Radarr or Sonarr URL and API key for
their tags, requests and member tags. Choose where requested titles go under
**Settings > Collection defaults**. Imported Plex smart collections keep their
Plex filter until you choose **Replace the Plex filter with these criteria**.
Failed list lookups keep existing members.

**Collection groups**, opened from **Groups** in the collection sidebar or
**Create new group** in Setup's Group list, creates groups and edits a group's
collection set, Settings and Schedule; Setup only assigns a group. **Save**
takes effect on the next sync, **Save and Apply** sends display settings to the
server at once while keeping members and explicit overrides, and **Save and
Sync** runs the set and syncs the group's collections. A group can be renamed
or deleted; deleting can keep its collections or remove them from Overture, the
media server or both. Media files are always kept.

### Operations

Operations do the work in bulk for the libraries and folders you pick, and run
in the background, so you can close the browser; **Stop** keeps what has
finished.

| Operation | What it does                                                                                                                                 |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Sync      | Imports library items, folders, seasons and existing local assets. Full sync also hides items removed from the server and keeps their files. |
| Assets    | Fills artwork and themes for monitored items using your chosen sources and order. Runs manually or on a schedule.                            |
| Renamer   | Finds nonstandard asset filenames such as `folder.jpg` and renames the ones you select.                                                      |
| Audit     | Compares local assets with the server, refreshes selected differences and checks whether the changes took effect.                            |

Sync schedules can run a full reconciliation or poll for newly added media
(**incremental**). Incremental schedules can also fetch OvertureDB artwork and
OvertureDB or ThemerrDB themes for new items. Run a full Sync first to import
your existing library.

Assets can use OvertureDB and local-image matching for artwork; theme sources
are OvertureDB, ThemerrDB and YouTube search. Local-image matching finds a source
for artwork already on disk. The library checklist in **Assets** and full **Sync**
includes a single **Collections** checkbox below Movies and Shows. In Sync it
refreshes collection metadata and memberships for the selected libraries; pick a
collection group under **Collections** to sync only that group. In Assets it
fills collection themes in those libraries. Switch Assets to **Collections** to
run art and themes over every collection or the groups you tick, now or on a
schedule, or use **Current sidebar items** from the collection list to target
its filtered rows. Collection posters and backgrounds come from OvertureDB, or
local-image matching against the server's current image, and are uploaded to the
media server. Collection themes use OvertureDB and ThemerrDB in the configured
order; YouTube search applies to movies and shows.
New collection IDs imported by a full Sync also use the catalog theme order of
an enabled incremental schedule covering their library.

<details>
<summary><b>How Assets treats existing choices and files</b></summary>

By default, Assets keeps every existing file and skips slots that already have
a saved choice, downloading the saved choice again when its file is missing:

| Saved choice | Local file | Default                   | Replace existing |
| ------------ | ---------- | ------------------------- | ---------------- |
| Yes          | Yes        | Skip                      | Search again     |
| Yes          | No         | Download the saved choice | Search again     |
| No           | Either     | Search                    | Search again     |

Saved choices include the artwork URLs Sync copies from your media server, so
a run downloads those to the media folder when no local file exists yet.
Assets knows a file is missing from what Overture last recorded on disk; a file
deleted outside Overture is noticed after a Renamer scan or an Audit.

**Replace existing** also replaces existing theme files; a downloaded file
identical to yours is left untouched. A source image identical to your file is
adopted in place. Local-image matching defaults to identical files; a looser
matching threshold can replace unsaved local artwork with a similar image.

**Skip recently checked** skips searches within the chosen time window, also
with Replace existing. Restoring a missing saved choice always runs.

</details>

**Schedules** use five-field cron in your time zone. One operation runs at a
time: Sync, Assets, Renamer and Audit each wait for whichever is running, and a
scheduled run waits its turn. A full sync also waits for queued downloads, and
downloads wait while a full sync runs.

### Files

Overture names files the way your `MEDIA_SERVER` expects. Images are `.jpg`,
`.jpeg` or `.png`; saving one format removes the others for that slot.

| File                                    | Plex                         | Jellyfin                     | Emby                         |
| --------------------------------------- | ---------------------------- | ---------------------------- | ---------------------------- |
| Poster                                  | `poster.jpg`                 | `poster.jpg`                 | `poster.jpg`                 |
| Background                              | `background.jpg`             | `background.jpg`             | `background.jpg`             |
| Season poster, in the season folder     | **`Season01.jpg`**           | `poster.jpg`                 | `poster.jpg`                 |
| Specials poster, in the specials folder | `season-specials-poster.jpg` | `season-specials-poster.jpg` | `season-specials-poster.jpg` |
| Theme song                              | `theme.mp3`                  | `theme.mp3`                  | `theme.mp3`                  |

### OvertureDB

OvertureDB is a community catalog of hand-picked artwork sets and themes.
Enable it in the **OvertureDB** menu to download the catalog and keep it up to
date. It also carries imported ThemerrDB theme choices. Catalog-only runs still
download images and audio from their linked sources; coverage and availability
depend on those sources.

Use **Library | OvertureDB** above the sidebar tabs to browse the full local
catalog, including movies, shows and movie collections outside your library.
Filter by artwork, season posters, either theme source, local drafts or library
membership. Catalog links use TMDB, TVDB or IMDb identities, for example
`/overturedb/shows/tvdb-81189`.

Artwork and theme choices in this view become local drafts. They do not change
library selections or download files. Catalog pages share the library's artwork,
season and theme views, including status badges with clear buttons on hover.
Before a draft exists, artwork candidates come from TMDB. After you make a
draft, the OvertureDB section also offers the original catalog artwork.
Draft artwork and titles appear in the sidebar as well as on the page.
Item, collection, season and member images in the OvertureDB view always use
the catalog, with drafts overriding it everywhere. Missing images show a
placeholder, even when TMDB or your library has artwork. TMDB still supplies
editing candidates, season details and collection membership.
**Discard draft** restores the catalog entry; the Overture icon opens a linked
item or collection in your library. The GitHub icon appears when a draft differs
from the catalog and opens an issue with those choices. **Export selections** includes
all local drafts along with library selections and matched collection themes.
The OvertureDB popup shows collection and draft counts.

To contribute one title, select the GitHub icon on its page, shown when your
choices differ from the catalog's. It opens a
[movie](https://github.com/AutoGitr/OvertureDB/issues/new?template=movie.yml) or
[show](https://github.com/AutoGitr/OvertureDB/issues/new?template=show.yml), or
[collection](https://github.com/AutoGitr/OvertureDB/issues/new?template=collection.yml)
issue filled in with the title's IDs and your choices. For many titles, use
**OvertureDB -> Export selections** and attach the ZIP to a
[bulk contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml).

Review and submit the issue on GitHub; a maintainer approves it before it joins
the catalog. Imported ThemerrDB choices are maintained upstream in ThemerrDB.

### REST API

The REST API is described in [`openapi/overture.json`](https://github.com/AutoGitr/Overture/blob/main/openapi/overture.json)
and served at `/api/docs` for authenticated users.

Required JSON request bodies reject `null`. To stop all bulk asset jobs,
`POST /api/bulk/assets/stop` accepts an omitted body, `null`, or `{}`.

## Maintenance

### Upgrade

Read the [changelog](https://github.com/AutoGitr/Overture/blob/main/.github/CHANGELOG.md)
first; each [release](https://github.com/AutoGitr/Overture/releases) carries its
section.

- **Docker:** run `docker compose pull && docker compose up -d`.
- **Linux service:** extract the new archive and run its `install.sh`. If the new
  version fails to start, the service stays stopped: read the journal, fix the
  cause and run the installer again. The previous version is kept.

The database upgrades on start, after a [backup](#backup-and-restore). An
upgraded database opens only in that version or newer, so to go back, restore
that backup and run the old version: its version tag in place of `1` in
`compose.yaml` for Docker, or
`sudo ln -sfn /opt/overture/<previous-version> /opt/overture/current` for the
service.

### Verify a release

Each release is signed by its GitHub workflow with Sigstore. Check an image
with [cosign](https://docs.sigstore.dev/cosign/system_config/installation/) 3.1
or newer before you run it, and the native archive before you install it:

```sh
IDENTITY='^https://github.com/AutoGitr/Overture/\.github/workflows/release\.yml@refs/(tags/v.+|heads/main)$'
ISSUER=https://token.actions.githubusercontent.com

# GHCR keeps the signatures in a package of their own.
COSIGN_REPOSITORY=ghcr.io/autogitr/overture-signatures cosign verify \
  ghcr.io/autogitr/overture:<version> \
  --certificate-identity-regexp "$IDENTITY" --certificate-oidc-issuer "$ISSUER"
cosign verify docker.io/autogitr/overture:<version> \
  --certificate-identity-regexp "$IDENTITY" --certificate-oidc-issuer "$ISSUER"

cosign verify-blob overture-<version>-linux-x86_64.tar.gz \
  --bundle overture-<version>-linux-x86_64.tar.gz.sigstore.json \
  --certificate-identity-regexp "$IDENTITY" --certificate-oidc-issuer "$ISSUER"

# Every file attached to the release
gh release verify v<version> --repo AutoGitr/Overture
```

The release notes list the image digest. The image
carries its SPDX SBOM and build provenance, and the SBOMs are also attached to
the release.

### Backup and restore

Backups go to `backups` in the config folder (`config/backups` for Docker,
`/var/lib/overture/backups` for the service), by schedule or from the **Backup**
menu. Overture also makes one before every database upgrade. They hold your
library and choices; your media folders hold the files. Copy backups off the
host now and then.

To restore, stop Overture, copy a backup over `overture.db` and delete its
`-wal` and `-shm` files. Copy the current database first if you may need it.
Restoring signs everyone out.

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

For the Linux service, use `systemctl` to start, stop or restart Overture.
`sudo -u overture overture check` tests configuration, bundled tools and
permissions.

### Troubleshooting

| Problem                            | Check                                                                                                     |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Overture exits at start            | The log, required settings, and permissions                                                               |
| `/api/ready` returns 503           | Failed checks in its response, then the logs; readiness covers the database, tools and background workers |
| Sign-in loops or live updates fail | `APP_URL`, proxy WebSocket setup, `TRUSTED_PROXY_CIDRS`                                                   |
| Library is empty                   | Run Sync; check the media server connection, selected libraries and matching media paths                  |
| Saving files fails                 | The container or `overture` user can write and rename in each media folder                                |
| The server shows old artwork       | Run Audit; check the server's local-assets setting                                                        |

### Uninstall

**Docker:** run `docker compose down`. Your bind-mounted config and media
remain on disk.

**Linux service:** run `sudo bash /opt/overture/current/uninstall.sh`. This keeps your
settings, database, backups and the `overture` user. To remove them too, copy
any backups you want to keep and run `sudo rm -rf /etc/overture /var/lib/overture`
and `sudo userdel overture`.

## Contributing

Share artwork and theme selections with
[OvertureDB](#overturedb), or help improve Overture itself. See the
[contributor guide](https://github.com/AutoGitr/Overture/blob/main/.github/CONTRIBUTING.md) for development setup, checks and pull
requests. Report security issues [privately](https://github.com/AutoGitr/Overture/blob/main/.github/SECURITY.md).

Overture is licensed under [AGPL-3.0](https://github.com/AutoGitr/Overture/blob/main/LICENSE).
