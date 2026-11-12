---
sidebar_position: 6
title: Authentication
description: Password sign-in, single sign-on with OpenID Connect, or open access.
---

# Authentication

Choose sign-in with `AUTH_MODE`:

| Mode                 | Sign-in            | Required settings                                                    |
| -------------------- | ------------------ | -------------------------------------------------------------------- |
| `password` (default) | Password           | `APP_PASSWORD_HASH`                                                  |
| `oidc`               | OpenID Connect SSO | `APP_URL`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` |
| `both`               | Password or SSO    | Both sets above                                                      |
| `none`               | Open access        |                                                                      |

:::warning

`AUTH_MODE=none` opens your instance to anyone who can reach its port. Use it
only on a trusted network or behind a proxy that handles sign-in. Never expose
an unprotected instance to the internet.

:::

## Password

When `AUTH_MODE` is `password` or `both`, a password hash is required.

`overture password hash` asks for a password twice and prints a line such as
`APP_PASSWORD_HASH='$argon2id$...'`. In `.env` or `overture.env`, paste the
whole line, quotes included, in place of the old one. Any non-empty password
up to 1,024 bytes works; use 15 characters or more. Hashes from other Argon2id
tools also work.

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

## SSO with OpenID Connect

When `AUTH_MODE` is `oidc` or `both`, OIDC authentication is enabled. Every
signed-in user has full access, so limit who may use Overture in your identity
provider.

1. Register a confidential web client using the authorization code flow with
   PKCE and `client_secret_basic`, scopes `openid profile email`, and these
   URIs:
   - Redirect: `https://overture.example.com/api/auth/oidc/callback`
   - Post-logout redirect: `https://overture.example.com/login?autologin=0`
2. Set `APP_URL`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`,
   and optionally `OIDC_DISPLAY_NAME` and `OIDC_AUTO_LOGIN`.

Set the issuer, client ID and secret together; Overture starts only with all
three. OIDC requires `APP_URL` and HTTPS, except on loopback, so it usually
sits behind a [reverse proxy](reverse-proxy.md).

With Authentik, the issuer is the provider's URL including its path and
trailing slash, such as `https://auth.example.com/application/o/overture/`.

## API keys

Dashboards and scripts sign in with an API key instead of a password or SSO
session. Keys are read-only; see [REST API](../features/api.md).
