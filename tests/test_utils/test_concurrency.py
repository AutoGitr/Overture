"""Coverage for ordered, bounded concurrency."""

lazy import asyncio
lazy from contextlib import aclosing

lazy import pytest

lazy from overture.utils.concurrency import in_order


async def test_in_order_yields_in_input_order_with_bounded_overlap() -> None:
    running = 0
    peak = 0

    async def work(item: int) -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        # Later items take fewer event-loop turns, so they finish first.
        for _ in range(10 - item):
            await asyncio.sleep(0)
        running -= 1
        return item * 2

    results = [result async for result in in_order(range(10), work, limit=3)]

    assert results == [item * 2 for item in range(10)]
    assert peak == 3


async def test_in_order_cancels_running_work_when_closed_early() -> None:
    started: list[int] = []
    cancelled: list[int] = []

    async def work(item: int) -> int:
        started.append(item)
        try:
            if item:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(item)
            raise
        return item

    async with aclosing(in_order(range(100), work, limit=4)) as results:
        async for result in results:
            assert result == 0
            break

    # Nothing new starts while the caller holds a result.
    assert started == [0, 1, 2, 3]
    assert sorted(cancelled) == [1, 2, 3]


async def test_in_order_raises_a_failure_in_its_place_and_stops_the_rest() -> None:
    started: list[int] = []
    cancelled: list[int] = []

    async def work(item: int) -> int:
        started.append(item)
        if item == 1:
            raise OSError("unreadable")
        try:
            if item:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(item)
            raise
        return item

    results = in_order(range(5), work, limit=3)
    assert await anext(results) == 0
    with pytest.raises(OSError, match="unreadable"):
        await anext(results)

    assert started == [0, 1, 2]
    assert cancelled == [2]
