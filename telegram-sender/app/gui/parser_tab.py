import customtkinter as ctk
from tkinter import messagebox, filedialog
import threading

from app.core.database import get_accounts, get_account, get_settings, import_recipients, get_recipients
from app.core.link_parser import parse_telegram_links
from app.core.telegram_client import TelegramManager


class ParserTab(ctk.CTkScrollableFrame):
    def __init__(self, master, manager: TelegramManager, **kwargs):
        super().__init__(master, **kwargs)
        self.manager = manager
        self._account_checks: dict[int, ctk.BooleanVar] = {}

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Парсер членов чатов",
            anchor="w",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(4, 8))

        ctk.CTkLabel(
            self,
            text="Извлеките список участников из чата/канала и сохраните как потенциальных клиентов",
            text_color="gray",
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        # Выбор аккаунтов
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

        accounts = get_accounts()
        if not accounts:
            ctk.CTkLabel(
                self.accounts_frame, text="Нет аккаунтов", text_color="gray"
            ).grid(row=0, column=0, sticky="w", pady=4)
        else:
            for index, account in enumerate(accounts):
                var = ctk.BooleanVar(value=True)
                self._account_checks[account.id] = var
                label = f"{account.display_name} ({account.phone})"
                ctk.CTkCheckBox(self.accounts_frame, text=label, variable=var).grid(
                    row=index, column=0, sticky="w", pady=2, padx=4
                )

        # Чаты для парсинга
        chats_section = ctk.CTkFrame(self, fg_color="transparent")
        chats_section.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        chats_section.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(chats_section, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(
            header,
            text="Чаты для парсинга (по одному на строку):",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            header,
            text="Из файла",
            width=90,
            fg_color="#444444",
            hover_color="#555555",
            command=self._load_chats_file,
        ).pack(side="right")

        ctk.CTkLabel(
            chats_section,
            text="Форматы: @channel, t.me/channel, https://t.me/+invite — по одному на строку\nПапки (t.me/addlist/...) импортируйте вручную в Telegram",
            text_color="gray",
            anchor="w",
            wraplength=680,
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        self.chats_box = ctk.CTkTextbox(chats_section, height=100)
        self.chats_box.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        # Параметры парсинга
        controls = ctk.CTkFrame(self)
        controls.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(controls, text="Лимит/чат:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.limit_entry = ctk.CTkEntry(controls, width=100)
        self.limit_entry.grid(row=0, column=1, sticky="w", padx=8, pady=8)
        self.limit_entry.insert(0, "1000")

        ctk.CTkLabel(controls, text="Задержка (сек):").grid(row=0, column=2, sticky="w", padx=8, pady=8)
        self.delay_entry = ctk.CTkEntry(controls, width=100)
        self.delay_entry.grid(row=0, column=3, sticky="w", padx=8, pady=8)
        self.delay_entry.insert(0, "5")

        # Фильтры
        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.grid(row=7, column=0, sticky="w", pady=(0, 12))

        self.skip_bots_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            filters,
            text="Пропускать ботов",
            variable=self.skip_bots_var,
        ).pack(side="left", padx=(0, 16))

        self.balance_load_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            filters,
            text="Распределить нагрузку между аккаунтами",
            variable=self.balance_load_var,
        ).pack(side="left")

        # Кнопки управления
        btns_frame = ctk.CTkFrame(self)
        btns_frame.grid(row=8, column=0, sticky="ew", pady=(0, 12))

        self.parse_btn = ctk.CTkButton(btns_frame, text="Парсить", command=self._start_parse, width=140)
        self.parse_btn.pack(side="left", padx=(0, 8))

        self.parse_by_messages_btn = ctk.CTkButton(
            btns_frame,
            text="По сообщениям",
            command=self._start_parse_by_messages,
            width=140,
            fg_color="#444444",
            hover_color="#555555",
        )
        self.parse_by_messages_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            btns_frame,
            text="Остановить",
            fg_color="#8B0000",
            hover_color="#A52A2A",
            command=self._stop_parse,
            state="disabled",
            width=140,
        )
        self.stop_btn.pack(side="left", padx=(0, 8))

        self.save_btn = ctk.CTkButton(
            btns_frame,
            text="Сохранить в базу",
            command=self._save_to_db,
            state="disabled",
            width=140,
        )
        self.save_btn.pack(side="left")

        # Результаты
        ctk.CTkLabel(self, text="Найдено участников:", anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=9, column=0, sticky="w", pady=(8, 4)
        )

        self.result_label = ctk.CTkLabel(self, text="0", anchor="w")
        self.result_label.grid(row=10, column=0, sticky="w", pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=11, column=0, sticky="ew", pady=(0, 12))
        self.progress_bar.set(0)

        # Лог
        ctk.CTkLabel(self, text="Лог парсинга:", anchor="w").grid(
            row=12, column=0, sticky="w", pady=(0, 4)
        )

        self.log_box = ctk.CTkTextbox(self, height=80, state="disabled")
        self.log_box.grid(row=13, column=0, sticky="ew", pady=(0, 8))

        # Текстовое поле со списком участников
        ctk.CTkLabel(self, text="Участники (ID или username):", anchor="w").grid(
            row=14, column=0, sticky="w", pady=(0, 4)
        )

        self.members_box = ctk.CTkTextbox(self, height=150)
        self.members_box.grid(row=15, column=0, sticky="ew", pady=(0, 8))

        self.members_list = []
        self._parsing = False
        self._stop_requested = False

        # ============ Парсер чатов аккаунта ============
        ctk.CTkLabel(
            self,
            text="Парсер чатов аккаунта",
            anchor="w",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=16, column=0, sticky="w", padx=4, pady=(16, 8))

        ctk.CTkLabel(
            self,
            text="Извлеките список всех чатов/каналов на аккаунте с юзернеймами",
            text_color="gray",
            anchor="w",
        ).grid(row=17, column=0, sticky="w", pady=(0, 12))

        # Выбор аккаунта для парсинга чатов
        ctk.CTkLabel(self, text="Аккаунт:", anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=18, column=0, sticky="w", pady=(0, 4)
        )

        accounts_list = [(acc.display_name + f" ({acc.phone})", acc.id) for acc in get_accounts()]
        self._chats_accounts_list = accounts_list
        self._chats_account_by_name = {name: acc_id for name, acc_id in accounts_list}
        
        self.chats_account_dropdown = None
        if accounts_list:
            self.chats_account_dropdown = ctk.CTkComboBox(
                self,
                values=[name for name, _ in accounts_list],
                state="readonly",
                height=32,
            )
            self.chats_account_dropdown.set(accounts_list[0][0])
            self.chats_account_dropdown.grid(row=19, column=0, sticky="ew", pady=(0, 12))
        else:
            ctk.CTkLabel(
                self, text="Нет аккаунтов", text_color="gray"
            ).grid(row=19, column=0, sticky="w", pady=(0, 12))

        # Кнопки управления для парсинга чатов
        chats_btns = ctk.CTkFrame(self)
        chats_btns.grid(row=20, column=0, sticky="ew", pady=(0, 12))

        self.parse_chats_btn = ctk.CTkButton(
            chats_btns, text="Получить чаты", command=self._start_parse_chats, width=140
        )
        self.parse_chats_btn.pack(side="left", padx=(0, 8))

        self.stop_chats_btn = ctk.CTkButton(
            chats_btns,
            text="Остановить",
            fg_color="#8B0000",
            hover_color="#A52A2A",
            command=self._stop_parse_chats,
            state="disabled",
            width=140,
        )
        self.stop_chats_btn.pack(side="left", padx=(0, 8))

        self.copy_chats_btn = ctk.CTkButton(
            chats_btns,
            text="Копировать юзернеймы",
            command=self._copy_chats_usernames,
            state="disabled",
            width=180,
        )
        self.copy_chats_btn.pack(side="left")

        # Результаты парсинга чатов
        ctk.CTkLabel(self, text="Найдено чатов:", anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=21, column=0, sticky="w", pady=(8, 4)
        )

        self.chats_result_label = ctk.CTkLabel(self, text="0", anchor="w")
        self.chats_result_label.grid(row=22, column=0, sticky="w", pady=(0, 8))

        self.chats_progress_bar = ctk.CTkProgressBar(self)
        self.chats_progress_bar.grid(row=23, column=0, sticky="ew", pady=(0, 12))
        self.chats_progress_bar.set(0)

        # Лог парсинга чатов
        ctk.CTkLabel(self, text="Лог получения чатов:", anchor="w").grid(
            row=24, column=0, sticky="w", pady=(0, 4)
        )

        self.chats_log_box = ctk.CTkTextbox(self, height=60, state="disabled")
        self.chats_log_box.grid(row=25, column=0, sticky="ew", pady=(0, 8))

        # Результаты парсинга чатов (список с юзернеймами)
        ctk.CTkLabel(self, text="Чаты с юзернеймами:", anchor="w").grid(
            row=26, column=0, sticky="w", pady=(0, 4)
        )

        self.chats_box_result = ctk.CTkTextbox(self, height=150)
        self.chats_box_result.grid(row=27, column=0, sticky="ew", pady=(0, 8))

        self._parsing_chats = False
        self._stop_chats_requested = False
        self._parsed_chats_list: list[dict] = []

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

    def _load_chats_file(self) -> None:
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
        self.chats_box.insert("1.0", content.strip())

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start_parse(self) -> None:
        self._run_parse(False)

    def _start_parse_by_messages(self) -> None:
        self._run_parse(True)

    def _run_parse(self, by_messages: bool) -> None:
        if self._parsing:
            messagebox.showwarning("Ошибка", "Парсинг уже выполняется")
            return

        accounts = self._get_selected_accounts()
        if not accounts:
            messagebox.showerror("Ошибка", "Выберите хотя бы один аккаунт")
            return

        chats_raw = self.chats_box.get("1.0", "end").strip()
        if not chats_raw:
            messagebox.showerror("Ошибка", "Укажите хотя бы один чат")
            return

        # Парсим список чатов
        chats = parse_telegram_links(chats_raw)
        if not chats:
            messagebox.showerror("Ошибка", "Не найдены чаты в предоставленном тексте")
            return

        try:
            limit = int(self.limit_entry.get().strip() or "1000")
            delay = float(self.delay_entry.get().strip() or "5")
        except ValueError:
            messagebox.showerror("Ошибка", "Лимит и задержка должны быть числами")
            return

        self._parsing = True
        self._stop_requested = False
        self.parse_btn.configure(state="disabled")
        self.parse_by_messages_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.save_btn.configure(state="disabled")
        self.result_label.configure(text="Парсинг запущен...")
        self.members_box.configure(state="normal")
        self.members_box.delete("1.0", "end")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.members_list = []
        self.progress_bar.set(0)

        def worker():
            try:
                skip_bots = self.skip_bots_var.get()
                balance_load = self.balance_load_var.get()
                all_members = []
                seen = set()

                total_chats = len(chats)
                current_account_idx = 0
                parse_name = "ПО СООБЩЕНИЯМ" if by_messages else "ПАРС"

                for chat_idx, chat in enumerate(chats):
                    if self._stop_requested:
                        break

                    # Распределяем чаты по аккаунтам
                    if balance_load and len(accounts) > 1:
                        account = accounts[current_account_idx % len(accounts)]
                        current_account_idx += 1
                    else:
                        account = accounts[0]

                    chat = chat.strip()
                    if not chat:
                        continue

                    self.after(0, lambda c=chat, p=parse_name: self._append_log(f"[{p}] {c}..."))

                    try:
                        if by_messages:
                            members = self.manager.parse_chat_members_by_messages(
                                account,
                                chat,
                                limit=limit,
                                skip_bots=skip_bots,
                                on_progress=lambda curr, tot: None,
                                stop_flag=lambda: self._stop_requested,
                            )
                        else:
                            members = self.manager.parse_chat_members(
                                account,
                                chat,
                                limit=limit,
                                skip_bots=skip_bots,
                                on_progress=lambda curr, tot: None,
                                stop_flag=lambda: self._stop_requested,
                            )

                        for member in members:
                            if member.lower() not in seen:
                                seen.add(member.lower())
                                all_members.append(member)

                        msg = f"✓ {chat}: {len(members)} участников (всего: {len(all_members)})"
                        self.after(0, lambda m=msg: self._append_log(m))
                    except Exception as exc:
                        err_msg = f"✗ {chat}: {str(exc)}"
                        self.after(0, lambda e=err_msg: self._append_log(e))

                    # Задержка между чатами
                    if chat_idx < total_chats - 1 and not self._stop_requested:
                        import time
                        time.sleep(delay)

                    # Обновляем прогресс
                    progress = (chat_idx + 1) / total_chats
                    self.after(0, lambda p=progress, m=len(all_members): self._update_progress(p, m))

                self.members_list = all_members
                self.after(0, lambda: self._on_parse_complete(all_members))
            except Exception as exc:
                self.after(0, lambda: self._on_parse_error(str(exc)))
            finally:
                self._parsing = False

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_parse_progress(self, current: int, total: int) -> None:
        self.after(0, lambda: self._update_progress(None, current))

    def _update_progress(self, progress: float = None, members_count: int = None) -> None:
        if progress is not None:
            self.progress_bar.set(progress)
        if members_count is not None:
            self.result_label.configure(text=f"Найдено {members_count} участников...")

    def _on_parse_complete(self, members: list[str]) -> None:
        self.result_label.configure(text=f"Найдено: {len(members)} участников")
        self.progress_bar.set(1.0)
        self.members_box.configure(state="normal")
        self.members_box.insert("1.0", "\n".join(members))
        self.members_box.configure(state="disabled")
        self.parse_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.save_btn.configure(state="normal")
        self._append_log(f"[ГОТОВО] Найдено {len(members)} участников")
        messagebox.showinfo("Готово", f"Найдено {len(members)} участников")

    def _on_parse_error(self, error: str) -> None:
        self.result_label.configure(text="Ошибка при парсинге")
        self.parse_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._append_log(f"[ОШИБКА] {error}")
        messagebox.showerror("Ошибка", error)

    def _stop_parse(self) -> None:
        self._stop_requested = True
        self.stop_btn.configure(state="disabled")

    def _save_to_db(self) -> None:
        if not self.members_list:
            messagebox.showwarning("Ошибка", "Нет участников для сохранения")
            return

        try:
            added, skipped = import_recipients(self.members_list)
            messagebox.showinfo("Готово", f"Добавлено {added} новых участников\n(пропущено {skipped} дубликатов)")
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Ошибка при сохранении: {str(exc)}")
            return

        self.members_list = []
        self.members_box.configure(state="normal")
        self.members_box.delete("1.0", "end")
        self.members_box.configure(state="disabled")
        self.result_label.configure(text="0")
        self.save_btn.configure(state="disabled")

    def _start_parse_chats(self) -> None:
        if self._parsing_chats:
            messagebox.showwarning("Ошибка", "Получение чатов уже выполняется")
            return

        if not self._chats_accounts_list or not self.chats_account_dropdown:
            messagebox.showerror("Ошибка", "Нет аккаунтов для получения чатов")
            return

        # Получаем выбранный аккаунт
        selected_text = self.chats_account_dropdown.get()
        if not selected_text:
            messagebox.showerror("Ошибка", "Выберите аккаунт")
            return

        account_id = self._chats_account_by_name.get(selected_text)
        if not account_id:
            messagebox.showerror("Ошибка", "Неверный аккаунт")
            return

        account = get_account(account_id)
        if not account:
            messagebox.showerror("Ошибка", "Аккаунт не найден")
            return

        self._parsing_chats = True
        self._stop_chats_requested = False
        self.parse_chats_btn.configure(state="disabled")
        self.stop_chats_btn.configure(state="normal")
        self.copy_chats_btn.configure(state="disabled")
        self.chats_result_label.configure(text="Получение чатов...")
        self.chats_box_result.configure(state="normal")
        self.chats_box_result.delete("1.0", "end")
        self.chats_log_box.configure(state="normal")
        self.chats_log_box.delete("1.0", "end")
        self.chats_log_box.configure(state="disabled")
        self._parsed_chats_list = []
        self.chats_progress_bar.set(0)

        def worker():
            try:
                account_label = f"{account.display_name} ({account.phone})"
                self.after(0, lambda: self._append_chats_log(f"[НАЧАЛО] Получение чатов {account_label}..."))

                chats = self.manager.get_account_chats(
                    account,
                    on_progress=lambda curr: self.after(0, lambda c=curr: self._update_chats_progress(c))
                )

                self._parsed_chats_list = chats
                self.after(0, lambda c=chats: self._on_parse_chats_complete(c))
            except Exception as exc:
                self.after(0, lambda: self._on_parse_chats_error(str(exc)))
            finally:
                self._parsing_chats = False

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _append_chats_log(self, text: str) -> None:
        self.chats_log_box.configure(state="normal")
        self.chats_log_box.insert("end", text + "\n")
        self.chats_log_box.see("end")
        self.chats_log_box.configure(state="disabled")

    def _update_chats_progress(self, current: int) -> None:
        if current > 0:
            self.chats_progress_bar.set(min(current / 100, 1.0))

    def _on_parse_chats_complete(self, chats: list[dict]) -> None:
        self.chats_result_label.configure(text=f"Найдено: {len(chats)} чатов")
        self.chats_progress_bar.set(1.0)

        # Форматируем результаты
        result_lines = []
        for chat in chats:
            if chat["username"]:
                result_lines.append(f"@{chat['username']}")
            else:
                result_lines.append(f"t.me/{chat['title'].replace(' ', '_')} (ID: {chat['id']})")

        self.chats_box_result.configure(state="normal")
        self.chats_box_result.insert("1.0", "\n".join(result_lines))
        self.chats_box_result.configure(state="disabled")

        self.parse_chats_btn.configure(state="normal")
        self.stop_chats_btn.configure(state="disabled")
        self.copy_chats_btn.configure(state="normal")
        self._append_chats_log(f"[ГОТОВО] Найдено {len(chats)} чатов")
        messagebox.showinfo("Готово", f"Найдено {len(chats)} чатов")

    def _on_parse_chats_error(self, error: str) -> None:
        self.chats_result_label.configure(text="Ошибка при получении чатов")
        self.parse_chats_btn.configure(state="normal")
        self.stop_chats_btn.configure(state="disabled")
        self._append_chats_log(f"[ОШИБКА] {error}")
        messagebox.showerror("Ошибка", error)

    def _stop_parse_chats(self) -> None:
        self._stop_chats_requested = True
        self.stop_chats_btn.configure(state="disabled")

    def _copy_chats_usernames(self) -> None:
        content = self.chats_box_result.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("Ошибка", "Нет чатов для копирования")
            return

        try:
            self.clipboard_clear()
            self.clipboard_append(content)
            messagebox.showinfo("Готово", "Список чатов скопирован в буфер обмена")
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Ошибка при копировании: {str(exc)}")
