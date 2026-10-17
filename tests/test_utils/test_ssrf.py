"""Coverage for the shared SSRF-guard helpers, including the DNS resolution path."""

lazy import asyncio
lazy import socket

lazy import pytest

lazy from overture.utils import ssrf as module

#: What ``socket.getaddrinfo`` returns: one entry per resolved address.
type AddressInfo = list[
    tuple[socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int]]
]


async def test_rejects_non_http_schemes() -> None:
    assert await module.is_private_url("ftp://example.test/file") is True


async def test_rejects_url_with_no_hostname() -> None:
    assert await module.is_private_url("http:///no-host") is True


async def test_rejects_explicit_loopback_literals() -> None:
    assert await module.is_private_url("http://localhost/") is True
    assert await module.is_private_url("http://127.0.0.1/") is True
    assert await module.is_private_url("http://[::1]/") is True


async def test_ip_literal_private_address_is_blocked() -> None:
    assert await module.is_private_url("http://10.0.0.5/") is True


async def test_ip_literal_other_loopback_is_blocked() -> None:
    assert await module.is_private_url("http://127.0.0.2/") is True


async def test_ip_literal_link_local_ipv6_is_blocked() -> None:
    assert await module.is_private_url("http://[fe80::1]/") is True


async def test_ip_literal_public_address_is_allowed() -> None:
    assert await module.is_private_url("http://8.8.8.8/") is False


@pytest.mark.parametrize(
    ("addresses", "error", "blocked"),
    [
        (["93.184.216.34"], None, False),
        (["192.168.1.5"], None, True),
        (["100.100.100.200"], None, True),
        (["93.184.216.34", "100.64.0.1"], None, True),
        (["93.184.216.34", "::1"], None, True),
        ([], None, True),
        ([], OSError("resolution failed"), True),
        ([], ValueError("bad input"), True),
        ([], TimeoutError("resolver timed out"), True),
    ],
)
async def test_dns_requires_exclusively_public_addresses(
    addresses: list[str],
    error: Exception | None,
    blocked: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(*_args: object, **_kwargs: object) -> AddressInfo:
        if error:
            raise error
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))
            for address in addresses
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    assert await module.is_private_url("https://example.test/") is blocked
