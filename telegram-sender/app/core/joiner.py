import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.database import Account
from app.core.link_parser import parse_telegram_links
from app.core.telegram_client import JoinResult, TelegramManager


@dataclass
class JoinState:
    running: bool = False
    stopped: bool = False
    total: int = 0
    results: list[JoinResult] = field(default_factory=list)


class JoinService:
    def __init__(self, manager: TelegramManager) -> None:
        self.manager = manager
        self.state = JoinState()
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = False

    @staticmethod
    def parse_chats(raw: str) -> list[str]:
        return parse_telegram_links(raw)

    def is_running(self) -> bool:
        return self.state.running

    def stop(self) -> None:
        self._stop_requested = True
        self.state.stopped = True

    def start(
        self,
        accounts: list[Account],
        chats: list[str],
        delay: float,
        on_progress: Callable[[int, int, JoinResult], None],
        on_complete: Callable[[list[JoinResult]], None],
        on_error: Callable[[str], None],
    ) -> None:
        if self.state.running:
            on_error("Вступление уже выполняется")
            return

        if not accounts:
            on_error("Выберите хотя бы один аккаунт")
            return
        if not chats:
            on_error("Укажите хотя бы один чат")
            return

        total = len(accounts) * len(chats)
        self._stop_requested = False
        self.state = JoinState(running=True, total=total)

        def worker():
            try:
                results = self.manager.join_chats(
                    accounts=accounts,
                    chats=chats,
                    delay=delay,
                    on_progress=on_progress,
                    stop_flag=lambda: self._stop_requested,
                )
                self.state.results = results
                on_complete(results)
            except Exception as exc:
                on_error(str(exc))
            finally:
                self.state.running = False

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
