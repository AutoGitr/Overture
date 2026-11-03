"""Shared SSRF-guard helpers."""

lazy import asyncio
lazy import ipaddress
lazy import socket
lazy from urllib.parse import urlparse

# Only these schemes are ever legitimate for external art/theme URLs.
_ALLOWED_SCHEMES = {"http", "https"}

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
"""Host names that always mean this machine."""


async def is_private_url(
    url: str, *, dns_cache: dict[str, asyncio.Task[bool]] | None = None
) -> bool:
    """Return True if *url* should be blocked as a private/internal address."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        _ = parsed.port
    except ValueError:
        return True

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return True

    if not host:
        return True

    if host in LOOPBACK_HOSTS:
        return True

    try:
        ip = ipaddress.ip_address(host)
        return is_blocked_ip(ip)
    except ValueError:
        pass

    if dns_cache is None:
        return await _private_host(host)
    if host not in dns_cache:
        dns_cache[host] = asyncio.create_task(_private_host(host))
    return await dns_cache[host]


async def _private_host(host: str) -> bool:
    """Resolve one host with a bounded wait; failures remain unsafe."""
    try:
        loop = asyncio.get_running_loop()
        async with asyncio.timeout(10):
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not infos:
            return True
        for _family, _socktype, _proto, _canonname, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if is_blocked_ip(ip):
                return True
        return False
    except OSError, ValueError, TimeoutError:
        # Resolver failures are treated as unsafe: callers should not be allowed
        # to bypass SSRF protection when the host cannot be verified.
        return True


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for any IP that should never be fetched server-side."""
    # Shared address space (100.64.0.0/10) is neither private nor global.
    return not ip.is_global or ip.is_multicast or ip.is_reserved
