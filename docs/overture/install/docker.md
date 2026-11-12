---
sidebar_position: 2
title: Docker
description: Run Overture with Docker Compose.
---

# Docker

For Linux `amd64` and `arm64`. The image is `ghcr.io/autogitr/overture`, also
on Docker Hub as `autogitr/overture`. A tag such as `1.2.3` is one release,
`1.2` and `1` follow the newest release in that line, and `latest` follows the
newest release. The supplied Compose file uses `0`, which gets every update
without a breaking change.

## Steps

1. Download [`compose.yaml`](https://github.com/AutoGitr/Overture/blob/main/compose.yaml).
2. Download [`.env.example`](https://github.com/AutoGitr/Overture/blob/main/.env.example),
   save it as `.env`, and configure your environment (see
   [Environment variables](environment-variables.md)).
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

4. Create the config directory owned by the container user (`1000:1000` by
   default), and give that user read and write access to your media folders. If
   you change `user:` in Compose, use the same UID and GID here:

   ```sh
   mkdir -p config && sudo chown 1000:1000 config
   ```

5. Set up [authentication](authentication.md). The default is password sign-in;
   generate and save `APP_PASSWORD_HASH` as described under
   [Password](authentication.md#password).

6. Start Overture and open `http://localhost:5885`:

   ```sh
   docker compose up -d
   ```

   The supplied Compose file binds to localhost. To reach it from another
   machine, change the port mapping to `"5885:5885"` or configure a
   [reverse proxy](reverse-proxy.md). Keep authentication enabled.

## The Compose file

The supplied file runs the container read-only as an unprivileged user with
every capability dropped, limits its CPU, memory and process count, and keeps
its logs small:

```yaml
services:
  overture:
    image: "ghcr.io/autogitr/overture:0"
    container_name: "overture"
    restart: "unless-stopped"
    user: "1000:1000"
    cap_drop:
      - "ALL"
    security_opt:
      - "no-new-privileges:true"
    read_only: true
    init: true
    ports:
      - "127.0.0.1:5885:5885"
    env_file: ".env"
    volumes:
      - "./config:/config"
      # The container path must be the one your media server reports for your media.
      - "/path/to/media:/media"
    tmpfs:
      - "/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777"
    logging:
      driver: "json-file"
      options:
        max-file: "3"
        max-size: "10m"
    cpus: 2.0
    mem_limit: "2g"
    mem_reservation: "512m"
    pids_limit: 256
    stop_grace_period: "60s"
    ulimits:
      nofile:
        hard: 65536
        soft: 65536
```

The Docker image sets its own listening address and config folder; change the
published port in `compose.yaml` instead.

## Docker secrets

Any setting can come from a
[Compose secret](https://docs.docker.com/compose/how-tos/use-secrets/) named
after it in lowercase. Leave the setting empty in `.env`. Overture validates
required settings after loading the mounted secrets.

```yaml
services:
  overture:
    secrets: [media_server_api_key]
secrets:
  media_server_api_key:
    file: ./secrets/media_server_api_key
```

## Verify the image

Each release is signed by its GitHub workflow with Sigstore. See
[Verify a release](../administration/verify-a-release.md) to check the image
before you run it.
