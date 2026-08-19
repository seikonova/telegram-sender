import customtkinter as ctk
from tkinter import messagebox

from app.core.database import get_settings, save_settings


class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        settings = get_settings()

        ctk.CTkLabel(self, text="API ID:", anchor="w").grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))
        self.api_id_entry = ctk.CTkEntry(self, placeholder_text="Число с my.telegram.org")
        self.api_id_entry.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=(16, 8))
        self.api_id_entry.insert(0, settings.api_id)

        ctk.CTkLabel(self, text="API Hash:", anchor="w").grid(row=1, column=0, sticky="w", padx=16, pady=8)
        self.api_hash_entry = ctk.CTkEntry(self, placeholder_text="Строка с my.telegram.org", show="*")
        self.api_hash_entry.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=8)
        self.api_hash_entry.insert(0, settings.api_hash)

        ctk.CTkLabel(self, text="Задержка (сек):", anchor="w").grid(row=2, column=0, sticky="w", padx=16, pady=8)
        self.delay_entry = ctk.CTkEntry(self, placeholder_text="5")
        self.delay_entry.grid(row=2, column=1, sticky="ew", padx=(0, 16), pady=8)
        self.delay_entry.insert(0, str(settings.default_delay))

        info = ctk.CTkLabel(
            self,
            text="Получите API ID и API Hash на https://my.telegram.org → API development tools",
            text_color="gray",
            wraplength=520,
            justify="left",
        )
        info.grid(row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 16))

        self.save_btn = ctk.CTkButton(self, text="Сохранить настройки", command=self._save)
        self.save_btn.grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 16), sticky="w")

    def _save(self) -> None:
        api_id = self.api_id_entry.get().strip()
        api_hash = self.api_hash_entry.get().strip()

        try:
            delay = int(self.delay_entry.get().strip() or "5")
            if delay < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Задержка должна быть целым числом от 1 и выше")
            return

        if not api_id.isdigit():
            messagebox.showerror("Ошибка", "API ID должен быть числом")
            return

        if not api_hash:
            messagebox.showerror("Ошибка", "Укажите API Hash")
            return

        save_settings(api_id, api_hash, delay)
        messagebox.showinfo("Готово", "Настройки сохранены")
