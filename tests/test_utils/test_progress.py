"""Stage progress mapping and throttling."""

lazy from collections.abc import Awaitable, Callable

lazy import pytest

lazy import overture.utils.progress as progress_mod
lazy from overture.utils.progress import StageProgress


class _Clock:
    """A clock that hands out the readings a test asked for, in order."""

    def __init__(self, ticks: tuple[float, ...]) -> None:
        self._ticks = iter(ticks)

    def monotonic(self) -> float:
        return next(self._ticks)


def _recorder() -> tuple[
    list[tuple[int, str]],
    Callable[[int, str], Awaitable[None]],
]:
    seen: list[tuple[int, str]] = []

    async def record(percent: int, stage: str) -> None:
        seen.append((percent, stage))

    return seen, record


async def test_report_maps_a_fraction_onto_the_stage_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(progress_mod, "time", _Clock((1.0, 2.0, 3.0)))
    seen, record = _recorder()
    stage = StageProgress(record, stage="downloading", start=10, end=70)

    await stage.report(0)
    await stage.report(0.5)
    await stage.report(2)  # clamped to the end of the band

    assert seen == [(10, "downloading"), (40, "downloading"), (70, "downloading")]


async def test_report_drops_updates_that_arrive_too_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(progress_mod, "time", _Clock((5.0, 5.1, 5.4)))
    seen, record = _recorder()
    stage = StageProgress(record, stage="downloading", start=0, end=100)

    await stage.report(0.1)
    await stage.report(0.2)
    await stage.report(0.3)

    assert seen == [(10, "downloading"), (30, "downloading")]


async def test_report_bytes_says_nothing_without_a_known_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(progress_mod, "time", _Clock((1.0,)))
    seen, record = _recorder()
    stage = StageProgress(record, stage="downloading", start=0, end=100)

    await stage.report_bytes(500, None)
    await stage.report_bytes(500, 1000)

    assert seen == [(50, "downloading")]
