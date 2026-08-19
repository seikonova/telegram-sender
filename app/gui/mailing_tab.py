import customtkinter as ctk
from tkinter import messagebox

from app.core.database import count_recipients, get_account, get_accounts, get_settings
from app.core.mailer import MailerService
from app.core.telegram_client import MailingMode, SendResult, TelegramManager


class MailingTab(ctk.CTkScrollableFrame):
    def __init__(self, master, mailer: MailerService, on_mailing_finished=None, **kwargs):
        super().__init__(master, **kwargs)
        self.mailer = mailer
        self.on_mailing_finished = on_mailing_finished
        self._account_checks: dict[int, ctk.BooleanVar] = {}

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Аккаунты для рассылки:", anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=4, pady=(4, 4)
        )

        acc_controls = ctk.CTkFrame(self, fg_color="transparent")
        acc_controls.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkButton(acc_controls, text="Выбрать все", width=110, command=self._select_all_accounts).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            acc_controls,
            text="Снять все",
            width=110,
            fg_color="#444444",
            hover_color="#555555",
            command=self._deselect_all_accounts,
        ).pack(side="left")

        self.accounts_frame = ctk.CTkFrame(self)
        self.accounts_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.accounts_frame.grid_columnconfigure(0, weight=1)

        mode_frame = ctk.CTkFrame(self, fg_color="transparent")
        mode_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(mode_frame, text="Режим:", font=ctk.CTkFont(weight="bold")).pack(
            side="left", padx=(0, 8)
        )
        self.mode_var = ctk.StringVar(value=MailingMode.SINGLE)
        ctk.CTkRadioButton(
            mode_frame,
            text="По 1 сообщению каждому",
            variable=self.mode_var,
            value=MailingMode.SINGLE,
            command=self._update_mode_hint,
        ).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(
            mode_frame,
            text="С каждого аккаунта каждому",
            variable=self.mode_var,
            value=MailingMode.ALL_ACCOUNTS,
            command=self._update_mode_hint,
        ).pack(side="left")

        self.mode_hint = ctk.CTkLabel(self, text="", text_color="gray", anchor="w", wraplength=700)
        self.mode_hint.grid(row=4, column=0, sticky="w", pady=(0, 8))

        source_frame = ctk.CTkFrame(self, fg_color="transparent")
        source_frame.grid(row=5, column=0, sticky="ew", pady=(0, 6))

        ctk.CTkLabel(source_frame, text="Источник:").pack(side="left", padx=(0, 8))
        self.source_var = ctk.StringVar(value="database")
        ctk.CTkRadioButton(
            source_frame,
            text="База получателей (только ожидающие)",
            variable=self.source_var,
            value="database",
            command=self._toggle_source,
        ).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(
            source_frame,
            text="Вручную",
            variable=self.source_var,
            value="manual",
            command=self._toggle_source,
        ).pack(side="left")

        self.db_info_label = ctk.CTkLabel(self, text="", anchor="w", text_color="#7ec8ff")
        self.db_info_label.grid(row=6, column=0, sticky="ew", pady=(0, 8))

        self.recipients_section = ctk.CTkFrame(self, fg_color="transparent")
        self.recipients_section.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        self.recipients_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.recipients_section,
            text="Список получателей (по одному на строку):",
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.recipients_box = ctk.CTkTextbox(self.recipients_section, height=90)
        self.recipients_box.grid(row=1, column=0, sticky="ew")

        self.message_section = ctk.CTkFrame(self, fg_color="transparent")
        self.message_section.grid(row=8, column=0, sticky="ew", pady=(0, 12))
        self.message_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.message_section,
            text="Текст сообщения:",
            anchor="w",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.message_box = ctk.CTkTextbox(self.message_section, height=140)
        self.message_box.grid(row=1, column=0, sticky="ew")

        controls = ctk.CTkFrame(self)
        controls.grid(row=9, column=0, sticky="ew", pady=(0, 8))
        controls.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(controls, text="Задержка (сек):").grid(row=0, column=0, padx=(8, 6), pady=8)
        self.delay_entry = ctk.CTkEntry(controls, width=80)
        self.delay_entry.grid(row=0, column=1, padx=(0, 12), pady=8)
        self.delay_entry.insert(0, str(get_settings().default_delay))

        self.start_btn = ctk.CTkButton(controls, text="Начать рассылку", command=self._start_mailing)
        self.start_btn.grid(row=0, column=2, padx=8, pady=8, sticky="w")

        self.stop_btn = ctk.CTkButton(
            controls,
            text="Остановить",
            fg_color="#8B0000",
            hover_color="#A52A2A",
            command=self._stop_mailing,
            state="disabled",
        )
        self.stop_btn.grid(row=0, column=3, padx=8, pady=8)

        self.progress_label = ctk.CTkLabel(self, text="Готово к рассылке", anchor="w")
        self.progress_label.grid(row=10, column=0, sticky="ew", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=11, column=0, sticky="ew", pady=(0, 12))
        self.progress_bar.set(0)

        ctk.CTkLabel(self, text="Лог:", anchor="w").grid(row=12, column=0, sticky="w", pady=(0, 6))
        self.log_box = ctk.CTkTextbox(self, height=130, state="disabled")
        self.log_box.grid(row=13, column=0, sticky="ew", pady=(0, 8))

        self.refresh_accounts()
        self._toggle_source()
        self._update_mode_hint()

    def refresh_accounts(self) -> None:
        for widget in self.accounts_frame.winfo_children():
            widget.destroy()
        self._account_checks.clear()

        accounts = get_accounts()
        if not accounts:
            ctk.CTkLabel(
                self.accounts_frame,
                text="Нет аккаунтов — добавьте во вкладке «Аккаунты»",
                text_color="gray",
            ).grid(row=0, column=0, sticky="w", pady=4, padx=4)
            return

        for index, account in enumerate(accounts):
            var = ctk.BooleanVar(value=True)
            self._account_checks[account.id] = var
            label = f"{account.display_name} ({account.phone})"
            ctk.CTkCheckBox(
                self.accounts_frame,
                text=label,
                variable=var,
                command=self._update_mode_hint,
            ).grid(row=index, column=0, sticky="w", pady=2, padx=4)
        self._update_mode_hint()

    def refresh_db_info(self) -> None:
        pending = count_recipients("pending")
        self.db_info_label.configure(
            text=f"В базе ожидают отправки: {pending} получателей"
        )

    def _toggle_source(self) -> None:
        use_db = self.source_var.get() == "database"
        if use_db:
            self.refresh_db_info()
            self.db_info_label.grid()
            self.recipients_section.grid_remove()
        else:
            self.db_info_label.grid_remove()
            self.recipients_section.grid()
        self._update_mode_hint()

    def _update_mode_hint(self) -> None:
        accounts_count = max(sum(1 for v in self._account_checks.values() if v.get()), 1)
        pending = count_recipients("pending")
        mode = self.mode_var.get()

        if mode == MailingMode.SINGLE:
            text = (
                "Каждый получатель получит одно сообщение. "
                "Аккаунты используются по очереди (1-й получатель — 1-й акк., 2-й — 2-й акк. и т.д.)."
            )
            if self.source_var.get() == "database" and pending:
                text += f" Будет отправлено: {pending} сообщений."
        else:
            text = (
                "Каждый выбранный аккаунт отправит сообщение каждому получателю. "
                f"При {accounts_count} акк. и получателях из базы/списка — "
                "число отправок = аккаунты × получатели."
            )
            if self.source_var.get() == "database" and pending:
                total = TelegramManager.calc_total(accounts_count, pending, mode)
                text += f" Сейчас: ~{total} отправок ({accounts_count} × {pending})."
        self.mode_hint.configure(text=text)

    def _select_all_accounts(self) -> None:
        for var in self._account_checks.values():
            var.set(True)

    def _deselect_all_accounts(self) -> None:
        for var in self._account_checks.values():
            var.set(False)

    def _get_selected_accounts(self):
        accounts = []
        for account_id, var in self._account_checks.items():
            if var.get():
                account = get_account(account_id)
                if account:
                    accounts.append(account)
        return accounts

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start_mailing(self) -> None:
        if self.mailer.is_running():
            return

        accounts = self._get_selected_accounts()
        if not accounts:
            messagebox.showerror("Ошибка", "Выберите хотя бы один аккаунт")
            return

        text = self.message_box.get("1.0", "end").strip()
        if not text:
            messagebox.showerror("Ошибка", "Введите текст сообщения")
            return

        try:
            delay = float(self.delay_entry.get().strip() or "5")
            if delay < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Задержка должна быть числом от 1 и выше")
            return

        use_db = self.source_var.get() == "database"
        pending = 0
        recipients: list[str] = []

        if use_db:
            pending = count_recipients("pending")
            if pending == 0:
                messagebox.showerror("Ошибка", "В базе нет ожидающих получателей. Добавьте их во вкладке «База»")
                return
        else:
            recipients = self.mailer.parse_recipients(self.recipients_box.get("1.0", "end"))
            if not recipients:
                messagebox.showerror("Ошибка", "Укажите получателей")
                return

        mode = self.mode_var.get()
        targets_count = pending if use_db else len(recipients)
        total_ops = TelegramManager.calc_total(len(accounts), targets_count, mode)
        mode_name = "1 сообщ./получ." if mode == MailingMode.SINGLE else "все аккаунты"

        if mode == MailingMode.ALL_ACCOUNTS and total_ops > 50:
            if not messagebox.askyesno(
                "Подтверждение",
                f"Будет выполнено {total_ops} отправок ({len(accounts)} акк. × {targets_count} получ.).\n"
                "Продолжить?",
            ):
                return

        acc_names = ", ".join(a.display_name for a in accounts)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_label.configure(
            text=f"Режим: {mode_name} | {total_ops} отправок | {acc_names[:50]}..."
        )
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        def on_progress(current: int, total: int, result: SendResult) -> None:
            self.after(0, lambda: self._handle_progress(current, total, result))

        def on_complete(results: list[SendResult]) -> None:
            self.after(0, lambda: self._handle_complete(results))

        def on_error(error: str) -> None:
            self.after(0, lambda: self._handle_error(error))

        if use_db:
            self.mailer.start_from_database(
                accounts, text, delay, mode, on_progress, on_complete, on_error
            )
        else:
            targets = self.mailer.contacts_to_targets(recipients)
            self.mailer.start_multi(
                accounts,
                targets,
                text,
                delay,
                mode,
                on_progress,
                on_complete,
                on_error,
                update_db=False,
            )

    def _handle_progress(self, current: int, total: int, result: SendResult) -> None:
        status = "OK" if result.success else "ОШИБКА"
        acc = f"[{result.account_label}] " if result.account_label else ""
        self._append_log(f"[{status}] {acc}{result.recipient}: {result.message}")
        self.progress_label.configure(text=f"Отправлено {current} из {total}")
        self.progress_bar.set(current / total if total else 0)

    def _handle_complete(self, results: list[SendResult]) -> None:
        success = sum(1 for r in results if r.success)
        self.progress_label.configure(text=f"Готово: {success}/{len(results)} успешно")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.refresh_db_info()
        if self.on_mailing_finished:
            self.on_mailing_finished()

    def _handle_error(self, error: str) -> None:
        self._append_log(f"[ОШИБКА] {error}")
        self.progress_label.configure(text="Рассылка прервана")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        messagebox.showerror("Ошибка рассылки", error)

    def _stop_mailing(self) -> None:
        self.mailer.stop()
        self._append_log("[INFO] Остановка рассылки...")
        self.stop_btn.configure(state="disabled")
