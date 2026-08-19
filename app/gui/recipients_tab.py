import customtkinter as ctk
from tkinter import filedialog, messagebox

from app.core.database import (
    clear_recipients,
    count_recipients,
    delete_recipient,
    get_recipient_stats,
    get_recipients,
    import_recipients,
    reset_failed_recipients,
)
from app.core.mailer import MailerService


class RecipientsTab(ctk.CTkFrame):
    def __init__(self, master, mailer: MailerService, **kwargs):
        super().__init__(master, **kwargs)
        self.mailer = mailer
        self._filter = "all"

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="База получателей", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", pady=(8, 4)
        )

        self.stats_label = ctk.CTkLabel(top, text="", text_color="gray", anchor="w")
        self.stats_label.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(
            self,
            text="Вставьте контакты (по одному на строку: @username, номер или ID):",
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))

        self.import_box = ctk.CTkTextbox(self, height=100)
        self.import_box.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))

        ctk.CTkButton(btn_row, text="Добавить в базу", command=self._import_text, width=140).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            btn_row,
            text="Загрузить из файла",
            command=self._import_file,
            width=150,
            fg_color="#444444",
            hover_color="#555555",
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_row,
            text="Сбросить ошибки",
            command=self._reset_failed,
            width=130,
            fg_color="#444444",
            hover_color="#555555",
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_row,
            text="Очистить базу",
            command=self._clear_all,
            width=120,
            fg_color="#8B0000",
            hover_color="#A52A2A",
        ).pack(side="left")

        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))

        ctk.CTkLabel(filter_row, text="Показать:").pack(side="left", padx=(0, 8))
        self.filter_menu = ctk.CTkOptionMenu(
            filter_row,
            values=["Все", "Ожидают", "Отправлено", "Ошибки"],
            command=self._on_filter_change,
            width=140,
        )
        self.filter_menu.pack(side="left")

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.grid(row=5, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.grid_rowconfigure(5, weight=1)
        self.refresh()

    def _on_filter_change(self, value: str) -> None:
        mapping = {"Все": "all", "Ожидают": "pending", "Отправлено": "sent", "Ошибки": "failed"}
        self._filter = mapping.get(value, "all")
        self.refresh()

    def refresh(self) -> None:
        stats = get_recipient_stats()
        self.stats_label.configure(
            text=(
                f"Всего: {stats['total']}  |  Ожидают: {stats['pending']}  |  "
                f"Отправлено: {stats['sent']}  |  Ошибки: {stats['failed']}"
            )
        )

        for widget in self.list_frame.winfo_children():
            widget.destroy()

        status = None if self._filter == "all" else self._filter
        recipients = get_recipients(status=status, limit=200)

        if not recipients:
            ctk.CTkLabel(self.list_frame, text="База пуста", text_color="gray").grid(
                row=0, column=0, sticky="w", pady=8
            )
            return

        status_colors = {
            "pending": "#f2994a",
            "sent": "#6fcf97",
            "failed": "#eb5757",
        }
        status_names = {
            "pending": "ожидает",
            "sent": "отправлено",
            "failed": "ошибка",
        }

        for index, recipient in enumerate(recipients):
            row = ctk.CTkFrame(self.list_frame)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)

            color = status_colors.get(recipient.status, "gray")
            status_text = status_names.get(recipient.status, recipient.status)
            info = f"{recipient.contact}  —  {status_text}"
            if recipient.last_error:
                info += f" ({recipient.last_error[:60]})"

            ctk.CTkLabel(row, text=info, anchor="w", text_color=color).grid(
                row=0, column=0, sticky="w", padx=10, pady=8
            )

            ctk.CTkButton(
                row,
                text="×",
                width=30,
                fg_color="#555555",
                hover_color="#8B0000",
                command=lambda rid=recipient.id: self._delete_one(rid),
            ).grid(row=0, column=1, padx=8, pady=6)

    def _import_text(self) -> None:
        raw = self.import_box.get("1.0", "end")
        contacts = MailerService.parse_recipients(raw)
        if not contacts:
            messagebox.showerror("Ошибка", "Введите хотя бы один контакт")
            return
        added, skipped = import_recipients(contacts)
        self.import_box.delete("1.0", "end")
        self.refresh()
        messagebox.showinfo("Готово", f"Добавлено: {added}\nПропущено (дубликаты): {skipped}")

    def _import_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите файл с контактами",
            filetypes=[("Текстовые файлы", "*.txt"), ("CSV", "*.csv"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except UnicodeDecodeError:
            with open(path, encoding="cp1251") as f:
                raw = f.read()

        contacts = MailerService.parse_recipients(raw)
        if not contacts:
            messagebox.showerror("Ошибка", "В файле не найдено контактов")
            return
        added, skipped = import_recipients(contacts)
        self.refresh()
        messagebox.showinfo("Готово", f"Из файла добавлено: {added}\nПропущено (дубликаты): {skipped}")

    def _reset_failed(self) -> None:
        count = reset_failed_recipients()
        self.refresh()
        messagebox.showinfo("Готово", f"В очередь возвращено: {count} получателей с ошибками")

    def _clear_all(self) -> None:
        total = count_recipients()
        if total == 0:
            return
        if not messagebox.askyesno("Подтверждение", f"Удалить всех {total} получателей из базы?"):
            return
        clear_recipients()
        self.refresh()

    def _delete_one(self, recipient_id: int) -> None:
        delete_recipient(recipient_id)
        self.refresh()
