import asyncio
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


class AsyncWorker:
    """Один фоновый поток с event loop для всех операций Telethon."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="TelegramWorker", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)
        if not self._loop:
            raise RuntimeError("Не удалось запустить фоновый поток Telegram")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, T], timeout: float = 120) -> T:
        if threading.current_thread() is self._thread:
            raise RuntimeError("Нельзя вызывать run() из фонового потока — используйте await")
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def submit(self, coro: Coroutine[Any, Any, T]) -> "asyncio.Future[T]":
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
