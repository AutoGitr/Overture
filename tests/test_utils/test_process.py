"""Owned subprocess pipes, cancellation and cleanup without starting programs."""

lazy import asyncio
lazy from types import SimpleNamespace
lazy from unittest.mock import AsyncMock, Mock

lazy import pytest

lazy from overture.utils import process


@pytest.fixture
async def child(monkeypatch: pytest.MonkeyPatch) -> Mock:
    proc = Mock(spec=asyncio.subprocess.Process)
    proc.pid = 123
    proc.returncode = 0
    proc.stdout = asyncio.StreamReader()
    proc.stderr = asyncio.StreamReader()
    proc.wait = AsyncMock(return_value=0)
    monkeypatch.setattr(
        process.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc)
    )
    monkeypatch.setattr(process, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(process, "WindowsJob", Mock())
    return proc


@pytest.mark.parametrize("capture", [False, True])
async def test_capture_drains_both_pipes_and_keeps_a_bounded_error_tail(
    child: Mock, monkeypatch: pytest.MonkeyPatch, capture: bool
) -> None:
    monkeypatch.setattr(process, "_TAIL_BYTES", 8)
    child.stdout.feed_data(b"output")
    child.stdout.feed_eof()
    child.stderr.feed_data(b"discarded-error\xff")
    child.stderr.feed_eof()

    result = await process.run_process(
        ["tool", "--version"], deadline=1, capture=capture
    )

    assert result == process.ProcessResult(
        0, b"output" if capture else b"", "d-error\ufffd"
    )
    child.wait.assert_awaited()


@pytest.mark.parametrize(
    ("data", "capture", "message"),
    [
        (b"12345", True, "output exceeds"),
        (b"12345\n", False, "line exceeds"),
        (b"12345", False, "line exceeds"),
    ],
)
async def test_output_limits_fail_the_operation_and_reap_the_child(
    child: Mock,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    capture: bool,
    message: str,
) -> None:
    monkeypatch.setattr(process, "_MAX_OUTPUT", 4)
    monkeypatch.setattr(process, "_MAX_LINE", 4)
    child.stdout.feed_data(data)
    child.stdout.feed_eof()
    child.stderr.feed_eof()
    on_line = AsyncMock()

    with pytest.raises(ValueError, match=message):
        await process.run_process(
            ["tool"], deadline=1, capture=capture, on_line=on_line
        )

    child.wait.assert_awaited()


async def test_missing_pipe_is_an_error_and_still_reaps_the_child(child: Mock) -> None:
    child.stdout = None
    child.stderr.feed_eof()
    with pytest.raises(OSError, match="pipe unavailable"):
        await process.run_process(["tool"], deadline=1)
    child.wait.assert_awaited()


async def test_slow_progress_is_coalesced_and_callback_failure_does_not_stop_pipes(
    child: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    delivered: list[str] = []
    called = asyncio.Event()

    async def on_line(line: str) -> None:
        delivered.append(line)
        called.set()
        raise ValueError("progress unavailable")

    child.stdout.feed_data(b"old\n latest \n")
    child.stderr.feed_eof()
    task = asyncio.create_task(
        process.run_process(["tool"], deadline=2, on_line=on_line)
    )
    try:
        async with asyncio.timeout(2):
            await called.wait()
        child.stdout.feed_eof()
        result = await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert delivered == ["latest"]
    assert result.stdout == b"old\n latest \n"
    assert "Subprocess progress delivery failed" in caplog.text


async def test_deadline_kills_and_reaps_a_running_child(child: Mock) -> None:
    child.returncode = None
    with pytest.raises(TimeoutError):
        await process.run_process(["tool"], deadline=0)
    child.kill.assert_called_once_with()
    child.wait.assert_awaited_once()


async def test_cancellation_during_spawn_waits_for_ownership_before_cleanup(
    child: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def spawn(*args: str, **kwargs: object) -> Mock:
        entered.set()
        await release.wait()
        return child

    monkeypatch.setattr(process.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(process.run_process(["tool"], deadline=1))
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    child.wait.assert_awaited_once()


async def test_failed_windows_job_acquisition_uses_taskkill(
    child: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    child.returncode = None
    killer = Mock(wait=AsyncMock())
    spawn = AsyncMock(side_effect=[child, killer])
    monkeypatch.setattr(process.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(
        process, "WindowsJob", Mock(side_effect=OSError("job unavailable"))
    )

    with pytest.raises(OSError, match="job unavailable"):
        await process.run_process(["tool"], deadline=1)

    assert spawn.call_args_list[1].args == ("taskkill", "/PID", "123", "/T", "/F")
    killer.wait.assert_awaited_once()
    child.kill.assert_called_once_with()
    child.wait.assert_awaited_once()


@pytest.mark.parametrize("already_exited", [False, True])
async def test_posix_cleanup_kills_the_process_group(
    child: Mock, monkeypatch: pytest.MonkeyPatch, already_exited: bool
) -> None:
    killpg = Mock(side_effect=ProcessLookupError if already_exited else None)
    monkeypatch.setattr(process, "os", SimpleNamespace(name="posix", killpg=killpg))
    monkeypatch.setattr(process, "signal", SimpleNamespace(SIGKILL=9))
    child.stdout.feed_eof()
    child.stderr.feed_eof()

    await process.run_process(["tool"], deadline=1)

    killpg.assert_called_once_with(123, 9)
    child.kill.assert_not_called()


@pytest.mark.parametrize("operation_fails", [False, True])
async def test_cleanup_failure_preserves_the_original_error(
    child: Mock,
    monkeypatch: pytest.MonkeyPatch,
    operation_fails: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tasks_before = asyncio.all_tasks()
    job = Mock()
    job.close.side_effect = OSError("cleanup failed")
    monkeypatch.setattr(process, "WindowsJob", Mock(return_value=job))
    child.stdout.feed_eof()
    child.stderr.feed_eof()
    if operation_fails:
        child.stdout = None
    with pytest.raises(
        OSError, match="pipe unavailable" if operation_fails else "cleanup failed"
    ):
        await process.run_process(["tool"], deadline=1)
    if operation_fails:
        assert "Subprocess cleanup failed after operation error" in caplog.text
    assert asyncio.all_tasks() == tasks_before


async def test_cancellation_during_cleanup_waits_until_the_child_is_reaped(
    child: Mock,
) -> None:
    waiting = asyncio.Event()
    release = asyncio.Event()
    waits = 0

    async def wait() -> int:
        nonlocal waits
        waits += 1
        if waits == 2:
            waiting.set()
            await release.wait()
        return 0

    child.wait.side_effect = wait
    child.stdout.feed_eof()
    child.stderr.feed_eof()
    task = asyncio.create_task(process.run_process(["tool"], deadline=2))
    try:
        async with asyncio.timeout(2):
            await waiting.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert waits == 2
