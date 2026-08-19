import customtkinter as ctk
from tkinter import filedialog, messagebox

from app.core.database import (
    delete_chat_folder,
    get_account,
    get_accounts,
    get_chat_folder,
    get_chat_folders,
    save_chat_folder,
)
from app.core.folder_service import FolderService
from app.core.telegram_client import FolderResult


class FoldersTab(ctk.CTkScrollableFrame):
    def __init__(self, master, folder_service: FolderService, **kwargs):
        super().__init__(master, **kwargs)
        self.folder_service = folder_service
        self._account_checks: dict[int, ctk.BooleanVar] = {}
        self._folder_checks: dict[int, ctk.BooleanVar] = {}
        self._editing_id: int | None = None

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Папки чатов",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(4, 4))

        ctk.CTkLabel(
            self,
            text="Создайте шаблон папки и примените его на выбранных аккаунтах в Telegram",
            text_color="gray",
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        form = ctk.CTkFrame(self)
        form.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Название папки:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.name_entry = ctk.CTkEntry(form, placeholder_text="Например: Работа")
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=6)

        ctk.CTkLabel(form, text="Иконка:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.emoji_entry = ctk.CTkEntry(form, width=80, placeholder_text="📁")
        self.emoji_entry.grid(row=1, column=1, sticky="w", padx=8, pady=6)
        self.emoji_entry.insert(0, "📁")

        ctk.CTkLabel(form, text="Чаты в папке:").grid(row=2, column=0, sticky="nw", padx=8, pady=6)
        self.chats_box = ctk.CTkTextbox(form, height=100)
        self.chats_box.grid(row=2, column=1, sticky="ew", padx=8, pady=6)

        ctk.CTkLabel(
            form,
            text="@username, t.me/channel, t.me/+ (приглашение) — по одному на строку\nt.me/addlist/... импортируйте вручную в Telegram перед добавлением",
            text_color="gray",
        ).grid(row=3, column=1, sticky="w", padx=8, pady=(0, 6))

        form_btns = ctk.CTkFrame(form, fg_color="transparent")
        form_btns.grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        ctk.CTkButton(form_btns, text="Сохранить шаблон", command=self._save_template, width=140).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            form_btns,
            text="Очистить форму",
            command=self._clear_form,
            width=120,
            fg_color="#444444",
            hover_color="#555555",
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            form_btns,
            text="Из файла",
            command=self._load_chats_file,
            width=90,
            fg_color="#444444",
            hover_color="#555555",
        ).pack(side="left")

        ctk.CTkLabel(self, text="Сохранённые папки:", font=ctk.CTkFont(weight="bold")).grid(
            row=3, column=0, sticky="w", pady=(0, 6)
        )

        self.folders_list = ctk.CTkFrame(self)
        self.folders_list.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        self.folders_list.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Применить на аккаунтах:", font=ctk.CTkFont(weight="bold")).grid(
            row=5, column=0, sticky="w", pady=(0, 4)
        )

        acc_controls = ctk.CTkFrame(self, fg_color="transparent")
        acc_controls.grid(row=6, column=0, sticky="ew", pady=(0, 4))
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
        self.accounts_frame.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        self.accounts_frame.grid_columnconfigure(0, weight=1)

        self.auto_join_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self,
            text="Автоматически вступать в чаты перед добавлением в папку",
            variable=self.auto_join_var,
        ).grid(row=8, column=0, sticky="w", pady=(0, 8))

        controls = ctk.CTkFrame(self)
        controls.grid(row=9, column=0, sticky="ew", pady=(0, 8))
        controls.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(controls, text="Задержка (сек):").grid(row=0, column=0, padx=(8, 6), pady=8)
        self.delay_entry = ctk.CTkEntry(controls, width=80)
        self.delay_entry.grid(row=0, column=1, padx=(0, 12), pady=8)
        self.delay_entry.insert(0, "3")

        self.apply_btn = ctk.CTkButton(controls, text="Создать папки в Telegram", command=self._apply)
        self.apply_btn.grid(row=0, column=2, padx=8, pady=8, sticky="w")

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
        self.progress_label.grid(row=10, column=0, sticky="ew", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=11, column=0, sticky="ew", pady=(0, 12))
        self.progress_bar.set(0)

        ctk.CTkLabel(self, text="Лог:", anchor="w").grid(row=12, column=0, sticky="w", pady=(0, 6))
        self.log_box = ctk.CTkTextbox(self, height=120, state="disabled")
        self.log_box.grid(row=13, column=0, sticky="ew", pady=(0, 8))

        self.refresh_accounts()
        self.refresh_folders()

    def refresh_accounts(self) -> None:
        for widget in self.accounts_frame.winfo_children():
            widget.destroy()
        self._account_checks.clear()

        accounts = get_accounts()
        if not accounts:
            ctk.CTkLabel(
                self.accounts_frame,
                text="Нет аккаунтов",
                text_color="gray",
            ).grid(row=0, column=0, sticky="w", padx=4, pady=4)
            return

        for index, account in enumerate(accounts):
            var = ctk.BooleanVar(value=True)
            self._account_checks[account.id] = var
            ctk.CTkCheckBox(
                self.accounts_frame,
                text=f"{account.display_name} ({account.phone})",
                variable=var,
            ).grid(row=index, column=0, sticky="w", pady=2, padx=4)

    def refresh_folders(self) -> None:
        for widget in self.folders_list.winfo_children():
            widget.destroy()
        self._folder_checks.clear()

        folders = get_chat_folders()
        if not folders:
            ctk.CTkLabel(self.folders_list, text="Нет сохранённых папок", text_color="gray").grid(
                row=0, column=0, sticky="w", padx=8, pady=8
            )
            return

        for index, folder in enumerate(folders):
            row = ctk.CTkFrame(self.folders_list)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)

            var = ctk.BooleanVar(value=False)
            self._folder_checks[folder.id] = var
            label = f"{folder.emoticon} {folder.name}  ({len(folder.chats)} чатов)"
            ctk.CTkCheckBox(row, text=label, variable=var).grid(row=0, column=0, sticky="w", padx=8, pady=8)

            ctk.CTkButton(
                row,
                text="Изменить",
                width=80,
                fg_color="#444444",
                hover_color="#555555",
                command=lambda fid=folder.id: self._edit_folder(fid),
            ).grid(row=0, column=1, padx=4, pady=6)

            ctk.CTkButton(
                row,
                text="Удалить",
                width=80,
                fg_color="#8B0000",
                hover_color="#A52A2A",
                command=lambda fid=folder.id, fn=folder.name: self._delete_folder(fid, fn),
            ).grid(row=0, column=2, padx=8, pady=6)

    def _clear_form(self) -> None:
        self._editing_id = None
        self.name_entry.delete(0, "end")
        self.emoji_entry.delete(0, "end")
        self.emoji_entry.insert(0, "📁")
        self.chats_box.delete("1.0", "end")

    def _edit_folder(self, folder_id: int) -> None:
        folder = get_chat_folder(folder_id)
        if not folder:
            return
        self._editing_id = folder_id
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, folder.name)
        self.emoji_entry.delete(0, "end")
        self.emoji_entry.insert(0, folder.emoticon)
        self.chats_box.delete("1.0", "end")
        self.chats_box.insert("1.0", "\n".join(folder.chats))

    def _save_template(self) -> None:
        name = self.name_entry.get().strip()
        emoticon = self.emoji_entry.get().strip() or "📁"
        chats = self.folder_service.parse_chats(self.chats_box.get("1.0", "end"))

        try:
            save_chat_folder(name, chats, emoticon)
            self._clear_form()
            self.refresh_folders()
            messagebox.showinfo("Готово", f"Папка «{name}» сохранена ({len(chats)} чатов)")
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))

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

    def _delete_folder(self, folder_id: int, name: str) -> None:
        if not messagebox.askyesno("Удаление", f"Удалить шаблон папки «{name}»?"):
            return
        delete_chat_folder(folder_id)
        self.refresh_folders()

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

    def _get_selected_folders(self):
        folders = []
        for folder_id, var in self._folder_checks.items():
            if var.get():
                folder = get_chat_folder(folder_id)
                if folder:
                    folders.append(folder)
        return folders

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _apply(self) -> None:
        if self.folder_service.is_running():
            return

        accounts = self._get_selected_accounts()
        folders = self._get_selected_folders()

        if not accounts:
            messagebox.showerror("Ошибка", "Выберите хотя бы один аккаунт")
            return
        if not folders:
            messagebox.showerror("Ошибка", "Выберите хотя бы одну сохранённую папку")
            return

        try:
            delay = float(self.delay_entry.get().strip() or "3")
            if delay < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Задержка должна быть числом от 0 и выше")
            return

        total = len(accounts) * len(folders)
        if not messagebox.askyesno(
            "Подтверждение",
            f"Создать {len(folders)} папок на {len(accounts)} аккаунтах?\n"
            f"Всего операций: {total}",
        ):
            return

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_label.configure(text="Запуск...")
        self.apply_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        def on_progress(current: int, total_ops: int, result: FolderResult) -> None:
            self.after(0, lambda: self._on_progress(current, total_ops, result))

        def on_complete(results: list[FolderResult]) -> None:
            self.after(0, lambda: self._on_complete(results))

        def on_error(error: str) -> None:
            self.after(0, lambda: self._on_error(error))

        self.folder_service.start(
            accounts,
            folders,
            self.auto_join_var.get(),
            delay,
            on_progress,
            on_complete,
            on_error,
        )

    def _on_progress(self, current: int, total: int, result: FolderResult) -> None:
        status = "OK" if result.success else "ОШИБКА"
        self._append_log(
            f"[{status}] [{result.account_label}] {result.folder_name}: {result.message}"
        )
        self.progress_label.configure(text=f"Выполнено {current} из {total}")
        self.progress_bar.set(current / total if total else 0)

    def _on_complete(self, results: list[FolderResult]) -> None:
        success = sum(1 for r in results if r.success)
        self.progress_label.configure(text=f"Готово: {success}/{len(results)} успешно")
        self.apply_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _on_error(self, error: str) -> None:
        self._append_log(f"[ОШИБКА] {error}")
        self.progress_label.configure(text="Прервано")
        self.apply_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        messagebox.showerror("Ошибка", error)

    def _stop(self) -> None:
        self.folder_service.stop()
        self._append_log("[INFO] Остановка...")
        self.stop_btn.configure(state="disabled")
