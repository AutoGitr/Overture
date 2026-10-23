"""A fake clock for rate-limit pauses."""

lazy import asyncio


class PauseClock:
    """Advance rate-limit pauses without delaying the tests."""

    def __init__(self) -> None:
        self.now = 100.0
        self.waits: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.waits.append(delay)
        self.now += delay
        await asyncio.sleep(0)
