---
sidebar_position: 5
title: Troubleshooting
description: The first thing to check for each common problem.
---

# Troubleshooting

| Problem                            | Check                                                                                                     |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Overture exits at start            | The log, required settings, and permissions                                                               |
| `/api/ready` returns 503           | Failed checks in its response, then the logs; readiness covers the database, tools and background workers |
| Sign-in loops or live updates fail | `APP_URL`, proxy WebSocket setup, `TRUSTED_PROXY_CIDRS`                                                   |
| Library is empty                   | Run Sync; check the media server connection, selected libraries and matching media paths                  |
| Saving files fails                 | The container or `overture` user can write and rename in each media folder                                |
| The server shows old artwork       | Run Audit; check the server's local-assets setting                                                        |
| Plex cannot be reached             | DNS rebinding protection blocking `plex.direct`; see [Media servers](../install/media-servers.mdx)        |
| Themes fail to download            | `THEME_DOWNLOAD_WORKERS`, since YouTube blocks addresses that download too fast                           |

Still stuck? Open an [issue](https://github.com/AutoGitr/Overture/issues/new/choose)
with the redacted log lines around the problem, your version and how Overture
is installed. See [Support](../support.md).
