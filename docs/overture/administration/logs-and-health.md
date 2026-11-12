---
sidebar_position: 4
title: Logs and health
description: Reading the log, the health endpoints and the service's self-check.
---

# Logs and health

`docker compose logs -f overture` or `journalctl -u overture -f` shows
changes, job progress and errors; set `LOG_LEVEL=debug` for more. Errors in
the web interface include a request ID that also appears in the log.

`/api/health` reports liveness and `/api/ready` returns 503 until Overture can
serve requests; readiness covers the database, tools and background workers,
and its response names the failed checks.

For the Linux service, use `systemctl` to start, stop or restart Overture.
`sudo -u overture overture check` tests configuration, bundled tools and
permissions.

[Notifications](../features/notifications.md) can announce failed runs, so
you hear about problems without reading the log.
