import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlsplit

from telethon import TelegramClient, utils as tg_utils
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.channels import GetParticipantsRequest, JoinChannelRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    GetDialogFiltersRequest,
    ImportChatInviteRequest,
    UpdateDialogFilterRequest,
)
from telethon.tl.functions.photos import UploadProfilePhotoRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import Channel, Chat, ChatInviteAlready, DialogFilter, TextWithEntities, User, ChannelParticipantsRecent
from telethon.errors import (
    ApiIdInvalidError,
    ChannelInvalidError,
    ChannelPrivateError,
    ChannelsTooMuchError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    UserAlreadyParticipantError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UsernameOccupiedError,
)

from app.config import SESSIONS_DIR
from app.core.async_worker import AsyncWorker
from app.core.database import Account, ChatFolderTemplate, Settings, get_settings


class TwoFactorRequired(Exception):
    """Код верный, нужен пароль 2FA — сессия сохраняется для повторной попытки."""


class MailingMode:
    SINGLE = "single"
    ALL_ACCOUNTS = "all_accounts"


@dataclass
class MailingTarget:
    contact: str
    recipient_id: int | None = None


@dataclass
class SendResult:
    recipient: str
    success: bool
    message: str
    account_label: str = ""
    account_id: int | None = None
    recipient_id: int | None = None


@dataclass
class JoinResult:
    chat: str
    success: bool
    message: str
    account_label: str = ""
    account_id: int | None = None


@dataclass
class FolderResult:
    folder_name: str
    success: bool
    message: str
    account_label: str = ""
    account_id: int | None = None


@dataclass
class ProfileData:
    first_name: str
    last_name: str
    about: str
    username: str


@dataclass
class ProfileUpdate:
    first_name: str | None = None
    last_name: str | None = None
    about: str | None = None
    username: str | None = None
    photo_path: str | None = None


@dataclass
class ProfileResult:
    success: bool
    message: str
    account_label: str = ""
    account_id: int | None = None


@dataclass
class LoginCodeResult:
    phone_code_hash: str
    sent_via_app: bool


@dataclass
class AlreadyAuthorizedResult:
    display_name: str


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ApiIdInvalidError):
        return "Неверный API ID или API Hash. Проверьте данные на my.telegram.org"
    if isinstance(exc, PhoneNumberInvalidError):
        return "Неверный номер телефона. Используйте формат +79991234567"
    if isinstance(exc, PhoneNumberBannedError):
        return "Этот номер заблокирован в Telegram"
    if isinstance(exc, PhoneNumberFloodError):
        return "Слишком много попыток. Подождите несколько часов и попробуйте снова"
    if isinstance(exc, PhoneCodeInvalidError):
        return "Неверный код. Проверьте код из Telegram (не из SMS)"
    if isinstance(exc, PhoneCodeExpiredError):
        return "Код истёк. Нажмите «Отправить код» ещё раз"
    if isinstance(exc, PasswordHashInvalidError):
        return "Неверный пароль 2FA"
    if isinstance(exc, FloodWaitError):
        return f"Telegram просит подождать {exc.seconds} сек. перед следующей попыткой"
    if isinstance(exc, TwoFactorRequired):
        return str(exc)
    return str(exc) or exc.__class__.__name__


def _parse_proxy(proxy: str | None) -> tuple | None:
    if not proxy:
        return None

    proxy = proxy.strip()
    if not proxy:
        return None

    if "://" in proxy:
        parsed = urlsplit(proxy)
        proxy_type = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
    else:
        proxy_type = "socks5"
        if ":" not in proxy:
            raise ValueError("Прокси должен быть задан как host:port или scheme://user:pass@host:port")
        host, port_str = proxy.rsplit(":", 1)
        username = None
        password = None
        try:
            port = int(port_str)
        except ValueError:
            raise ValueError("Неверный порт в прокси")

    if proxy_type not in ("socks5", "socks4", "http", "https"):
        raise ValueError("Недопустимый прокси: используйте socks5://, socks4://, http:// или https://")
    if not host or port is None:
        raise ValueError("Прокси должен содержать хост и порт")

    proxy_options = (proxy_type, host, port, True)
    if username or password:
        proxy_options = (proxy_type, host, port, True, username, password)
    return proxy_options


