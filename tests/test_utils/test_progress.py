"""Step progress mapping and throttling."""

lazy import pytest

lazy import overture.utils.progress as progress_mod
lazy from overture.utils.progress import ProgressUpdate, StepProgress


class _Clock:
    """A clock that hands out the readings a test asked for, in order."""

    def __init__(self, ticks: tuple[float, ...]) -> None:
        self._ticks = iter(ticks)

    def monotonic(self) -> float:
        return next(self._ticks)


def _recorder(steps: tuple[str, ...]) -> tuple[list[ProgressUpdate], StepProgress]:
    seen: list[ProgressUpdate] = []

    async def record(update: ProgressUpdate) -> None:
        seen.append(update)

    return seen, StepProgress(record, steps)


async def test_each_step_is_an_equal_share_of_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(progress_mod, "time", _Clock((1.0, 2.0, 3.0, 4.0)))
    seen, progress = _recorder(("downloading", "hashing"))

    await progress.enter("downloading")
    await progress.report(0.5)
    await progress.report(2)  # clamped to the end of the step
    await progress.enter("hashing")

    assert seen == [
        ProgressUpdate(0, "downloading", 1, 2),
        ProgressUpdate(25, "downloading", 1, 2),
        ProgressUpdate(50, "downloading", 1, 2),
        ProgressUpdate(50, "hashing", 2, 2),
    ]


async def test_report_drops_updates_that_arrive_too_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(progress_mod, "time", _Clock((5.0, 5.1, 5.4, 5.45)))
    seen, progress = _recorder(("downloading", "writing"))

    await progress.enter("downloading")
    await progress.report(0.2)
    await progress.report(0.6)
    await progress.enter("writing")

    assert [update.percent for update in seen] == [0, 30, 50]


async def test_enter_refuses_a_step_that_already_passed() -> None:
    _seen, progress = _recorder(("downloading", "writing"))

    await progress.enter("writing")

    with pytest.raises(ValueError, match="not in tuple"):
        await progress.enter("downloading")


async def test_report_bytes_says_nothing_without_a_known_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(progress_mod, "time", _Clock((1.0, 2.0)))
    seen, progress = _recorder(("downloading",))

    await progress.enter("downloading")
    await progress.report_bytes(500, None)
    await progress.report_bytes(500, 1000)

    assert [update.percent for update in seen] == [0, 50]
