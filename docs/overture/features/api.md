---
sidebar_position: 9
title: REST API
description: The OpenAPI description, API keys and the health endpoints.
---

# REST API

The REST API is described in
[`openapi/overture.json`](https://github.com/AutoGitr/Overture/blob/main/openapi/overture.json)
and served at `/api/docs` for authenticated users.

## API keys

Dashboards and scripts sign in with an API key: create one under **API keys**
in the menu, copy it (it is shown once) and send it as the `X-Api-Key` header.
A key reads everything a signed-in user can and runs collection previews, but
cannot change anything. Revoke a key in the same place to stop it at once.

## Conventions

Required JSON request bodies reject `null`. To stop all bulk asset jobs,
`POST /api/bulk/assets/stop` accepts an omitted body, `null`, or `{}`.

A failed request answers `{"detail": "..."}` saying why, except a request
that does not fit the schema, whose 422 lists each issue with where it is. A
409 says what stands in the way, such as a setting that is not set (a media
server, a TMDB token) or OvertureDB being off; 502 and 503 mean a media server
or YouTube failed or is down. Every answer a
route can give is in the OpenAPI description.

Errors in the web interface include a request ID that also appears in the log.

## Assets

Titles and collections carry their poster, background and theme under
`assets`, and a season its poster under `poster`. Each asset has:

- the selection: `url`, `upload_hash` or `youtube_id`, with where it came from,
  and `selected` when there is one;
- `content_hash`, the bytes Overture holds for the selection once it has them;
- `status`: `complete` once every place it must be holds those bytes,
  `partial` when only some of it is recorded, and `missing` otherwise; an
  asset that is not `needed` is complete as it is;
- `deliveries`, one per place: `server_id` is `null` for the title's own
  folder, `delivered` says the place holds Overture's bytes, and `present` that
  something was seen there at all;
- `file`, the file in the title's folder; `width` and `height` of the image
  in place; and `duration`, how long a theme plays: the audio Overture holds,
  else the file in the folder, else the YouTube video.

## Useful endpoints

| Endpoint                                                     | Returns                                                                     |
| ------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `GET /api/health`                                            | Liveness                                                                    |
| `GET /api/ready`                                             | 503 until Overture can serve requests; the response names the failed checks |
| `GET /api/media-server/links`                                | Where the server's web app opens items and collections                      |
| `GET /api/library/items/{id}/record`                         | A title's stored rows and derived values, such as genres and people         |
| `GET /api/collections/{id}/record`                           | A collection's stored rows and derived values                               |
| `GET /api/collections/{id}/art/{art_type}/generated/{style}` | Art generated from the collection's title                                   |

## Live updates

The web interface follows changes over a WebSocket at `/ws`; a reverse proxy
must pass the upgrade (see [Reverse proxy](../install/reverse-proxy.md)).
Events such as `collection.monitored` report changes on their own, so several
open browsers stay in step.
