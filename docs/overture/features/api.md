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

Errors in the web interface include a request ID that also appears in the log.

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
