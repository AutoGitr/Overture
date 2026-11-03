"""KeyedLock: per-target mutual exclusion for downloads."""

lazy import asyncio

lazy import pytest

lazy from overture.utils.locks import KeyedLock


async def test_the_same_key_runs_one_at_a_time() -> None:
    locks = KeyedLock[str]()
    order: list[str] = []

    async def work(label: str, turns: int) -> None:
        async with locks.acquire("poster"):
            order.append(f"{label}:enter")
            for _ in range(turns):
                await asyncio.sleep(0)
            order.append(f"{label}:exit")

    await asyncio.gather(work("a", 3), work("b", 0))

    # Whoever went first finished before the other started.
    assert order[1].endswith(":exit")
    assert order[0].split(":")[0] == order[1].split(":")[0]


async def test_different_keys_do_not_block_each_other() -> None:
    locks = KeyedLock[str]()
    running = 0
    peak = 0

    async def work(key: str) -> None:
        nonlocal running, peak
        async with locks.acquire(key):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0)
            running -= 1

    await asyncio.gather(work("poster"), work("background"), work("theme"))

    assert peak == 3


async def test_locks_are_dropped_once_nobody_wants_the_key() -> None:
    """A long-lived process must not accumulate a lock per key it has seen."""
    locks = KeyedLock[int]()

    for key in range(50):
        async with locks.acquire(key):
            pass

    assert locks.tracked_keys == 0


async def test_a_failing_holder_releases_the_key() -> None:
    locks = KeyedLock[str]()

    with pytest.raises(RuntimeError):
        async with locks.acquire("poster"):
            raise RuntimeError("boom")

    assert locks.tracked_keys == 0
    async with locks.acquire("poster"):
        pass
