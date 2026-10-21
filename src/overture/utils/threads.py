"""Await blocking work without abandoning its resource ownership on cancellation."""

lazy import asyncio
lazy from collections.abc import Callable


async def owned_thread[T, **P](
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Delay cancellation until the thread has stopped using its files or locks."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result
