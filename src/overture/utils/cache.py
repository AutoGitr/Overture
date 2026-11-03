"""Provide backend support for cache."""

lazy import asyncio
lazy import logging
lazy import time
lazy from collections import OrderedDict
lazy from collections.abc import Awaitable, Callable, Hashable
lazy from typing import Any

#: Returned for an absent key, so a legitimately cached ``None`` stays a hit.
MISSING = sentinel("MISSING")


class LRUCache[KeyT: Hashable, ValueT]:
    """Simple LRU cache backed by an OrderedDict."""

    def __init__(self, maxsize: int) -> None:
        """Initialize instance state."""
        self._maxsize = maxsize
        self._data: OrderedDict[KeyT, ValueT] = OrderedDict()

    def get(self, key: KeyT) -> ValueT | MISSING:
        """Return the cached value, or ``MISSING`` if the key is not present."""
        if key not in self._data:
            return MISSING
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: KeyT, value: ValueT) -> None:
        """Persist set."""
        if key in self._data:
            self._data.move_to_end(key)
        elif len(self._data) >= self._maxsize:
            self._data.popitem(last=False)
        self._data[key] = value

    def clear(self) -> None:
        """Release cached values."""
        self._data.clear()

    def __contains__(self, key: KeyT) -> bool:
        """Return whether the cache contains a key."""
        return key in self._data


class AsyncMemoizer[KeyT: Hashable]:
    """Fetch from cache or deduplicate inflight async requests.

    One memoizer serves calls that return different shapes, so the value type
    belongs to each ``get_or_compute`` call rather than to the instance: the
    caller gets back exactly what the coroutine it handed over returns.
    """

    def __init__(self, maxsize: int = 2000, *, ttl_seconds: float = 300) -> None:
        """Initialize instance state."""
        self._cache: LRUCache[KeyT, Any] = LRUCache(maxsize)
        self._inflight: dict[KeyT, asyncio.Task[Any]] = {}
        self._admission = asyncio.Semaphore(32)
        self._ttl = ttl_seconds
        self._closed = False
        self._generation = 0

    async def get_or_compute[ValueT, **P](
        self,
        key: KeyT,
        coro_func: Callable[P, Awaitable[ValueT]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> ValueT:
        """Return or compute."""
        if self._closed:
            raise RuntimeError("Cache is closed")
        cached = self._cache.get(key)
        if cached is not MISSING and time.monotonic() < cached[0]:
            return cached[1]
        task = self._inflight.get(key)
        if task is not None:
            return await asyncio.shield(task)
        await self._admission.acquire()
        if self._closed:
            self._admission.release()
            raise RuntimeError("Cache is closed")
        task = self._inflight.get(key)
        cached = self._cache.get(key)
        if task is not None:
            self._admission.release()
            return await asyncio.shield(task)
        if cached is not MISSING and time.monotonic() < cached[0]:
            self._admission.release()
            return cached[1]
        generation = self._generation

        async def fetch() -> ValueT:
            try:
                data = await coro_func(*args, **kwargs)
                if generation == self._generation:
                    self._cache.set(key, (time.monotonic() + self._ttl, data))
                return data
            finally:
                self._inflight.pop(key, None)
                self._admission.release()

        task = asyncio.create_task(fetch())
        task.add_done_callback(self._observe)
        self._inflight[key] = task
        return await asyncio.shield(task)

    @staticmethod
    def _observe(task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and (failure := task.exception()) is not None:
            logging.getLogger(__name__).debug(
                "Memoized operation failed", exc_info=failure
            )

    def invalidate(self) -> None:
        """Invalidate cached and still-computing pre-mutation values."""
        self._generation += 1
        self._cache.clear()

    async def close(self) -> None:
        """Cancel and await shared computations before their client closes."""
        self._closed = True
        self.invalidate()
        tasks = tuple(self._inflight.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logging.getLogger(__name__).debug(
                    "Cache operation failed at shutdown", exc_info=True
                )
        self._inflight.clear()


class TimedRegistry[KeyT: Hashable, ValueT]:
    """A bounded, self-expiring key registry.

    Two places needed the same thing - login attempts per IP, and the last
    request time per outbound host - and each hand-rolled its own eviction: a
    sweep for stale entries, then a second pass to enforce a size cap, over
    plain dicts that had to be kept in step. Both are the same structure: keep
    an entry while it is fresh, keep at most ``maxsize`` of them, and drop the
    least recently touched first.

    Entries are ordered by last touch, so eviction is a pop from the front
    rather than a scan.
    """

    def __init__(self, maxsize: int, ttl_seconds: float) -> None:
        """Bound the registry by both age and size."""
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._data: OrderedDict[KeyT, tuple[float, ValueT]] = OrderedDict()

    def __len__(self) -> int:
        """Return how many entries are currently tracked."""
        return len(self._data)

    def get(self, key: KeyT, now: float) -> ValueT | None:
        """Return the value for *key*, or None once it has expired."""
        entry = self._data.get(key)
        if entry is None:
            return None
        touched, value = entry
        if now - touched > self._ttl:
            del self._data[key]
            return None
        return value

    def set(self, key: KeyT, value: ValueT, now: float) -> None:
        """Store *value*, marking *key* as most recently touched."""
        self._data[key] = (now, value)
        self._data.move_to_end(key)
        self._evict(now)

    def pop(self, key: KeyT, now: float) -> ValueT | None:
        """Consume a fresh entry synchronously, without an intervening await."""
        value = self.get(key, now)
        self._data.pop(key, None)
        return value

    def clear(self) -> None:
        """Discard all registry entries."""
        self._data.clear()

    def _evict(self, now: float) -> None:
        """Drop expired entries, then the oldest, until the size cap holds."""
        while self._data:
            _, (touched, _) = next(iter(self._data.items()))
            if now - touched <= self._ttl and len(self._data) <= self._maxsize:
                break
            self._data.popitem(last=False)
