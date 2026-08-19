import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox

from app.core.database import get_account, get_accounts
from app.core.profile_service import ProfileService
from app.core.telegram_client import ProfileResult, ProfileUpdate


class ProfileTab(ctk.CTkScrollableFrame):
    def __init__(self, master, profile_service: ProfileService, on_profile_updated=None, **kwargs):
        super().__init__(master, **kwargs)
        self.profile_service = profile_service
        self.on_profile_updated = on_profile_updated
        self._photo_path: str | None = None

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Оформление аккаунта",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(4, 4))

        ctk.CTkLabel(
            self,
            text="Изменение имени, описания, username и фото профиля в Telegram",
            text_color="gray",
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        ctk.CTkLabel(self, text="Аккаунт:", font=ctk.CTkFont(weight="bold")).grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )

        acc_row = ctk.CTkFrame(self, fg_color="transparent")
        acc_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        acc_row.grid_columnconfigure(0, weight=1)

        self.account_var = ctk.StringVar(value="")
        self.account_menu = ctk.CTkOptionMenu(
            acc_row, variable=self.account_var, values=["Нет аккаунтов"], width=300
        )
        self.account_menu.grid(row=0, column=0, sticky="w", padx=(0, 8))

        ctk.CTkButton(
            acc_row,
            text="Загрузить данные",
            width=140,
            fg_color="#444444",
            hover_color="#555555",
            command=self._load_profile,
        ).grid(row=0, column=1)

        form = ctk.CTkFrame(self)
        form.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Имя:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.first_name_entry = ctk.CTkEntry(form, placeholder_text="Оставьте пустым — не менять")
        self.first_name_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=6)

        ctk.CTkLabel(form, text="Фамилия:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.last_name_entry = ctk.CTkEntry(form, placeholder_text="Оставьте пустым — не менять")
        self.last_name_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)

        ctk.CTkLabel(form, text="Username:").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.username_entry = ctk.CTkEntry(form, placeholder_text="@username")
        self.username_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=6)

        ctk.CTkLabel(form, text="О себе:").grid(row=3, column=0, sticky="nw", padx=8, pady=6)
        self.about_box = ctk.CTkTextbox(form, height=80)
        self.about_box.grid(row=3, column=1, sticky="ew", padx=8, pady=6)

        photo_row = ctk.CTkFrame(form, fg_color="transparent")
        photo_row.grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ctk.CTkButton(photo_row, text="Выбрать фото", command=self._pick_photo, width=120).pack(
            side="left", padx=(0, 8)
        )
        self.photo_label = ctk.CTkLabel(photo_row, text="Фото не выбрано", text_color="gray")
        self.photo_label.pack(side="left")

        ctk.CTkLabel(
            self,
            text="Применить на нескольких аккаунтах (одинаковые данные):",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=5, column=0, sticky="w", pady=(0, 4))

        self.multi_frame = ctk.CTkFrame(self)
        self.multi_frame.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        self._multi_checks: dict[int, ctk.BooleanVar] = {}

        controls = ctk.CTkFrame(self)
        controls.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        controls.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(controls, text="Задержка (сек):").grid(row=0, column=0, padx=(8, 6), pady=8)
        self.delay_entry = ctk.CTkEntry(controls, width=80)
        self.delay_entry.grid(row=0, column=1, padx=(0, 12), pady=8)
        self.delay_entry.insert(0, "3")

        self.apply_btn = ctk.CTkButton(controls, text="Применить оформление", command=self._apply)
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
        self.progress_label.grid(row=8, column=0, sticky="ew", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=9, column=0, sticky="ew", pady=(0, 12))
        self.progress_bar.set(0)

        ctk.CTkLabel(self, text="Лог:", anchor="w").grid(row=10, column=0, sticky="w", pady=(0, 6))
        self.log_box = ctk.CTkTextbox(self, height=120, state="disabled")
        self.log_box.grid(row=11, column=0, sticky="ew", pady=(0, 8))

        self._account_map: dict[str, int] = {}
        self.refresh_accounts()

    def refresh_accounts(self) -> None:
        for widget in self.multi_frame.winfo_children():
            widget.destroy()
        self._multi_checks.clear()
        self._account_map.clear()

        accounts = get_accounts()
        if not accounts:
            self.account_menu.configure(values=["Нет аккаунтов"])
            self.account_var.set("Нет аккаунтов")
            ctk.CTkLabel(self.multi_frame, text="Нет аккаунтов", text_color="gray").grid(
                row=0, column=0, sticky="w", padx=4, pady=4
            )
            return

        labels = []
        for index, account in enumerate(accounts):
            label = f"{account.display_name} ({account.phone})"
            labels.append(label)
            self._account_map[label] = account.id

            var = ctk.BooleanVar(value=False)
            self._multi_checks[account.id] = var
            ctk.CTkCheckBox(self.multi_frame, text=label, variable=var).grid(
                row=index, column=0, sticky="w", pady=2, padx=4
            )

        self.account_menu.configure(values=labels)
        self.account_var.set(labels[0])

    def _pick_photo(self) -> None:
        path = filedialog.askopenfilename(
            title="Фото профиля",
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.webp"), ("Все файлы", "*.*")],
        )
        if path:
            self._photo_path = path
            self.photo_label.configure(text=path.split("/")[-1].split("\\")[-1], text_color="#7ec8ff")

    def _build_update(self) -> ProfileUpdate:
        first = self.first_name_entry.get().strip()
        last = self.last_name_entry.get().strip()
        username = self.username_entry.get().strip()
        about = self.about_box.get("1.0", "end").strip()

        return ProfileUpdate(
            first_name=first if first else None,
            last_name=last if last else None,
            about=about if about else None,
            username=username if username else None,
            photo_path=self._photo_path,
        )

    def _load_profile(self) -> None:
        label = self.account_var.get()
        account_id = self._account_map.get(label)
        if not account_id:
            messagebox.showerror("Ошибка", "Выберите аккаунт")
            return

        account = get_account(account_id)
        if not account:
            return

        self.progress_label.configure(text="Загрузка профиля...")

        def worker():
            try:
                data = self.profile_service.get_profile(account)
                self.after(0, lambda: self._fill_form(data))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Ошибка", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_form(self, data) -> None:
        self.first_name_entry.delete(0, "end")
        self.first_name_entry.insert(0, data.first_name)
        self.last_name_entry.delete(0, "end")
        self.last_name_entry.insert(0, data.last_name)
        self.username_entry.delete(0, "end")
        if data.username:
            self.username_entry.insert(0, f"@{data.username}")
        self.about_box.delete("1.0", "end")
        self.about_box.insert("1.0", data.about)
        self.progress_label.configure(text="Данные загружены")

    def _get_target_accounts(self):
        selected = [aid for aid, var in self._multi_checks.items() if var.get()]
        if selected:
            return [get_account(aid) for aid in selected if get_account(aid)]

        label = self.account_var.get()
        account_id = self._account_map.get(label)
        if account_id:
            account = get_account(account_id)
            return [account] if account else []
        return []

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _apply(self) -> None:
        if self.profile_service.is_running():
            return

        accounts = self._get_target_accounts()
        if not accounts:
            messagebox.showerror("Ошибка", "Выберите аккаунт в списке или отметьте чекбоксы")
            return

        update = self._build_update()
        if not any([update.first_name, update.last_name, update.about, update.username, update.photo_path]):
            messagebox.showerror("Ошибка", "Заполните хотя бы одно поле или выберите фото")
            return

        try:
            delay = float(self.delay_entry.get().strip() or "3")
            if delay < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Задержка должна быть числом от 0 и выше")
            return

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.progress_label.configure(text="Применение...")
        self.apply_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

        def on_progress(current: int, total: int, result: ProfileResult) -> None:
            self.after(0, lambda: self._on_progress(current, total, result))

        def on_complete(results: list[ProfileResult]) -> None:
            self.after(0, lambda: self._on_complete(results))

        def on_error(error: str) -> None:
            self.after(0, lambda: self._on_error(error))

        self.profile_service.start(accounts, update, delay, on_progress, on_complete, on_error)

    def _on_progress(self, current: int, total: int, result: ProfileResult) -> None:
        status = "OK" if result.success else "ОШИБКА"
        self._append_log(f"[{status}] [{result.account_label}] {result.message}")
        self.progress_label.configure(text=f"Обработано {current} из {total}")
        self.progress_bar.set(current / total if total else 0)

    def _on_complete(self, results: list[ProfileResult]) -> None:
        success = sum(1 for r in results if r.success)
        self.progress_label.configure(text=f"Готово: {success}/{len(results)} успешно")
        self.apply_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if self.on_profile_updated:
            self.on_profile_updated()
        messagebox.showinfo("Готово", f"Обновлено аккаунтов: {success}/{len(results)}")

    def _on_error(self, error: str) -> None:
        self._append_log(f"[ОШИБКА] {error}")
        self.apply_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        messagebox.showerror("Ошибка", error)

    def _stop(self) -> None:
        self.profile_service.stop()
        self._append_log("[INFO] Остановка...")
        self.stop_btn.configure(state="disabled")
