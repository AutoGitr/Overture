"""Owned subprocess execution with bounded pipes and process-tree cleanup."""

lazy import asyncio
lazy import contextlib
lazy import logging
lazy import os
lazy import signal
lazy from collections.abc import Awaitable, Callable, Sequence
lazy from dataclasses import dataclass

lazy from .windows_job import WindowsJob

logger = logging.getLogger(__name__)
#: ffprobe and audio fingerprint processes at once; they are CPU bound.
PROBE_SLOTS = asyncio.Semaphore(os.process_cpu_count() or 2)
_MAX_OUTPUT = 4 * 1024 * 1024
_MAX_LINE = 1024 * 1024
_TAIL_BYTES = 16 * 1024
_CREATE_SUSPENDED = 0x4


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    error_tail: str


async def _terminate(proc: asyncio.subprocess.Process, job: WindowsJob | None) -> None:
    if os.name == "nt":
        if job is not None:
            job.close()
        elif proc.returncode is None:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(proc.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    await proc.wait()


async def _read(
    stream: asyncio.StreamReader | None,
    *,
    output: bytearray | None,
    tail: bytearray,
    progress: asyncio.Queue[str] | None,
) -> None:
    if stream is None:
        raise OSError("Subprocess output pipe unavailable")
    pending: bytearray = bytearray()
    while chunk := await stream.read(64 * 1024):
        tail.extend(chunk)
        del tail[:-_TAIL_BYTES]
        if output is not None:
            if len(output) + len(chunk) > _MAX_OUTPUT:
                raise ValueError("Subprocess output exceeds safety limit")
            output.extend(chunk)
        if progress is not None:
            pending.extend(chunk)
            while b"\n" in pending:
                boundary = pending.index(b"\n")
                line = pending.take_bytes(boundary + 1)[:-1]
                if len(line) > _MAX_LINE:
                    raise ValueError("Subprocess output line exceeds safety limit")
                if progress.full():
                    progress.get_nowait()
                progress.put_nowait(line.decode(errors="replace").strip())
            if len(pending) > _MAX_LINE:
                raise ValueError("Subprocess output line exceeds safety limit")


async def _report(
    progress: asyncio.Queue[str], on_line: Callable[[str], Awaitable[None]] | None
) -> None:
    while True:
        line = await progress.get()
        if on_line is not None:
            try:
                await on_line(line)
            except Exception:
                logger.exception("Subprocess progress delivery failed")


async def _spawn_owned(
    args: Sequence[str],
) -> tuple[asyncio.subprocess.Process, bool]:
    """Finish process acquisition even if its requester is cancelled."""
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=_CREATE_SUSPENDED if os.name == "nt" else 0,
        )
    )
    cancelled = False
    while not spawn.done():
        try:
            await asyncio.shield(spawn)
        except asyncio.CancelledError:
            cancelled = True
    return spawn.result(), cancelled


async def _finish_owned(
    proc: asyncio.subprocess.Process,
    job: WindowsJob | None,
    readers: list[asyncio.Task[None]],
    reporter: asyncio.Task[None] | None,
    primary: BaseException | None,
) -> None:
    cleanup = asyncio.create_task(_terminate(proc, job))
    cancelled = False
    try:
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
    except Exception:
        if primary is None:
            raise
        logger.exception("Subprocess cleanup failed after operation error")
    finally:
        if reporter is not None:
            reporter.cancel()
        for reader in readers:
            reader.cancel()
        for task in [*readers, *([reporter] if reporter is not None else [])]:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Subprocess reader failed", exc_info=True)
    if cancelled and primary is None:
        raise asyncio.CancelledError


async def run_process(
    args: Sequence[str],
    *,
    deadline: float,
    on_line: Callable[[str], Awaitable[None]] | None = None,
    capture: bool = True,
) -> ProcessResult:
    """Drain both pipes independently of optional, coalesced progress delivery."""
    proc, cancelled = await _spawn_owned(args)
    job: WindowsJob | None = None
    output = bytearray()
    tail = bytearray()
    progress: asyncio.Queue[str] = asyncio.Queue(1)
    reporter: asyncio.Task[None] | None = None
    readers: list[asyncio.Task[None]] = []
    primary: BaseException | None = None
    try:
        if os.name == "nt":
            job = WindowsJob(proc.pid)
        if cancelled:
            raise asyncio.CancelledError
        reporter = asyncio.create_task(_report(progress, on_line))
        readers = [
            asyncio.create_task(
                _read(
                    proc.stdout,
                    output=output if capture else None,
                    tail=tail,
                    progress=progress if on_line else None,
                )
            ),
            asyncio.create_task(
                _read(
                    proc.stderr,
                    output=None,
                    tail=tail,
                    progress=progress if on_line else None,
                )
            ),
        ]
        async with asyncio.timeout(deadline):
            await asyncio.gather(*readers)
            code = await proc.wait()
        return ProcessResult(code, output.take_bytes(), tail.decode(errors="replace"))
    except BaseException as exc:
        primary = exc
        raise
    finally:
        await _finish_owned(proc, job, readers, reporter, primary)
