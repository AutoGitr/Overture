"""Per-key mutual exclusion for work that must not overlap on the same target."""

lazy import asyncio
lazy from collections.abc import AsyncGenerator, Hashable
lazy from contextlib import asynccontextmanager


class KeyedLock[KeyT: Hashable]:
    """Serialise work per key, holding no lock for a key nobody is using.

    Two downloads for the same art slot must not run at once. Waiting on the
    key parks the caller until the holder finishes, which is what an
    ``asyncio.Lock`` is for; the alternative a caller reaches for without one
    is re-queueing on a timer, which turns contention into a spin.

    Locks are created on demand and dropped once the last waiter leaves, so a
    long-running process does not accumulate one per key it has ever seen.
    """

    def __init__(self) -> None:
        """Initialize an empty lock registry."""
        self._locks: dict[KeyT, asyncio.Lock] = {}
        self._waiters: dict[KeyT, int] = {}

    @property
    def tracked_keys(self) -> int:
        """Return how many keys currently have a lock, for tests and metrics."""
        return len(self._locks)

    @asynccontextmanager
    async def acquire(self, key: KeyT) -> AsyncGenerator[None]:
        """Hold the lock for *key* for the duration of the block."""
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        self._waiters[key] = self._waiters.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            remaining = self._waiters[key] - 1
            if remaining:
                self._waiters[key] = remaining
            else:
                del self._waiters[key]
                self._locks.pop(key, None)
