import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.database import Account, update_account_name
from app.core.telegram_client import ProfileResult, ProfileUpdate, TelegramManager


@dataclass
class ProfileState:
    running: bool = False
    results: list[ProfileResult] = field(default_factory=list)


class ProfileService:
    def __init__(self, manager: TelegramManager) -> None:
        self.manager = manager
        self.state = ProfileState()
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = False

    def is_running(self) -> bool:
        return self.state.running

    def stop(self) -> None:
        self._stop_requested = True

    def get_profile(self, account: Account):
        return self.manager.get_profile(account)

    def start(
        self,
        accounts: list[Account],
        update: ProfileUpdate,
        delay: float,
        on_progress: Callable[[int, int, ProfileResult], None],
        on_complete: Callable[[list[ProfileResult]], None],
        on_error: Callable[[str], None],
    ) -> None:
        if self.state.running:
            on_error("Операция уже выполняется")
            return

        self._stop_requested = False
        self.state = ProfileState(running=True)

        def worker():
            try:
                results = self.manager.update_profiles(
                    accounts=accounts,
                    update=update,
                    delay=delay,
                    on_progress=on_progress,
                    stop_flag=lambda: self._stop_requested,
                )
                for result in results:
                    if result.success and result.account_id and update.first_name:
                        update_account_name(result.account_id, update.first_name)
                self.state.results = results
                on_complete(results)
            except Exception as exc:
                on_error(str(exc))
            finally:
                self.state.running = False

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
