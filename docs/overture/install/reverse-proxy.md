---
sidebar_position: 7
title: Reverse proxy
description: Serve Overture over HTTPS behind Caddy, Nginx or Traefik.
---

# Reverse proxy

1. Set `APP_URL` to the exact public origin, such as
   `https://overture.example.com`.
2. Set `TRUSTED_PROXY_CIDRS` to the address the proxy connects from.
3. Pass WebSocket upgrades on `/ws` and keep the browser's `Origin` header.
4. Serve HTTP/2, so the browser loads many images at once.

For direct HTTP access with password sign-in, leave `APP_URL` and
`TRUSTED_PROXY_CIDRS` empty. OIDC still requires `APP_URL` and HTTPS, except
on loopback.

Browsers offer to install Overture as an app only over HTTPS, so a reverse
proxy with a certificate is also what makes the
[installable app](../features/getting-started.md#install-as-an-app) available.

## Caddy

```caddy
overture.example.com {
    reverse_proxy 127.0.0.1:5885
}
```

## Nginx

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

## Traefik

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

## Troubleshooting

Sign-in loops and live updates that stop are almost always `APP_URL`, the
proxy's WebSocket setup or `TRUSTED_PROXY_CIDRS`. See
[Troubleshooting](../administration/troubleshooting.md).
