---
sidebar_position: 8
title: Notifications
description: Hear when runs end, through Discord, Slack, Telegram, Gotify, ntfy or Apprise.
---

# Notifications

Set `NOTIFY_URL` and Overture tells that address when runs end. It recognises
these by their address and sends each the message its API takes:

| Service       | `NOTIFY_URL`                                                                                                                                                                                                                                         |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Discord       | the channel's webhook, `https://discord.com/api/webhooks/…`                                                                                                                                                                                          |
| Slack         | the incoming webhook, `https://hooks.slack.com/services/…`                                                                                                                                                                                           |
| Telegram      | `https://api.telegram.org/bot<token>/sendMessage?chat_id=<chat>`                                                                                                                                                                                     |
| Gotify        | `https://<gotify>/message?token=<app token>`                                                                                                                                                                                                         |
| ntfy          | `https://ntfy.sh/<topic>`                                                                                                                                                                                                                            |
| Anything else | gets JSON with `title`, `body` and `type` (`success`, `warning` or `failure`), which [Apprise's API](https://github.com/caronc/apprise-api) takes as is, so one Apprise URL reaches email, Matrix, Pushover and every other service Apprise supports |

**Notifications** in the menu chooses, for each kind of run (library sync,
Assets art and theme runs, Renamer scan, server audit and its fix, OvertureDB
sync, backup), whether a failed or stopped run is announced, which completed
runs are (never, always, only with changes, only with errors), and whether
only runs a schedule started count. Out of the box only failures are
announced. **Send test notification** checks the address.

A message never carries a configured secret; one that cannot be sent is
logged, without the URL, and never holds up the run.
