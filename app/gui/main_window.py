import customtkinter as ctk

from app.core.database import init_db
from app.core.folder_service import FolderService
from app.core.joiner import JoinService
from app.core.mailer import MailerService
from app.core.profile_service import ProfileService
from app.core.telegram_client import TelegramManager
from app.gui.accounts_tab import AccountsTab
from app.gui.folders_tab import FoldersTab
from app.gui.join_chats_tab import JoinChatsTab
from app.gui.mailing_tab import MailingTab
from app.gui.parser_tab import ParserTab
from app.gui.profile_tab import ProfileTab
from app.gui.recipients_tab import RecipientsTab
from app.gui.settings_tab import SettingsTab


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Telegram Авторассылка")
        self.geometry("800x780")
        self.minsize(700, 640)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        init_db()
        self.manager = TelegramManager()
        self.mailer = MailerService(self.manager)
        self.joiner = JoinService(self.manager)
        self.folder_service = FolderService(self.manager)
        self.profile_service = ProfileService(self.manager)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.pack(fill="x")

        ctk.CTkLabel(
            header,
            text="Telegram Авторассылка",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left", padx=20, pady=16)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=16, pady=16)

        self.tabview.add("Рассылка")
        self.tabview.add("Чаты")
        self.tabview.add("Папки")
        self.tabview.add("Парсер")
        self.tabview.add("База")
        self.tabview.add("Аккаунты")
        self.tabview.add("Оформление")
        self.tabview.add("Настройки")

        self.recipients_tab = RecipientsTab(self.tabview.tab("База"), self.mailer)
        self.recipients_tab.pack(fill="both", expand=True)

        self.mailing_tab = MailingTab(
            self.tabview.tab("Рассылка"),
            self.mailer,
            on_mailing_finished=self.recipients_tab.refresh,
            fg_color="transparent",
        )
        self.mailing_tab.pack(fill="both", expand=True, padx=8, pady=8)

        self.join_chats_tab = JoinChatsTab(
            self.tabview.tab("Чаты"),
            self.joiner,
            fg_color="transparent",
        )
        self.join_chats_tab.pack(fill="both", expand=True, padx=8, pady=8)

        self.folders_tab = FoldersTab(
            self.tabview.tab("Папки"),
            self.folder_service,
            fg_color="transparent",
        )
        self.folders_tab.pack(fill="both", expand=True, padx=8, pady=8)

        self.parser_tab = ParserTab(
            self.tabview.tab("Парсер"),
            self.manager,
            fg_color="transparent",
        )
        self.parser_tab.pack(fill="both", expand=True, padx=8, pady=8)

        self.accounts_tab = AccountsTab(
            self.tabview.tab("Аккаунты"),
            self.manager,
            on_accounts_changed=self._on_accounts_changed,
        )
        self.accounts_tab.pack(fill="both", expand=True)

        self.profile_tab = ProfileTab(
            self.tabview.tab("Оформление"),
            self.profile_service,
            on_profile_updated=self._on_accounts_changed,
            fg_color="transparent",
        )
        self.profile_tab.pack(fill="both", expand=True, padx=8, pady=8)

        self.settings_tab = SettingsTab(self.tabview.tab("Настройки"))
        self.settings_tab.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_accounts_changed(self) -> None:
        self.mailing_tab.refresh_accounts()
        self.join_chats_tab.refresh_accounts()
        self.folders_tab.refresh_accounts()
        self.profile_tab.refresh_accounts()

    def _on_close(self) -> None:
        self.mailer.stop()
        self.joiner.stop()
        self.folder_service.stop()
        self.profile_service.stop()
        self.manager.shutdown()
        self.destroy()
