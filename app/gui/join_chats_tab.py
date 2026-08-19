import customtkinter as ctk
from tkinter import filedialog, messagebox

from app.core.database import get_account, get_accounts, get_settings
from app.core.joiner import JoinService
from app.core.telegram_client import JoinResult


class JoinChatsTab(ctk.CTkScrollableFrame):
    def __init__(self, master, joiner: JoinService, **kwargs):
        super().__init__(master, **kwargs)
        self.joiner = joiner
        self._account_checks: dict[int, ctk.BooleanVar] = {}

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Вступление в чаты",
            anchor="w",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(4, 8))

        ctk.CTkLabel(
            self,
            text="Каждый выбранный аккаунт вступит во все указанные чаты/каналы",
            text_color="gray",
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        ctk.CTkLabel(self, text="Аккаунты:", anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )

        acc_controls = ctk.CTkFrame(self, fg_color="transparent")
        acc_controls.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkButton(acc_controls, text="Выбрать все", width=110, command=self._select_all).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            acc_controls,
            text="Снять все",
            width=110,
            fg_color="#444444",
            hover_color="#555555",
            command=self._deselect_all,
        ).pack(side="left")

        self.accounts_frame = ctk.CTkFrame(self)
        self.accounts_frame.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        self.accounts_frame.grid_columnconfigure(0, weight=1)

        chats_section = ctk.CTkFrame(self, fg_color="transparent")
        chats_section.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        chats_section.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(chats_section, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(
            header,
            text="Чаты и каналы (по одному на строку):",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header,
            text="Из файла",
            width=90,
            fg_color="#444444",
            hover_color="#555555",
            command=self._load_from_file,
        ).pack(side="right")

        ctk.CTkLabel(
            chats_section,
            text="Форматы: @username, t.me/channel, https://t.me/+invite — по одному на строку\nПапки (t.me/addlist/...) импортируйте вручную в Telegram",
            text_color="gray",
            anchor="w",
            wraplength=680,
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        self.chats_box = ctk.CTkTextbox(chats_section, height=140)
        self.chats_box.grid(row=2, column=0, sticky="ew")

        controls = ctk.CTkFrame(self)
        controls.grid(row=6, column=0, sticky="ew", pady=(12, 8))
        controls.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(controls, text="Задержка (сек):").grid(row=0, column=0, padx=(8, 6), pady=8)
        self.delay_entry = ctk.CTkEntry(controls, width=80)
        self.delay_entry.grid(row=0, column=1, padx=(0, 12), pady=8)
        self.delay_entry.insert(0, str(get_settings().default_delay))

        self.start_btn = ctk.CTkButton(controls, text="Вступить в чаты", command=self._start)
        self.start_btn.grid(row=0, column=2, padx=8, pady=8, sticky="w")

        self.stop_btn = ctk.CTkButton(
            controls,
            text="Остановить",
            fg_color="#8B0000",
            hover_color="#A52A2A",
            command=self._stop,
            state="disabled",
        )
        self.stop_btn.grid(row=0, column=3, padx=8, pady=8)

        self.progress_label = ctk.CTkLabel(self, text="Готово", anchor="w")
        self.progress_label.grid(row=7, column=0, sticky="ew", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=8, column=0, sticky="ew", pady=(0, 12))
        self.progress_bar.set(0)

        ctk.CTkLabel(self, text="Лог:", anchor="w").grid(row=9, column=0, sticky="w", pady=(0, 6))
        self.log_box = ctk.CTkTextbox(self, height=150, state="disabled")
        self.log_box.grid(row=10, column=0, sticky="ew", pady=(0, 8))

        self.refresh_accounts()

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
            ctk.CTkCheckBox(self.accounts_frame, text=label, variable=var).grid(
                row=index, column=0, sticky="w", pady=2, padx=4
            )

    def _select_all(self) -> None:
        for var in self._account_checks.values():
            var.set(True)

    def _deselect_all(self) -> None:
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

    def _load_from_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Файл со списком чатов",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(path, encoding="cp1251") as f:
                content = f.read()
        self.chats_box.delete("1.0", "end")
        links = parse_telegram_links(content)
        self.chats_box.insert("1.0", "\n".join(links) if links else content.strip())
        if links:
            messagebox.showinfo("Файл загружен", f"Извлечено ссылок: {len(links)}")

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start(self) -> None:
        if self.joiner.is_running():
            return

        accounts = self._get_selected_accounts()
        if not accounts:
            messagebox.showerror("Ошибка", "Выберите хотя бы один аккаунт")
            return

        chats = self.joiner.parse_chats(self.chats_box.get("1.0", "end"))
        if not chats:
            messagebox.showerror("Ошибка", "Укажите чаты для вступления")
            return

        try:
            delay = float(self.delay_entry.get().strip() or "5")
            if delay < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Задержка должна быть числом от 1 и выше")
            return

        total_ops = len(accounts) * len(chats)
        if not messagebox.askyesno(
            "Подтверждение",
            f"Вступить в {len(chats)} чат(ов) с {len(accounts)} аккаунт(ов)?\n"
            f"Всего операций: {total_ops}",
        ):
            return

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_label.configure(text="Запуск...")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        def on_progress(current: int, total: int, result: JoinResult) -> None:
            self.after(0, lambda: self._on_progress(current, total, result))

        def on_complete(results: list[JoinResult]) -> None:
            self.after(0, lambda: self._on_complete(results))

        def on_error(error: str) -> None:
            self.after(0, lambda: self._on_error(error))

        self.joiner.start(accounts, chats, delay, on_progress, on_complete, on_error)

    def _on_progress(self, current: int, total: int, result: JoinResult) -> None:
        status = "OK" if result.success else "ОШИБКА"
        self._append_log(f"[{status}] [{result.account_label}] {result.chat}: {result.message}")
        self.progress_label.configure(text=f"Выполнено {current} из {total}")
        self.progress_bar.set(current / total if total else 0)

    def _on_complete(self, results: list[JoinResult]) -> None:
        success = sum(1 for r in results if r.success)
        self.progress_label.configure(text=f"Готово: {success}/{len(results)} успешно")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _on_error(self, error: str) -> None:
        self._append_log(f"[ОШИБКА] {error}")
        self.progress_label.configure(text="Прервано")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        messagebox.showerror("Ошибка", error)

    def _stop(self) -> None:
        self.joiner.stop()
        self._append_log("[INFO] Остановка...")
        self.stop_btn.configure(state="disabled")
