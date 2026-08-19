import re
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.database import (
    Account,
    Recipient,
    get_pending_recipients,
    mark_recipient_failed,
    mark_recipient_sent,
)
from app.core.telegram_client import MailingMode, MailingTarget, SendResult, TelegramManager


@dataclass
class MailingState:
    running: bool = False
    stopped: bool = False
    current: int = 0
    total: int = 0
    results: list[SendResult] = field(default_factory=list)


class MailerService:
    def __init__(self, manager: TelegramManager) -> None:
        self.manager = manager
        self.state = MailingState()
        self._thread: Optional[threading.Thread] = None
        self._stop_requested = False

    @staticmethod
    def parse_recipients(raw: str) -> list[str]:
        parts = re.split(r"[\n,;]+", raw)
        return [part.strip() for part in parts if part.strip()]

    @staticmethod
    def recipients_to_targets(recipients: list[Recipient]) -> list[MailingTarget]:
        return [MailingTarget(contact=r.contact, recipient_id=r.id) for r in recipients]

    @staticmethod
    def contacts_to_targets(contacts: list[str]) -> list[MailingTarget]:
        return [MailingTarget(contact=c) for c in contacts]

    def is_running(self) -> bool:
        return self.state.running

    def stop(self) -> None:
        self._stop_requested = True
        self.state.stopped = True

    def _make_db_callbacks(
        self,
        on_progress: Callable[[int, int, SendResult], None],
        update_db: bool,
        mode: str,
    ) -> tuple[
        Callable[[int, int, SendResult], None],
        Optional[Callable[[int, list[SendResult]], None]],
    ]:
        if not update_db:
            return on_progress, None

        if mode == MailingMode.SINGLE:

            def handler(current: int, total: int, result: SendResult) -> None:
                if result.recipient_id is not None:
                    if result.success and result.account_id is not None:
                        mark_recipient_sent(result.recipient_id, result.account_id)
                    elif not result.success:
                        mark_recipient_failed(
                            result.recipient_id,
                            result.message,
                            result.account_id,
                        )
                on_progress(current, total, result)

            return handler, None

        def on_recipient_complete(recipient_id: int, batch: list[SendResult]) -> None:
            successes = [r for r in batch if r.success]
            if successes:
                last = successes[-1]
                if last.account_id is not None:
                    mark_recipient_sent(recipient_id, last.account_id)
            else:
                last = batch[-1]
                mark_recipient_failed(recipient_id, last.message, last.account_id)

        return on_progress, on_recipient_complete

    def start_multi(
        self,
        accounts: list[Account],
        targets: list[MailingTarget],
        text: str,
        delay: float,
        mode: str,
        on_progress: Callable[[int, int, SendResult], None],
        on_complete: Callable[[list[SendResult]], None],
        on_error: Callable[[str], None],
        update_db: bool = False,
    ) -> None:
        if self.state.running:
            on_error("Рассылка уже выполняется")
            return

        total = TelegramManager.calc_total(len(accounts), len(targets), mode)
        self._stop_requested = False
        self.state = MailingState(running=True, total=total)

        progress, recipient_complete = self._make_db_callbacks(on_progress, update_db, mode)

        def worker():
            try:
                results = self.manager.send_multi(
                    accounts=accounts,
                    targets=targets,
                    text=text,
                    delay=delay,
                    mode=mode,
                    on_progress=progress,
                    stop_flag=lambda: self._stop_requested,
                    on_recipient_complete=recipient_complete,
                )
                self.state.results = results
                on_complete(results)
            except Exception as exc:
                on_error(str(exc))
            finally:
                self.state.running = False

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def start_from_database(
        self,
        accounts: list[Account],
        text: str,
        delay: float,
        mode: str,
        on_progress: Callable[[int, int, SendResult], None],
        on_complete: Callable[[list[SendResult]], None],
        on_error: Callable[[str], None],
    ) -> None:
        pending = get_pending_recipients()
        if not pending:
            on_error("В базе нет ожидающих получателей")
            return
        targets = self.recipients_to_targets(pending)
        self.start_multi(
            accounts,
            targets,
            text,
            delay,
            mode,
            on_progress,
            on_complete,
            on_error,
            update_db=True,
        )

    def start(
        self,
        account: Account,
        recipients: list[str],
        text: str,
        delay: float,
        on_progress: Callable[[int, int, SendResult], None],
        on_complete: Callable[[list[SendResult]], None],
        on_error: Callable[[str], None],
    ) -> None:
        targets = self.contacts_to_targets(recipients)
        self.start_multi(
            [account],
            targets,
            text,
            delay,
            MailingMode.SINGLE,
            on_progress,
            on_complete,
            on_error,
            update_db=False,
        )