def _friendly_join_error(exc: Exception) -> str:
    if isinstance(exc, UserAlreadyParticipantError):
        return "Уже состоит в чате"
    if isinstance(exc, InviteHashExpiredError):
        return "Ссылка-приглашение истекла"
    if isinstance(exc, InviteHashInvalidError):
        return "Неверная ссылка-приглашение"
    if isinstance(exc, ChannelPrivateError):
        return "Чат закрытый или нужно приглашение"
    if isinstance(exc, ChannelInvalidError):
        return "Чат не найден"
    if isinstance(exc, UsernameNotOccupiedError):
        return "Username не существует"
    if isinstance(exc, UsernameInvalidError):
        return "Неверный username"
    if isinstance(exc, FloodWaitError):
        return f"FloodWait: подождите {exc.seconds} сек."
    if isinstance(exc, ChannelsTooMuchError):
        return "Достигнут лимит каналов/групп в Telegram"
    return _friendly_error(exc)


def _friendly_profile_error(exc: Exception) -> str:
    if isinstance(exc, UsernameOccupiedError):
        return "Username уже занят"
    if isinstance(exc, UsernameInvalidError):
        return "Неверный username"
    if isinstance(exc, FloodWaitError):
        return f"FloodWait: подождите {exc.seconds} сек."
    return _friendly_error(exc)


