"""Cache eviction, shared work, and cancellation contracts."""

lazy import asyncio
lazy from contextlib import suppress

lazy import pytest

lazy from overture.utils.cache import MISSING, AsyncMemoizer, LRUCache


class TestLRUCache:
    def test_cache_preserves_none_as_hit_and_evicts_oldest_key(self) -> None:
        cache: LRUCache[tuple[str], str | None] = LRUCache(maxsize=2)
        cache.set(("a",), None)
        cache.set(("b",), "bee")

        assert cache.get(("a",)) is None

        cache.set(("c",), "see")
        assert ("a",) in cache
        assert ("b",) not in cache
        assert ("c",) in cache
        assert cache.get(("b",)) is MISSING


class TestAsyncMemoizer:
    async def test_deduplicates_inflight_work_and_caches_none(self) -> None:
        memoizer: AsyncMemoizer[tuple[str]] = AsyncMemoizer(maxsize=10)
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)

        first, second = await asyncio.gather(
            memoizer.get_or_compute(("key",), compute),
            memoizer.get_or_compute(("key",), compute),
        )
        third = await memoizer.get_or_compute(("key",), compute)

        assert first is None
        assert second is None
        assert third is None
        assert calls == 1

    async def test_failed_inflight_task_can_retry(self) -> None:
        memoizer: AsyncMemoizer[tuple[str]] = AsyncMemoizer(maxsize=10)
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary")
            return "ok"

        with pytest.raises(RuntimeError):
            await memoizer.get_or_compute(("key",), compute)

        assert await memoizer.get_or_compute(("key",), compute) == "ok"
        assert calls == 2

    async def test_cancelled_waiter_does_not_cancel_shared_work(self) -> None:
        memoizer: AsyncMemoizer[tuple[str]] = AsyncMemoizer(maxsize=10)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def compute() -> str:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return "ok"

        cancelled = asyncio.create_task(memoizer.get_or_compute(("key",), compute))
        await started.wait()
        survivor = asyncio.create_task(memoizer.get_or_compute(("key",), compute))
        cancelled.cancel()
        with suppress(asyncio.CancelledError):
            await cancelled

        release.set()
        assert await survivor == "ok"
        assert await memoizer.get_or_compute(("key",), compute) == "ok"
        assert calls == 1
