"""Overlap independent waits while keeping results in their input order."""

lazy import asyncio
lazy from collections import deque
lazy from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable


async def in_order[T, R](
    items: Iterable[T], work: Callable[[T], Awaitable[R]], *, limit: int
) -> AsyncGenerator[R]:
    """Yield ``work(item)`` for each item, in order, with up to *limit* running.

    A slow item holds back only the results after it, never the work: the
    next items keep running until *limit* are in flight. Closing the iterator
    early cancels what is still running and waits for it, so a caller that
    stops never leaves work behind; use it with :func:`contextlib.aclosing`.
    A failure is raised where its result would have been yielded.
    """
    running: deque[asyncio.Task[R]] = deque()

    async def run(item: T) -> R:
        return await work(item)

    async def oldest() -> R:
        # The task leaves the queue only once it is done, so the cleanup
        # below still owns it if this wait is interrupted.
        result = await running[0]
        running.popleft()
        return result

    try:
        for item in items:
            running.append(asyncio.create_task(run(item)))
            if len(running) >= limit:
                yield await oldest()
        while running:
            yield await oldest()
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
