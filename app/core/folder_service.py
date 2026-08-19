import re
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.database import Account, ChatFolderTemplate
from app.core.link_parser import parse_telegram_links
from app.core.telegram_client import FolderResult, TelegramManager


@dataclass
class FolderState:
    running: bool = False
    total: int = 0
    results: list[FolderResult] = field(default_factory=list)


class FolderService:
    def __init__(self, manager: TelegramManager) -> None:
        self.manager = manager
        self.state = FolderState()
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = False

    @staticmethod
    def parse_chats(raw: str) -> list[str]:
        return parse_telegram_links(raw)

    def is_running(self) -> bool:
        return self.state.running

    def stop(self) -> None:
        self._stop_requested = True

    def start(
        self,
        accounts: list[Account],
        folders: list[ChatFolderTemplate],
        auto_join: bool,
        delay: float,
        on_progress: Callable[[int, int, FolderResult], None],
        on_complete: Callable[[list[FolderResult]], None],
        on_error: Callable[[str], None],
    ) -> None:
        if self.state.running:
            on_error("Операция уже выполняется")
            return

        total = len(accounts) * len(folders)
        self._stop_requested = False
        self.state = FolderState(running=True, total=total)

        def worker():
            try:
                results = self.manager.apply_chat_folders(
                    accounts=accounts,
                    folders=folders,
                    auto_join=auto_join,
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