class TelegramManager:
    def __init__(self) -> None:
        self._worker = AsyncWorker()
        self._clients: dict[int, TelegramClient] = {}
        self._pending_auth: dict[str, TelegramClient] = {}
        self._pending_code_hash: dict[str, str] = {}

    def _session_path(self, session_name: str) -> str:
        return str(SESSIONS_DIR / session_name)

    def _validate_api(self, settings: Settings) -> None:
        if not settings.api_id or not settings.api_hash:
            raise ValueError("Сначала укажите API ID и API Hash во вкладке «Настройки» (my.telegram.org)")

    def _make_client(
        self,
        session_name: str,
        settings: Optional[Settings] = None,
        proxy: str | None = None,
    ) -> TelegramClient:
        settings = settings or get_settings()
        self._validate_api(settings)
        proxy_options = _parse_proxy(proxy)
        return TelegramClient(
            self._session_path(session_name),
            int(settings.api_id),
            settings.api_hash,
            proxy=proxy_options,
        )

    async def _disconnect_client(self, client: TelegramClient) -> None:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass

    async def _cleanup_pending(self, phone: str) -> None:
        old = self._pending_auth.pop(phone, None)
        self._pending_code_hash.pop(phone, None)
        if old and old not in self._clients.values():
            await self._disconnect_client(old)

    async def _get_client(self, account: Account) -> TelegramClient:
        if account.id in self._clients:
            return self._clients[account.id]

        client = self._make_client(account.session_name, proxy=account.proxy)
        await client.connect()

        if not await client.is_user_authorized():
            await self._disconnect_client(client)
            raise ValueError(f"Аккаунт {account.phone} не авторизован. Удалите и добавьте заново.")

        self._clients[account.id] = client
        return client

    def disconnect_account(self, account_id: int) -> None:
        async def _do():
            client = self._clients.pop(account_id, None)
            if client:
                await self._disconnect_client(client)

        self._worker.run(_do())

    def disconnect_all(self) -> None:
        async def _do():
            for account_id in list(self._clients):
                client = self._clients.pop(account_id, None)
                if client:
                    await self._disconnect_client(client)

        self._worker.run(_do())

    def shutdown(self) -> None:
        try:
            self.disconnect_all()
        finally:
            self._worker.stop()

    def start_login(
        self,
        phone: str,
        session_name: str,
        force_sms: bool = False,
        proxy: str | None = None,
    ) -> LoginCodeResult | AlreadyAuthorizedResult:
        async def _do() -> LoginCodeResult | AlreadyAuthorizedResult:
            await self._cleanup_pending(phone)

            client = self._make_client(session_name, proxy=proxy)
            await client.connect()

            try:
                if await client.is_user_authorized():
                    me = await client.get_me()
                    name = me.first_name or me.username or phone
                    self._pending_auth[phone] = client
                    return AlreadyAuthorizedResult(display_name=name)

                result = await client.send_code_request(phone, force_sms=force_sms)
                self._pending_auth[phone] = client
                self._pending_code_hash[phone] = result.phone_code_hash
                return LoginCodeResult(
                    phone_code_hash=result.phone_code_hash,
                    sent_via_app=not force_sms,
                )
            except Exception:
                await self._disconnect_client(client)
                self._pending_auth.pop(phone, None)
                self._pending_code_hash.pop(phone, None)
                raise

        try:
            return self._worker.run(_do(), timeout=60)
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(_friendly_error(exc)) from exc

    def complete_login(self, phone: str, code: str, password: Optional[str] = None) -> str:
        code = code.strip().replace(" ", "").replace("-", "")
        if not code.isdigit():
            raise ValueError("Код должен состоять только из цифр")

        async def _do() -> str:
            client = self._pending_auth.get(phone)
            phone_code_hash = self._pending_code_hash.get(phone)
            if not client or not phone_code_hash:
                raise ValueError("Сначала нажмите «Отправить код» для этого номера")

            if await client.is_user_authorized():
                me = await client.get_me()
                display_name = me.first_name or me.username or phone
            else:
                try:
                    await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
                except SessionPasswordNeededError:
                    if not password:
                        raise TwoFactorRequired(
                            "Введите пароль 2FA в поле ниже и нажмите «Подтвердить» снова"
                        )
                    await client.sign_in(password=password)

                me = await client.get_me()
                display_name = me.first_name or me.username or phone

            await self._disconnect_client(client)
            self._pending_auth.pop(phone, None)
            self._pending_code_hash.pop(phone, None)
            return display_name

        try:
            return self._worker.run(_do(), timeout=60)
        except TwoFactorRequired:
            raise
        except Exception as exc:
            if isinstance(exc, (ValueError, TwoFactorRequired)):
                raise
            if isinstance(exc, (PhoneCodeExpiredError, PhoneCodeInvalidError)):
                self._worker.run(self._invalidate_code(phone))
            raise ValueError(_friendly_error(exc)) from exc

    async def _invalidate_code(self, phone: str) -> None:
        self._pending_code_hash.pop(phone, None)

    def finalize_authorized_session(self, phone: str) -> str:
        async def _do() -> str:
            client = self._pending_auth.get(phone)
            if not client:
                raise ValueError("Сессия не найдена")
            me = await client.get_me()
            display_name = me.first_name or me.username or phone
            await self._cleanup_pending(phone)
            return display_name

        return self._worker.run(_do(), timeout=30)

    def cancel_login(self, phone: str) -> None:
        self._worker.run(self._cleanup_pending(phone))

    def send_bulk(
        self,
        account: Account,
        recipients: list[str],
        text: str,
        delay: float,
        on_progress: Optional[Callable[[int, int, SendResult], None]] = None,
        stop_flag: Callable[[], bool] = lambda: False,
    ) -> list[SendResult]:
        targets = [MailingTarget(contact=r) for r in recipients]

        async def _do() -> list[SendResult]:
            return await self._send_messages_multi(
                [account],
                targets,
                text,
                delay,
                MailingMode.SINGLE,
                on_progress,
                stop_flag,
            )

        return self._worker.run(_do(), timeout=3600)

    async def _send_one_message(
        self,
        client: TelegramClient,
        account: Account,
        target: MailingTarget,
        text: str,
    ) -> SendResult:
        contact = target.contact.strip()
        label = f"{account.display_name} ({account.phone})"
        try:
            await client.send_message(contact, text)
            return SendResult(
                recipient=contact,
                success=True,
                message="Отправлено",
                account_label=label,
                account_id=account.id,
                recipient_id=target.recipient_id,
            )
        except FloodWaitError as exc:
            return SendResult(
                recipient=contact,
                success=False,
                message=f"FloodWait: подождите {exc.seconds} сек.",
                account_label=label,
                account_id=account.id,
                recipient_id=target.recipient_id,
            )
        except Exception as exc:
            return SendResult(
                recipient=contact,
                success=False,
                message=str(exc),
                account_label=label,
                account_id=account.id,
                recipient_id=target.recipient_id,
            )

    async def _send_messages_multi(
        self,
        accounts: list[Account],
        targets: list[MailingTarget],
        text: str,
        delay: float,
        mode: str,
        on_progress: Optional[Callable[[int, int, SendResult], None]],
        stop_flag: Callable[[], bool],
        on_recipient_complete: Optional[Callable[[int, list[SendResult]], None]] = None,
    ) -> list[SendResult]:
        results: list[SendResult] = []
        clients: dict[int, TelegramClient] = {}

        async def get_client(account: Account) -> TelegramClient:
            if account.id not in clients:
                clients[account.id] = await self._get_client(account)
            return clients[account.id]

        if mode == MailingMode.ALL_ACCOUNTS:
            total = len(accounts) * len(targets)
            step = 0
            for target in targets:
                if stop_flag():
                    break
                contact = target.contact.strip()
                if not contact:
                    continue

                batch: list[SendResult] = []
                for account in accounts:
                    if stop_flag():
                        break

                    step += 1
                    client = await get_client(account)
                    result = await self._send_one_message(client, account, target, text)

                    if not result.success and "FloodWait" in result.message:
                        results.append(result)
                        batch.append(result)
                        if on_progress:
                            on_progress(step, total, result)
                        seconds = int(result.message.split()[-2])
                        await asyncio.sleep(seconds)
                        continue

                    results.append(result)
                    batch.append(result)
                    if on_progress:
                        on_progress(step, total, result)

                    if step < total and not stop_flag():
                        await asyncio.sleep(delay)

                if on_recipient_complete and target.recipient_id is not None:
                    on_recipient_complete(target.recipient_id, batch)

            return results

        total = len(targets)
        for index, target in enumerate(targets, start=1):
            if stop_flag():
                break

            contact = target.contact.strip()
            if not contact:
                continue

            account = accounts[(index - 1) % len(accounts)]
            client = await get_client(account)
            result = await self._send_one_message(client, account, target, text)

            if not result.success and "FloodWait" in result.message:
                results.append(result)
                if on_progress:
                    on_progress(index, total, result)
                seconds = int(result.message.split()[-2])
                await asyncio.sleep(seconds)
                continue

            results.append(result)
            if on_progress:
                on_progress(index, total, result)

            if on_recipient_complete and target.recipient_id is not None:
                on_recipient_complete(target.recipient_id, [result])

            if index < total and not stop_flag():
                await asyncio.sleep(delay)

        return results

    @staticmethod
    def calc_total(accounts_count: int, targets_count: int, mode: str) -> int:
        if mode == MailingMode.ALL_ACCOUNTS:
            return accounts_count * targets_count
        return targets_count

    def send_multi(
        self,
        accounts: list[Account],
        targets: list[MailingTarget],
        text: str,
        delay: float,
        mode: str = MailingMode.SINGLE,
        on_progress: Optional[Callable[[int, int, SendResult], None]] = None,
        stop_flag: Callable[[], bool] = lambda: False,
        on_recipient_complete: Optional[Callable[[int, list[SendResult]], None]] = None,
    ) -> list[SendResult]:
        if not accounts:
            raise ValueError("Выберите хотя бы один аккаунт")
        if not targets:
            raise ValueError("Нет получателей для рассылки")

        async def _do() -> list[SendResult]:
            return await self._send_messages_multi(
                accounts,
                targets,
                text,
                delay,
                mode,
                on_progress,
                stop_flag,
                on_recipient_complete,
            )

        return self._worker.run(_do(), timeout=7200)

    @staticmethod
    def _peer_key(peer) -> tuple:
        if hasattr(peer, "user_id") and peer.user_id:
            return ("user", peer.user_id)
        if hasattr(peer, "channel_id") and peer.channel_id:
            return ("channel", peer.channel_id)
        if hasattr(peer, "chat_id") and peer.chat_id:
            return ("chat", peer.chat_id)
        return (type(peer).__name__, str(peer))

    async def _resolve_folder_peers(
        self,
        client: TelegramClient,
        chats: list[str],
        auto_join: bool,
    ) -> tuple[list, list[str]]:
        peers = []
        skipped: list[str] = []

        for chat in chats:
            chat = chat.strip()
            if not chat:
                continue
            try:
                entity = None
                
                # Если это приглашительная ссылка, сначала вступаем
                username, is_invite = tg_utils.parse_username(chat)
                if (is_invite or auto_join) and (is_invite or "t.me/+" in chat.lower()):
                    try:
                        entity = await self._join_chat(client, chat)
                        # Даём время на синхронизацию
                        await asyncio.sleep(1)
                    except UserAlreadyParticipantError:
                        pass
                    except Exception:
                        if not auto_join:
                            raise
                
                # Если ещё не получили entity, пытаемся получить по имени
                if entity is None:
                    if auto_join and not is_invite:
                        try:
                            entity = await self._join_chat(client, chat)
                        except UserAlreadyParticipantError:
                            pass
                
                # Если всё ещё нет entity, получаем его просто по имени/ID
                if entity is None:
                    entity = await client.get_entity(chat)
                
                peers.append(await client.get_input_entity(entity))
            except Exception as exc:
                skipped.append(f"{chat}: {_friendly_join_error(exc)}")

        return peers, skipped

    async def _find_folder_id(self, client: TelegramClient, name: str) -> int | None:
        response = await client(GetDialogFiltersRequest())
        for item in response.filters:
            if isinstance(item, DialogFilter):
                title = item.title.text if hasattr(item.title, "text") else str(item.title)
                if title == name:
                    return item.id
        return None

    async def _next_folder_id(self, client: TelegramClient) -> int:
        response = await client(GetDialogFiltersRequest())
        used = {
            item.id for item in response.filters if hasattr(item, "id") and isinstance(item, DialogFilter)
        }
        for folder_id in range(2, 21):
            if folder_id not in used:
                return folder_id
        raise ValueError("Достигнут лимит папок в Telegram (максимум ~10)")

    async def _create_folder_on_account(
        self,
        client: TelegramClient,
        folder: ChatFolderTemplate,
        auto_join: bool,
        merge_existing: bool,
    ) -> str:
        peers, skipped = await self._resolve_folder_peers(client, folder.chats, auto_join)
        if not peers:
            raise ValueError("Не удалось добавить ни одного чата. Вступите в чаты или включите автовступление")

        folder_id = await self._find_folder_id(client, folder.name)
        include_peers = list(peers)

        if folder_id is None:
            folder_id = await self._next_folder_id(client)
        elif merge_existing:
            response = await client(GetDialogFiltersRequest())
            for item in response.filters:
                if isinstance(item, DialogFilter) and item.id == folder_id:
                    seen = {self._peer_key(p) for p in peers}
                    for peer in item.include_peers:
                        key = self._peer_key(peer)
                        if key not in seen:
                            include_peers.append(peer)
                            seen.add(key)
                    break

        dialog_filter = DialogFilter(
            id=folder_id,
            title=TextWithEntities(text=folder.name, entities=[]),
            pinned_peers=[],
            include_peers=include_peers,
            exclude_peers=[],
            emoticon=folder.emoticon or "📁",
        )
        await client(UpdateDialogFilterRequest(id=folder_id, filter=dialog_filter))

        message = f"Папка создана ({len(include_peers)} чатов)"
        if skipped:
            message += f", пропущено: {len(skipped)}"
        return message

    async def _apply_folders_multi(
        self,
        accounts: list[Account],
        folders: list[ChatFolderTemplate],
        auto_join: bool,
        delay: float,
        on_progress: Optional[Callable[[int, int, FolderResult], None]],
        stop_flag: Callable[[], bool],
    ) -> list[FolderResult]:
        results: list[FolderResult] = []
        total = len(accounts) * len(folders)
        step = 0
        clients: dict[int, TelegramClient] = {}

        for account in accounts:
            if stop_flag():
                break

            label = f"{account.display_name} ({account.phone})"
            if account.id not in clients:
                clients[account.id] = await self._get_client(account)
            client = clients[account.id]

            for folder in folders:
                if stop_flag():
                    break

                step += 1
                try:
                    message = await self._create_folder_on_account(
                        client, folder, auto_join=auto_join, merge_existing=True
                    )
                    result = FolderResult(
                        folder_name=folder.name,
                        success=True,
                        message=message,
                        account_label=label,
                        account_id=account.id,
                    )
                except FloodWaitError as exc:
                    result = FolderResult(
                        folder_name=folder.name,
                        success=False,
                        message=f"FloodWait: подождите {exc.seconds} сек.",
                        account_label=label,
                        account_id=account.id,
                    )
                    results.append(result)
                    if on_progress:
                        on_progress(step, total, result)
                    await asyncio.sleep(exc.seconds)
                    continue
                except Exception as exc:
                    result = FolderResult(
                        folder_name=folder.name,
                        success=False,
                        message=str(exc),
                        account_label=label,
                        account_id=account.id,
                    )

                results.append(result)
                if on_progress:
                    on_progress(step, total, result)

                if step < total and not stop_flag():
                    await asyncio.sleep(delay)

        return results

    def apply_chat_folders(
        self,
        accounts: list[Account],
        folders: list[ChatFolderTemplate],
        auto_join: bool = True,
        delay: float = 3,
        on_progress: Optional[Callable[[int, int, FolderResult], None]] = None,
        stop_flag: Callable[[], bool] = lambda: False,
    ) -> list[FolderResult]:
        if not accounts:
            raise ValueError("Выберите хотя бы один аккаунт")
        if not folders:
            raise ValueError("Выберите хотя бы одну папку")

        async def _do() -> list[FolderResult]:
            return await self._apply_folders_multi(
                accounts, folders, auto_join, delay, on_progress, stop_flag
            )

        return self._worker.run(_do(), timeout=7200)

    def remove_session_file(self, session_name: str) -> None:
        base = SESSIONS_DIR / session_name
        for path in [base, Path(f"{base}.session"), Path(f"{base}.session-journal")]:
            if path.exists():
                path.unlink()

    @staticmethod
    def _entity_from_updates(updates) -> object | None:
        chats = getattr(updates, "chats", None)
        if chats:
            return chats[0]
        return None

    async def _join_chat(self, client: TelegramClient, chat: str):
        chat = chat.strip()
        
        # Проверяем на addlist ссылку (папка чатов) — требует ручного импорта
        if "addlist/" in chat.lower():
            raise ValueError(
                "Это ссылка на папку чатов. Откройте её в Telegram вручную:\n"
                f"{chat}\n\n"
                "После этого чаты из папки будут доступны в вашем Telegram."
            )
        
        username, is_invite = tg_utils.parse_username(chat)

        if is_invite and username:
            try:
                updates = await client(ImportChatInviteRequest(username))
            except UserAlreadyParticipantError:
                invite = await client(CheckChatInviteRequest(username))
                if isinstance(invite, ChatInviteAlready):
                    return invite.chat
                raise
            
            entity = self._entity_from_updates(updates)
            if entity:
                return entity
            
            # Если entity не получен из updates, пытаемся получить через get_dialogs
            # (бывает задержка синхронизации)
            try:
                dialogs = await client.get_dialogs(limit=100)
                for dialog in dialogs:
                    dialog_entity = dialog.entity
                    if hasattr(dialog_entity, "username") and dialog_entity.username:
                        if dialog_entity.username.lower() == username.lower():
                            return dialog_entity
                    if hasattr(dialog_entity, "title"):
                        if chat.lower() in dialog_entity.title.lower():
                            return dialog_entity
            except Exception:
                pass
            
            raise ValueError("Не удалось вступить по ссылке-приглашению")

        lookup = username or chat.lstrip("@")
        entity = await client.get_entity(lookup)

        if isinstance(entity, Channel):
            try:
                await client(JoinChannelRequest(entity))
            except UserAlreadyParticipantError:
                return entity
            return entity

        if isinstance(entity, Chat):
            raise ValueError("Обычная группа — нужна ссылка-приглашение t.me/+...")

        raise ValueError("Это не канал/группа. Укажите @channel или ссылку t.me/...")

    async def _get_profile(self, client: TelegramClient) -> ProfileData:
        me = await client.get_me()
        full = await client(GetFullUserRequest(me))
        return ProfileData(
            first_name=me.first_name or "",
            last_name=me.last_name or "",
            about=getattr(full.full_user, "about", None) or "",
            username=me.username or "",
        )

    async def _update_profile_on_client(
        self, client: TelegramClient, update: ProfileUpdate
    ) -> str:
        parts: list[str] = []

        if update.first_name is not None or update.last_name is not None or update.about is not None:
            await client(
                UpdateProfileRequest(
                    first_name=update.first_name,
                    last_name=update.last_name,
                    about=update.about,
                )
            )
            if update.first_name is not None:
                parts.append("имя")
            if update.last_name is not None:
                parts.append("фамилия")
            if update.about is not None:
                parts.append("описание")

        if update.username is not None:
            username = update.username.strip().lstrip("@")
            await client(UpdateUsernameRequest(username=username))
            parts.append("username")

        if update.photo_path:
            path = Path(update.photo_path)
            if not path.exists():
                raise ValueError(f"Файл не найден: {update.photo_path}")
            uploaded = await client.upload_file(str(path))
            await client(UploadProfilePhotoRequest(file=uploaded))
            parts.append("фото")

        if not parts:
            raise ValueError("Укажите хотя бы одно поле для изменения")

        return "Обновлено: " + ", ".join(parts)

    def get_profile(self, account: Account) -> ProfileData:
        async def _do() -> ProfileData:
            client = await self._get_client(account)
            return await self._get_profile(client)

        return self._worker.run(_do(), timeout=60)

    def update_profiles(
        self,
        accounts: list[Account],
        update: ProfileUpdate,
        delay: float,
        on_progress: Optional[Callable[[int, int, ProfileResult], None]] = None,
        stop_flag: Callable[[], bool] = lambda: False,
    ) -> list[ProfileResult]:
        async def _do() -> list[ProfileResult]:
            results: list[ProfileResult] = []
            total = len(accounts)

            for index, account in enumerate(accounts, start=1):
                if stop_flag():
                    break

                label = f"{account.display_name} ({account.phone})"
                try:
                    client = await self._get_client(account)
                    message = await self._update_profile_on_client(client, update)
                    result = ProfileResult(
                        success=True,
                        message=message,
                        account_label=label,
                        account_id=account.id,
                    )
                except FloodWaitError as exc:
                    result = ProfileResult(
                        success=False,
                        message=f"FloodWait: подождите {exc.seconds} сек.",
                        account_label=label,
                        account_id=account.id,
                    )
                    results.append(result)
                    if on_progress:
                        on_progress(index, total, result)
                    await asyncio.sleep(exc.seconds)
                    continue
                except Exception as exc:
                    result = ProfileResult(
                        success=False,
                        message=_friendly_profile_error(exc),
                        account_label=label,
                        account_id=account.id,
                    )

                results.append(result)
                if on_progress:
                    on_progress(index, total, result)

                if index < total and not stop_flag():
                    await asyncio.sleep(delay)

            return results

        return self._worker.run(_do(), timeout=3600)

    async def _join_chats_multi(
        self,
        accounts: list[Account],
        chats: list[str],
        delay: float,
        on_progress: Optional[Callable[[int, int, JoinResult], None]],
        stop_flag: Callable[[], bool],
    ) -> list[JoinResult]:
        results: list[JoinResult] = []
        total = len(accounts) * len(chats)
        step = 0
        clients: dict[int, TelegramClient] = {}

        for account in accounts:
            if stop_flag():
                break

            label = f"{account.display_name} ({account.phone})"
            if account.id not in clients:
                clients[account.id] = await self._get_client(account)
            client = clients[account.id]

            for chat in chats:
                if stop_flag():
                    break

                chat = chat.strip()
                if not chat:
                    continue

                step += 1
                try:
                    entity = await self._join_chat(client, chat)
                    title = getattr(entity, "title", None) or getattr(entity, "username", None) or chat
                    result = JoinResult(
                        chat=chat,
                        success=True,
                        message=f"Вступил: {title}",
                        account_label=label,
                        account_id=account.id,
                    )
                except UserAlreadyParticipantError:
                    result = JoinResult(
                        chat=chat,
                        success=True,
                        message="Уже состоит в чате",
                        account_label=label,
                        account_id=account.id,
                    )
                except FloodWaitError as exc:
                    result = JoinResult(
                        chat=chat,
                        success=False,
                        message=f"FloodWait: подождите {exc.seconds} сек.",
                        account_label=label,
                        account_id=account.id,
                    )
                    results.append(result)
                    if on_progress:
                        on_progress(step, total, result)
                    await asyncio.sleep(exc.seconds)
                    continue
                except Exception as exc:
                    result = JoinResult(
                        chat=chat,
                        success=False,
                        message=_friendly_join_error(exc),
                        account_label=label,
                        account_id=account.id,
                    )

                results.append(result)
                if on_progress:
                    on_progress(step, total, result)

                if step < total and not stop_flag():
                    await asyncio.sleep(delay)

        return results

    def join_chats(
        self,
        accounts: list[Account],
        chats: list[str],
        delay: float,
        on_progress: Optional[Callable[[int, int, JoinResult], None]] = None,
        stop_flag: Callable[[], bool] = lambda: False,
    ) -> list[JoinResult]:
        if not accounts:
            raise ValueError("Выберите хотя бы один аккаунт")
        if not chats:
            raise ValueError("Укажите хотя бы один чат")

        async def _do() -> list[JoinResult]:
            return await self._join_chats_multi(
                accounts, chats, delay, on_progress, stop_flag
            )

        return self._worker.run(_do(), timeout=7200)

    async def _parse_members_async(
        self,
        client: TelegramClient,
        chat: str,
        limit: int,
        skip_bots: bool,
        on_progress: Optional[Callable[[int, int], None]],
        stop_flag: Callable[[], bool],
    ) -> list[str]:
        members: list[str] = []
        seen: set[str] = set()

        try:
            entity = await client.get_entity(chat)
        except Exception as exc:
            username, is_invite = tg_utils.parse_username(chat)
            if is_invite and username:
                try:
                    await self._join_chat(client, chat)
                    entity = await client.get_entity(chat)
                except Exception as join_exc:
                    raise ValueError(f"Чат не найден: {str(join_exc)}")
            else:
                raise ValueError(f"Чат не найден: {str(exc)}")

        if not hasattr(entity, "id"):
            raise ValueError("Это не группа или канал")

        if isinstance(entity, Channel) and not getattr(entity, "megagroup", False):
            raise ValueError(
                "Это канал, список подписчиков недоступен для парсинга. "
                "Парсер работает только с группами/супергруппами."
            )

        if hasattr(entity, "broadcast") and getattr(entity, "broadcast", False) and not getattr(entity, "megagroup", False):
            raise ValueError(
                "Это классический канал, у Telegram API нет доступа к списку подписчиков."
            )

        try:
            return await self._parse_members_from_participants_async(
                client, entity, limit, skip_bots, on_progress, stop_flag
            )
        except Exception as participants_exc:
            try:
                return await self._parse_members_from_messages_async(
                    client, entity, limit, skip_bots, on_progress, stop_flag
                )
            except Exception as messages_exc:
                raise ValueError(
                    f"Парсинг участников не удался: {participants_exc}. "
                    f"Попытка по сообщениям тоже не удалась: {messages_exc}"
                ) from messages_exc

    async def _parse_members_from_participants_async(
        self,
        client: TelegramClient,
        entity,
        limit: int,
        skip_bots: bool,
        on_progress: Optional[Callable[[int, int], None]],
        stop_flag: Callable[[], bool],
    ) -> list[str]:
        members: list[str] = []
        seen: set[str] = set()
        total_fetched = 0

        async for user in client.iter_participants(entity, limit=limit if limit > 0 else None):
            if stop_flag():
                break

            if skip_bots and getattr(user, "bot", False):
                continue

            if getattr(user, "username", None):
                member_id = f"@{user.username}"
            elif hasattr(user, "id"):
                member_id = str(user.id)
            else:
                continue

            if member_id not in seen:
                seen.add(member_id)
                members.append(member_id)

            total_fetched += 1
            if on_progress:
                on_progress(len(members), total_fetched)

            if limit > 0 and len(members) >= limit:
                break

        if not members:
            raise ValueError(
                "Не удалось получить участников. Возможно, это канал, вы не участник или чат закрыт для просмотра списка участников."
            )

        return members

    async def _parse_members_from_messages_async(
        self,
        client: TelegramClient,
        entity,
        limit: int,
        skip_bots: bool,
        on_progress: Optional[Callable[[int, int], None]],
        stop_flag: Callable[[], bool],
    ) -> list[str]:
        members: list[str] = []
        seen: set[str] = set()
        total_fetched = 0

        # Парсим участников по последним 2000 сообщениям чата
        message_limit = 2000
        async for message in client.iter_messages(entity, limit=message_limit):
            if stop_flag():
                break

            sender = None
            try:
                sender = await message.get_sender()
            except Exception:
                sender = getattr(message, "sender", None)

            if not sender or not isinstance(sender, User) or not hasattr(sender, "id"):
                continue

            if skip_bots and getattr(sender, "bot", False):
                continue

            if getattr(sender, "username", None):
                member_id = f"@{sender.username}"
            else:
                member_id = str(sender.id)

            if member_id not in seen:
                seen.add(member_id)
                members.append(member_id)

            total_fetched += 1
            if on_progress:
                on_progress(len(members), total_fetched)

            if limit > 0 and len(members) >= limit:
                break

        if not members:
            raise ValueError(
                "Не удалось получить участников по сообщениям. Возможно, чат закрыт или сообщений недостаточно."
            )

        return members

    def parse_chat_members(
        self,
        account: Account,
        chat: str,
        limit: int = 1000,
        skip_bots: bool = True,
        on_progress: Optional[Callable[[int, int], None]] = None,
        stop_flag: Callable[[], bool] = lambda: False,
    ) -> list[str]:
        async def _do() -> list[str]:
            client = await self._get_client(account)
            return await self._parse_members_async(client, chat, limit, skip_bots, on_progress, stop_flag)

        return self._worker.run(_do(), timeout=3600)

    def parse_chat_members_by_messages(
        self,
        account: Account,
        chat: str,
        limit: int = 1000,
        skip_bots: bool = True,
        on_progress: Optional[Callable[[int, int], None]] = None,
        stop_flag: Callable[[], bool] = lambda: False,
    ) -> list[str]:
        async def _do() -> list[str]:
            client = await self._get_client(account)
            entity = await self._resolve_chat_entity_async(client, chat)
            return await self._parse_members_from_messages_async(
                client, entity, limit, skip_bots, on_progress, stop_flag
            )

        return self._worker.run(_do(), timeout=3600)

    async def _resolve_chat_entity_async(
        self, client: TelegramClient, chat: str
    ):
        try:
            return await client.get_entity(chat)
        except Exception as exc:
            username, is_invite = tg_utils.parse_username(chat)
            if is_invite and username:
                try:
                    await self._join_chat(client, chat)
                    return await client.get_entity(chat)
                except Exception as join_exc:
                    raise ValueError(f"Чат не найден: {str(join_exc)}")
            raise ValueError(f"Чат не найден: {str(exc)}")

    async def _get_account_chats_async(
        self,
        client: TelegramClient,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> list[dict]:
        """Получает список всех чатов/каналов на аккаунте с их юзернеймами."""
        chats: list[dict] = []
        
        try:
            dialogs = await client.get_dialogs(limit=None)
            total = len(dialogs)
            
            for index, dialog in enumerate(dialogs, start=1):
                entity = dialog.entity
                
                # Пропускаем личные чаты и чаты без имени
                if not hasattr(entity, "title"):
                    continue
                
                chat_info: dict = {
                    "title": entity.title or "",
                    "username": "",
                    "id": entity.id,
                }
                
                # Извлекаем юзернейм если есть
                if hasattr(entity, "username") and entity.username:
                    chat_info["username"] = entity.username
                
                chats.append(chat_info)
                
                if on_progress:
                    on_progress(index)
        
        except Exception as exc:
            raise ValueError(f"Ошибка при получении чатов: {str(exc)}")
        
        return chats

    def get_account_chats(
        self,
        account: Account,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> list[dict]:
        """Получает список чатов на аккаунте."""
        async def _do() -> list[dict]:
            client = await self._get_client(account)
            return await self._get_account_chats_async(client, on_progress)

        return self._worker.run(_do(), timeout=600)
