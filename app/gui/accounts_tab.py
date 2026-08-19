import customtkinter as ctk
from tkinter import messagebox, simpledialog

from app.core.database import add_account, delete_account, get_accounts, get_settings, update_account_proxy
from app.core.phone_utils import normalize_phone, session_name_from_phone
from app.core.telegram_client import AlreadyAuthorizedResult, LoginCodeResult, TelegramManager, TwoFactorRequired


class AccountsTab(ctk.CTkFrame):
    def __init__(self, master, manager: TelegramManager, on_accounts_changed=None, **kwargs):
        super().__init__(master, **kwargs)
        self.manager = manager
        self.on_accounts_changed = on_accounts_changed
        self._pending_phone: str | None = None
        self._pending_proxy: str | None = None
        self._busy = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        settings_hint = ctk.CTkLabel(
            self,
            text="",
            text_color="gray",
            wraplength=600,
            justify="left",
        )
        settings_hint.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._update_settings_hint(settings_hint)

        form = ctk.CTkFrame(self)
        form.grid(row=1, column=0, sticky="ew", padx=16, pady=12)
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Добавить аккаунт", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(8, 4)
        )

        hint = ctk.CTkLabel(
            form,
            text="Код приходит в приложение Telegram (чат «Telegram»), а не в SMS. "
            "Номер можно вводить как +7999..., 7999... или 8999...",
            text_color="gray",
            wraplength=580,
            justify="left",
        )
        hint.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        ctk.CTkLabel(form, text="Телефон:").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.phone_entry = ctk.CTkEntry(form, placeholder_text="+79991234567 или 89991234567")
        self.phone_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=8, pady=6)

        ctk.CTkLabel(form, text="Прокси:").grid(row=3, column=0, sticky="w", padx=8, pady=6)
        self.proxy_entry = ctk.CTkEntry(form, placeholder_text="socks5://user:pass@host:port или host:port")
        self.proxy_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=8, pady=6)

        ctk.CTkLabel(form, text="Код из Telegram:").grid(row=4, column=0, sticky="w", padx=8, pady=6)
        self.code_entry = ctk.CTkEntry(form, placeholder_text="12345")
        self.code_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=6)

        btn_row = ctk.CTkFrame(form, fg_color="transparent")
        btn_row.grid(row=4, column=2, padx=8, pady=6)

        self.send_code_btn = ctk.CTkButton(btn_row, text="Отправить код", command=self._send_code, width=120)
        self.send_code_btn.pack(side="left", padx=(0, 4))

        self.send_sms_btn = ctk.CTkButton(
            btn_row,
            text="Через SMS",
            command=lambda: self._send_code(force_sms=True),
            width=100,
            fg_color="#444444",
            hover_color="#555555",
        )
        self.send_sms_btn.pack(side="left")

        ctk.CTkLabel(form, text="Пароль 2FA:").grid(row=5, column=0, sticky="w", padx=8, pady=6)
        self.password_entry = ctk.CTkEntry(form, placeholder_text="Если включена двухфакторная защита", show="*")
        self.password_entry.grid(row=5, column=1, columnspan=2, sticky="ew", padx=8, pady=6)

        self.add_btn = ctk.CTkButton(form, text="Подтвердить и добавить", command=self._confirm_login)
        self.add_btn.grid(row=6, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 4))

        self.status_label = ctk.CTkLabel(form, text="", text_color="#7ec8ff", wraplength=580, justify="left")
        self.status_label.grid(row=7, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        list_frame = ctk.CTkFrame(self)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(list_frame, text="Мои аккаунты", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 8)
        )

        self.accounts_list = ctk.CTkScrollableFrame(list_frame)
        self.accounts_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.accounts_list.grid_columnconfigure(0, weight=1)

        self.refresh()

    def _update_settings_hint(self, label: ctk.CTkLabel) -> None:
        settings = get_settings()
        if settings.api_id and settings.api_hash:
            label.configure(text=f"API настроен (ID: {settings.api_id})", text_color="#6fcf97")
        else:
            label.configure(
                text="Сначала откройте вкладку «Настройки» и укажите API ID и API Hash с my.telegram.org",
                text_color="#f2994a",
            )

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.send_code_btn.configure(state=state)
        self.send_sms_btn.configure(state=state)
        self.add_btn.configure(state=state)
        if status:
            self.status_label.configure(text=status)

    def _get_phone(self) -> str:
        return normalize_phone(self.phone_entry.get())

    def _run_in_background(self, task, on_success, on_error=None) -> None:
        """Запускает блокирующую задачу в фоне, GUI не зависает."""

        def worker():
            try:
                result = task()
                self.after(0, lambda: on_success(result))
            except TwoFactorRequired as exc:
                self.after(0, lambda: self._on_2fa_required(str(exc)))
            except Exception as exc:
                msg = str(exc)
                if on_error:
                    self.after(0, lambda: on_error(msg))
                else:
                    self.after(0, lambda: self._on_error(msg))

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _validate_proxy(self, proxy: str | None) -> str | None:
        if proxy is None:
            return None
        proxy = proxy.strip()
        if not proxy:
            return None

        if "://" in proxy:
            from urllib.parse import urlsplit

            parsed = urlsplit(proxy)
            if not parsed.hostname or not parsed.port:
                raise ValueError("Неверный формат прокси. Ожидается host:port или scheme://user:pass@host:port")
        else:
            if ":" not in proxy:
                raise ValueError("Неверный формат прокси. Ожидается host:port")
            host, port = proxy.rsplit(":", 1)
            if not host or not port.isdigit():
                raise ValueError("Неверный формат прокси. Ожидается host:port")

        return proxy

    def _edit_proxy(self, account_id: int, current_proxy: str | None) -> None:
        prompt = "Введите прокси для аккаунта\n(оставьте пустым для удаления):"
        proxy = simpledialog.askstring("Прокси", prompt, initialvalue=current_proxy or "")
        if proxy is None:
            return

        try:
            proxy = self._validate_proxy(proxy)
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc))
            return

        try:
            update_account_proxy(account_id, proxy)
            self.manager.disconnect_account(account_id)
            self.refresh()
            messagebox.showinfo("Готово", "Прокси для аккаунта сохранено")
            if self.on_accounts_changed:
                self.on_accounts_changed()
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))

    def _get_proxy(self) -> str | None:
        proxy = self.proxy_entry.get().strip()
        return proxy if proxy else None

    def _send_code(self, force_sms: bool = False) -> None:
        if self._busy:
            return

        try:
            phone = self._get_phone()
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc))
            return

        session_name = session_name_from_phone(phone)
        proxy = self._get_proxy()
        self._pending_proxy = proxy
        self._set_busy(True, "Подключение к Telegram... (подождите)")

        self._run_in_background(
            task=lambda: self.manager.start_login(phone, session_name, force_sms=force_sms, proxy=proxy),
            on_success=lambda result: self._on_code_sent(phone, result, force_sms),
        )

    def _on_code_sent(self, phone: str, result, force_sms: bool) -> None:
        self._pending_phone = phone

        if isinstance(result, AlreadyAuthorizedResult):
            self._set_busy(True, "Аккаунт уже авторизован, добавляем...")
            self._run_in_background(
                task=lambda: self._add_account_from_session(phone, result.display_name),
                on_success=lambda name: self._on_account_added(name, phone),
            )
            return

        if isinstance(result, LoginCodeResult):
            if force_sms:
                msg = f"SMS-код отправлен на {phone}"
            elif result.sent_via_app:
                msg = f"Код отправлен в приложение Telegram на номер {phone}. Откройте чат «Telegram»."
            else:
                msg = f"Код отправлен на {phone}"
            self._set_busy(False, msg)
            messagebox.showinfo("Код отправлен", msg)

    def _add_account_from_session(self, phone: str, display_name: str) -> str:
        display_name = self.manager.finalize_authorized_session(phone)
        add_account(phone, session_name_from_phone(phone), display_name, proxy=self._pending_proxy)
        return display_name

    def _confirm_login(self) -> None:
        if self._busy:
            return

        if not self._pending_phone:
            messagebox.showerror("Ошибка", "Сначала нажмите «Отправить код»")
            return

        code = self.code_entry.get().strip()
        if not code:
            messagebox.showerror("Ошибка", "Введите код из Telegram")
            return

        phone = self._pending_phone
        password = self.password_entry.get().strip() or None
        self._set_busy(True, "Проверка кода...")

        def task():
            display_name = self.manager.complete_login(phone, code, password)
            add_account(phone, session_name_from_phone(phone), display_name, proxy=self._pending_proxy)
            return display_name

        self._run_in_background(
            task=task,
            on_success=lambda name: self._on_account_added(name, phone),
        )

    def _on_account_added(self, display_name: str, phone: str) -> None:
        self._pending_phone = None
        self._pending_proxy = None
        self.phone_entry.delete(0, "end")
        self.proxy_entry.delete(0, "end")
        self.code_entry.delete(0, "end")
        self.password_entry.delete(0, "end")
        self._set_busy(False, f"Аккаунт «{display_name}» успешно добавлен")
        self.refresh()
        if self.on_accounts_changed:
            self.on_accounts_changed()
        messagebox.showinfo("Готово", f"Аккаунт {display_name} добавлен")

    def _on_2fa_required(self, message: str) -> None:
        self._set_busy(False, message)
        messagebox.showwarning("Нужен пароль 2FA", message)

    def _on_error(self, message: str) -> None:
        self._set_busy(False, f"Ошибка: {message}")
        messagebox.showerror("Ошибка", message)

    def _delete_account(self, account_id: int, phone: str) -> None:
        if not messagebox.askyesno("Удаление", f"Удалить аккаунт {phone}?"):
            return

        self._set_busy(True, "Удаление аккаунта...")

        def task():
            self.manager.disconnect_account(account_id)
            session_name = delete_account(account_id)
            if session_name:
                self.manager.remove_session_file(session_name)

        self._run_in_background(
            task=task,
            on_success=lambda _: self._on_account_deleted(),
        )

    def _on_account_deleted(self) -> None:
        self._set_busy(False, "")
        self.refresh()
        if self.on_accounts_changed:
            self.on_accounts_changed()

    def refresh(self) -> None:
        for widget in self.accounts_list.winfo_children():
            widget.destroy()

        accounts = get_accounts()
        if not accounts:
            ctk.CTkLabel(self.accounts_list, text="Пока нет добавленных аккаунтов", text_color="gray").grid(
                row=0, column=0, sticky="w", pady=8
            )
            return

        for index, account in enumerate(accounts):
            row = ctk.CTkFrame(self.accounts_list)
            row.grid(row=index, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(0, weight=1)

            label = f"{account.display_name}  ({account.phone})"
            if account.proxy:
                label += f" — {account.proxy}"
            ctk.CTkLabel(row, text=label, anchor="w").grid(row=0, column=0, sticky="w", padx=12, pady=10)

            edit_proxy_btn = ctk.CTkButton(
                row,
                text="Прокси",
                width=90,
                fg_color="#444444",
                hover_color="#555555",
                command=lambda aid=account.id, proxy=account.proxy: self._edit_proxy(aid, proxy),
            )
            edit_proxy_btn.grid(row=0, column=1, padx=12, pady=8)

            delete_btn = ctk.CTkButton(
                row,
                text="Удалить",
                width=90,
                fg_color="#8B0000",
                hover_color="#A52A2A",
                command=lambda aid=account.id, ph=account.phone: self._delete_account(aid, ph),
            )
            delete_btn.grid(row=0, column=2, padx=12, pady=8)
