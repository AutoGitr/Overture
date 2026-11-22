---
sidebar_position: 6
title: Environment variables
description: Every setting Overture reads at start.
---

# Environment variables

These variables set up the connection, sign-in and runtime; everything else is
set in the web interface. Docker reads them from `.env` or
[Docker secrets](docker.md#docker-secrets), and the Linux service from its
[settings file](linux-service.md#settings-file). Empty values count as unset.

A copy of
[`.env.example`](https://github.com/AutoGitr/Overture/blob/main/.env.example)
is the quickest start.

## Media servers and services

`<NAME>` is a name from `MEDIA_SERVERS` in capitals, so
`MEDIA_SERVERS=Plex,Living_Room` reads `MEDIA_SERVER_PLEX_URL` and
`MEDIA_SERVER_LIVING_ROOM_URL`. See [Media servers](media-servers.mdx).

| Variable                               | Required        | Default | Description                                                                                                                           |
| -------------------------------------- | --------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `MEDIA_SERVERS`                        | Yes             |         | Names of your media servers, comma-separated, the lead first; `none` for no server                                                    |
| `MEDIA_SERVER_<NAME>_TYPE`             | For each server |         | `plex`, `jellyfin` or `emby`                                                                                                          |
| `MEDIA_SERVER_<NAME>_URL`              | For each server |         | Server address with protocol, port and any base path                                                                                  |
| `MEDIA_SERVER_<NAME>_API_KEY`          | For each server |         | Server token or API key                                                                                                               |
| `MEDIA_SERVER_<NAME>_VERIFY_TLS`       | No              | `true`  | Set to `false` only for a self-signed certificate; keep it on for Plex                                                                |
| `MEDIA_SERVER_<NAME>_PATH_MAP`         | No              |         | `server_path=local_path` pairs, comma-separated, for folders the server sees at another path                                          |
| `MEDIA_SERVER_<NAME>_COLLECTIONS_PATH` | No              |         | Jellyfin only: local mount of its collections directory, used to write BoxSet themes                                                  |
| `TMDB_READ_ACCESS_TOKEN`               | No              |         | Enables TMDB artwork, titles, lists and search; the **API Read Access Token** under **Settings -> API** on themoviedb.org             |
| `MDBLIST_API_KEY`                      | No              |         | Enables dynamic collection membership from MDBList JSON lists; kept on the backend                                                    |
| `RADARR_URL`                           | No              |         | Radarr server URL with protocol, port and base path (e.g. `http://192.0.2.10:7878`); enables Radarr tag collection builders           |
| `RADARR_API_KEY`                       | If using Radarr |         | Radarr API key; kept on the backend                                                                                                   |
| `RADARR_VERIFY_TLS`                    | No              | `true`  | Set to `false` only for self-signed certificates                                                                                      |
| `SONARR_URL`                           | No              |         | Sonarr server URL with protocol, port and base path (e.g. `http://192.0.2.10:8989`); enables Sonarr tag collection builders           |
| `SONARR_API_KEY`                       | If using Sonarr |         | Sonarr API key; kept on the backend                                                                                                   |
| `SONARR_VERIFY_TLS`                    | No              | `true`  | Set to `false` only for self-signed certificates                                                                                      |
| `NOTIFY_URL`                           | No              |         | Discord, Slack, Telegram, Gotify, ntfy or Apprise address that hears when runs end; see [Notifications](../features/notifications.md) |

## Sign-in

| Variable              | Required           | Default            | Description                                                                                                                                 |
| --------------------- | ------------------ | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `AUTH_MODE`           | No                 | `password`         | Authentication mode: `password`, `oidc`, `both`, or `none`                                                                                  |
| `APP_PASSWORD_HASH`   | `password`, `both` |                    | [Password](authentication.md#password) hash; required for `password` and `both` modes                                                       |
| `OIDC_ISSUER_URL`     | `oidc`, `both`     |                    | Exact [OIDC](authentication.md#sso-with-openid-connect) issuer, with any path and trailing slash (Authentik: `.../application/o/overture/`) |
| `OIDC_CLIENT_ID`      | `oidc`, `both`     |                    | OIDC client ID                                                                                                                              |
| `OIDC_CLIENT_SECRET`  | `oidc`, `both`     |                    | OIDC client secret                                                                                                                          |
| `OIDC_DISPLAY_NAME`   | No                 | `Sign in with SSO` | Sign-in button text, up to 80 characters                                                                                                    |
| `OIDC_AUTO_LOGIN`     | No                 | `false`            | Send visitors straight to the provider; `/login?autologin=0` opens the login page                                                           |
| `APP_URL`             | `oidc`, `both`     |                    | The public origin behind a [reverse proxy](reverse-proxy.md); required for OIDC                                                             |
| `SESSION_EXPIRY_DAYS` | No                 | `7`                | How long a sign-in session lasts (in days)                                                                                                  |
| `TRUSTED_PROXY_CIDRS` | No                 |                    | Comma-separated proxy addresses or networks whose `X-Forwarded-For` names the client that sign-in attempts are limited by                   |

## Runtime

| Variable                 | Required | Default                   | Description                                                                                     |
| ------------------------ | -------- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| `TZ`                     | No       | `UTC`                     | IANA time zone for logs and schedules                                                           |
| `LOG_LEVEL`              | No       | `info`                    | `debug`, `info`, `warning`, `error` or `critical`                                               |
| `LOG_COLOUR`             | No       | `true` (service: `false`) | Colour log lines; set `false` for plain text                                                    |
| `PHASH_WORKERS`          | No       | `1`                       | Image hashing processes (1-32); more use more memory, and more than the CPU count gains nothing |
| `ART_DOWNLOAD_WORKERS`   | No       | `1`                       | Parallel artwork downloads (1-10); keep low to avoid rate limits and to be nice                 |
| `THEME_DOWNLOAD_WORKERS` | No       | `1`                       | Parallel theme downloads (1-4); YouTube blocks addresses that download too fast                 |

The Linux service reads a few more, for its address and paths: see
[Settings file](linux-service.md#settings-file).
