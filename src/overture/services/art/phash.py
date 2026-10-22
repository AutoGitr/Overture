"""Shared perceptual-hash executor and helpers."""

lazy import asyncio
lazy import logging
lazy import multiprocessing
lazy import signal
lazy import string
lazy from collections.abc import Callable
lazy from concurrent.futures import Executor, ProcessPoolExecutor
lazy from concurrent.futures.process import BrokenProcessPool
lazy from pathlib import Path

lazy from ...config import Settings
lazy from ...utils.phash import (
    PHASH_SIZE,
    compute_phash_from_bytes,
    compute_phash_from_file,
)
lazy from ...utils.threads import owned_thread

PHASH_TIMEOUT_SECONDS = 30.0
# Amortize process startup while periodically releasing retained decoder memory.
PHASH_TASKS_PER_WORKER = 1_000
PHASH_DISTANCE_STEPS = 32
PHASH_HEX_LENGTH = (PHASH_SIZE * PHASH_SIZE) // 4
DISTANCE_SCALE = max(1, (PHASH_SIZE * PHASH_SIZE) // PHASH_DISTANCE_STEPS)
logger = logging.getLogger(__name__)

_HEX_DIGITS = frozenset(string.hexdigits)


def _init_worker() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _execute_hash(function: Callable[..., str], *args: object) -> str:
    # Worker control-flow exceptions must not interrupt the API event loop.
    try:
        return function(*args)
    except (KeyboardInterrupt, SystemExit) as exc:
        raise OSError(f"pHash worker operation interrupted: {exc}") from exc


def _parse_phash(value: str) -> int:
    """Parse the pHash format stored by Overture."""
    if len(value) != PHASH_HEX_LENGTH or any(c not in _HEX_DIGITS for c in value):
        raise ValueError("Invalid pHash fingerprint")
    return int(value, 16)


class PhashService:
    """Owns killable processes for image decoding and CPU-intensive hashing."""

    def __init__(
        self,
        *,
        app_config: Settings,
        executor: Executor | None = None,
    ) -> None:
        """Initialize instance state."""
        self._app_config = app_config
        self._executor = executor
        self._slots = asyncio.Semaphore(app_config.PHASH_WORKERS)
        self._replacement_lock = asyncio.Lock()
        self._work: set[asyncio.Task[str]] = set()
        self._closed = False
        self._unavailable = False

    def _get_executor(self) -> Executor:
        """Return executor."""
        if not self.healthy:
            raise OSError("pHash service is unavailable")
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self._app_config.PHASH_WORKERS,
                max_tasks_per_child=PHASH_TASKS_PER_WORKER,
                initializer=_init_worker,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return self._executor

    @property
    def healthy(self) -> bool:
        """An unused pool is healthy; failed cleanup disables hashing."""
        return not self._closed and not self._unavailable

    async def _retire(self, executor: Executor) -> None:
        async with self._replacement_lock:
            if self._executor is not executor:
                return
            try:
                await owned_thread(self._terminate, executor)
            except Exception:
                self._unavailable = True
                logger.exception("pHash pool cleanup failed; hashing unavailable")
                raise
            self._executor = None

    @staticmethod
    def _terminate(executor: Executor) -> None:
        if isinstance(executor, ProcessPoolExecutor):
            executor.kill_workers()
        executor.shutdown(wait=True, cancel_futures=True)

    async def _run(self, function: Callable[..., str], *args: object) -> str:
        # Retirement shuts down the pool off-loop. Do not submit to it while
        # shutdown is in progress, even if another hash has released a slot.
        async with self._replacement_lock:
            executor = self._get_executor()
        try:
            future = asyncio.get_running_loop().run_in_executor(
                executor, _execute_hash, function, *args
            )
            future.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            async with asyncio.timeout(PHASH_TIMEOUT_SECONDS):
                return await asyncio.shield(future)
        except (BrokenProcessPool, TimeoutError) as exc:
            await self._retire(executor)
            logger.exception("pHash execution failed; retired pool")
            raise OSError("pHash worker failed") from exc

    async def _compute(self, data: bytes, path: str | None) -> str:
        try:
            if not self.healthy:
                raise OSError("pHash service is unavailable")
            if path is not None:
                return await self._run(compute_phash_from_file, path)
            return await self._run(compute_phash_from_bytes, data)
        finally:
            self._slots.release()

    async def _submit(self, *, data: bytes = b"", path: str | None = None) -> str:
        """Hash in a worker slot, owning the work until the executor finishes it.

        Only hashing holds a slot: callers fetch images before submitting, so
        a slow download never keeps a worker idle.
        """
        if not self.healthy:
            raise OSError("pHash service is unavailable")
        await self._slots.acquire()
        task = asyncio.create_task(self._compute(data, path))
        self._work.add(task)
        task.add_done_callback(self._finished)
        return await asyncio.shield(task)

    def _finished(self, task: asyncio.Task[str]) -> None:
        self._work.discard(task)
        if not task.cancelled():
            task.exception()

    async def compute_from_bytes(self, image_bytes: bytes) -> str:
        """Compute a hash under fixed process capacity."""
        return await self._submit(data=image_bytes)

    async def compute_from_file(self, file_path: str) -> str:
        """Hash in the worker without materializing the file in the API."""
        return await self._submit(path=str(Path(file_path)))

    @staticmethod
    def hamming_distance(hash1: str, hash2: str) -> int:
        """Compute a 32-step distance from perceptual hashes."""
        detail_distance = (_parse_phash(hash1) ^ _parse_phash(hash2)).bit_count()
        return (detail_distance + DISTANCE_SCALE - 1) // DISTANCE_SCALE

    @staticmethod
    def is_valid_fingerprint(value: str | None) -> bool:
        """Return whether a stored pHash has the current fingerprint shape."""
        try:
            return value is not None and _parse_phash(value) >= 0
        except ValueError:
            return False

    def shutdown(self) -> None:
        """Prevent admission and terminate owned processes; safe to repeat."""
        self._closed = True
        executor = self._executor
        self._executor = None
        if executor is not None:
            self._terminate(executor)

    async def close(self) -> None:
        """Terminate processes and await every outstanding owner before teardown."""
        self._closed = True
        async with self._replacement_lock:
            await owned_thread(self.shutdown)
        tasks = tuple(self._work)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("pHash operation failed during shutdown")
