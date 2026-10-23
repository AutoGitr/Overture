"""Rate-limit pauses: backoff, resets and waiting."""

lazy import httpx2
lazy import pytest

lazy from overture.utils import rate_limit
lazy from overture.utils.rate_limit import (
    PAUSE_MAX,
    PAUSE_MIN,
    RateLimitPause,
    retry_after_seconds,
)
lazy from tests.pause_clock import PauseClock


@pytest.mark.parametrize(
    ("header", "seconds"),
    [("120", 120), ("0", 0), ("", None), ("Wed, 21 Oct 2026 07:28:00 GMT", None)],
)
def test_retry_after_reads_only_delay_seconds(header: str, seconds: int | None) -> None:
    headers = {"Retry-After": header} if header else {}
    assert retry_after_seconds(httpx2.Response(429, headers=headers)) == seconds


def test_repeated_rate_limits_double_the_pause_up_to_the_maximum(
    pause_clock: PauseClock,
) -> None:
    pauses = RateLimitPause[str]()
    lengths = [pauses.limited("host") for _ in range(6)]
    assert lengths == [PAUSE_MIN, 120, 240, 480, PAUSE_MAX, PAUSE_MAX]
    assert pauses.remaining("host") == PAUSE_MAX
    assert pauses.remaining("other") == 0


def test_a_longer_retry_after_lengthens_the_pause_within_the_maximum(
    pause_clock: PauseClock,
) -> None:
    pauses = RateLimitPause[str]()
    assert pauses.limited("host", retry_after=5) == PAUSE_MIN
    assert pauses.limited("other", retry_after=300) == 300
    assert pauses.limited("other") == 600
    assert pauses.limited("third", retry_after=86400) == PAUSE_MAX


def test_a_success_resets_the_backoff_but_not_a_running_pause(
    pause_clock: PauseClock,
) -> None:
    pauses = RateLimitPause[str]()
    pauses.limited("host")
    pauses.limited("host")
    pauses.succeeded("host")
    assert pauses.remaining("host") == 120
    pause_clock.now += 120
    assert pauses.limited("host") == PAUSE_MIN
    pause_clock.now += PAUSE_MIN
    pauses.succeeded("host")
    assert pauses.longest() is None
    assert pauses.limited("host") == PAUSE_MIN


def test_longest_names_the_host_paused_longest(pause_clock: PauseClock) -> None:
    pauses = RateLimitPause[str]()
    pauses.limited("short")
    pauses.limited("long", retry_after=300)
    assert pauses.longest() == ("long", 300)
    pause_clock.now += 300
    assert pauses.longest() is None


async def test_waiting_sleeps_out_a_pause_extended_while_it_sleeps(
    monkeypatch: pytest.MonkeyPatch, pause_clock: PauseClock
) -> None:
    pauses = RateLimitPause[str]()
    pauses.limited("host")

    async def sleep(delay: float) -> None:
        if not pause_clock.waits:
            # A request already in flight is refused while this one sleeps.
            pauses.limited("host")
        await pause_clock.sleep(delay)

    monkeypatch.setattr(rate_limit, "sleep", sleep)
    await pauses.wait("host")
    await pauses.wait("other")
    assert pause_clock.waits == [PAUSE_MIN, 120 - PAUSE_MIN]
    assert pause_clock.now == 220
