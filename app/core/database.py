import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from app.config import DB_PATH


@dataclass
class Account:
    id: int
    phone: str
    session_name: str
    display_name: str
    is_active: bool
    proxy: str | None = None


@dataclass
class Settings:
    api_id: str
    api_hash: str
    default_delay: int


@dataclass
class Recipient:
    id: int
    contact: str
    status: str
    last_error: str
    sent_by_account_id: int | None
    sent_at: str | None


@dataclass
class ChatFolderTemplate:
    id: int
    name: str
    emoticon: str
    chats: list[str]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                api_id TEXT NOT NULL DEFAULT '',
                api_hash TEXT NOT NULL DEFAULT '',
                default_delay INTEGER NOT NULL DEFAULT 5
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL UNIQUE,
                session_name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL DEFAULT '',
                proxy TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact TEXT NOT NULL UNIQUE COLLATE NOCASE,
                status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT NOT NULL DEFAULT '',
                sent_by_account_id INTEGER,
                sent_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (sent_by_account_id) REFERENCES accounts(id)
            );

            CREATE INDEX IF NOT EXISTS idx_recipients_status ON recipients(status);

            CREATE TABLE IF NOT EXISTS chat_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                emoticon TEXT NOT NULL DEFAULT '📁',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_folder_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER NOT NULL,
                contact TEXT NOT NULL,
                FOREIGN KEY (folder_id) REFERENCES chat_folders(id) ON DELETE CASCADE,
                UNIQUE(folder_id, contact)
            );

            INSERT OR IGNORE INTO settings (id, api_id, api_hash, default_delay)
            VALUES (1, '', '', 5);
            """
        )
        columns = [row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()]
        if "proxy" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN proxy TEXT")


def get_settings() -> Settings:
    with get_db() as conn:
        row = conn.execute("SELECT api_id, api_hash, default_delay FROM settings WHERE id = 1").fetchone()
    return Settings(api_id=row["api_id"], api_hash=row["api_hash"], default_delay=row["default_delay"])


def save_settings(api_id: str, api_hash: str, default_delay: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE settings SET api_id = ?, api_hash = ?, default_delay = ? WHERE id = 1",
            (api_id.strip(), api_hash.strip(), default_delay),
        )


def add_account(phone: str, session_name: str, display_name: str = "", proxy: str | None = None) -> int:
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM accounts WHERE phone = ?", (phone,)).fetchone()
        if existing:
            raise ValueError(f"Аккаунт {phone} уже добавлен")
        cursor = conn.execute(
            """
            INSERT INTO accounts (phone, session_name, display_name, proxy)
            VALUES (?, ?, ?, ?)
            """,
            (phone, session_name, display_name or phone, proxy),
        )
        return cursor.lastrowid


def get_accounts() -> list[Account]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, phone, session_name, display_name, proxy, is_active FROM accounts ORDER BY id"
        ).fetchall()
    return [
        Account(
            id=row["id"],
            phone=row["phone"],
            session_name=row["session_name"],
            display_name=row["display_name"],
            proxy=row["proxy"],
            is_active=bool(row["is_active"]),
        )
        for row in rows
    ]


def get_account(account_id: int) -> Optional[Account]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, phone, session_name, display_name, proxy, is_active FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
    if not row:
        return None
    return Account(
        id=row["id"],
        phone=row["phone"],
        session_name=row["session_name"],
        display_name=row["display_name"],
        proxy=row["proxy"],
        is_active=bool(row["is_active"]),
    )


def delete_account(account_id: int) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute("SELECT session_name FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return row["session_name"]


def update_account_name(account_id: int, display_name: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE accounts SET display_name = ? WHERE id = ?", (display_name, account_id))


def update_account_proxy(account_id: int, proxy: str | None) -> None:
    with get_db() as conn:
        conn.execute("UPDATE accounts SET proxy = ? WHERE id = ?", (proxy, account_id))


def _row_to_recipient(row: sqlite3.Row) -> Recipient:
    return Recipient(
        id=row["id"],
        contact=row["contact"],
        status=row["status"],
        last_error=row["last_error"] or "",
        sent_by_account_id=row["sent_by_account_id"],
        sent_at=row["sent_at"],
    )


def import_recipients(contacts: list[str]) -> tuple[int, int]:
    """Возвращает (добавлено, пропущено дубликатов)."""
    added = 0
    skipped = 0
    with get_db() as conn:
        for contact in contacts:
            contact = contact.strip()
            if not contact:
                continue
            try:
                conn.execute(
                    "INSERT INTO recipients (contact) VALUES (?)",
                    (contact,),
                )
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
    return added, skipped


def get_recipients(status: str | None = None, limit: int = 500) -> list[Recipient]:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT id, contact, status, last_error, sent_by_account_id, sent_at
                FROM recipients WHERE status = ? ORDER BY id LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, contact, status, last_error, sent_by_account_id, sent_at
                FROM recipients ORDER BY id LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_row_to_recipient(row) for row in rows]


def get_pending_recipients() -> list[Recipient]:
    return get_recipients(status="pending", limit=100000)


def count_recipients(status: str | None = None) -> int:
    with get_db() as conn:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM recipients WHERE status = ?",
                (status,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM recipients").fetchone()
    return row["cnt"]


def get_recipient_stats() -> dict[str, int]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM recipients GROUP BY status"
        ).fetchall()
    stats = {"pending": 0, "sent": 0, "failed": 0, "total": 0}
    for row in rows:
        stats[row["status"]] = row["cnt"]
        stats["total"] += row["cnt"]
    return stats


def mark_recipient_sent(recipient_id: int, account_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE recipients
            SET status = 'sent', last_error = '', sent_by_account_id = ?, sent_at = datetime('now')
            WHERE id = ?
            """,
            (account_id, recipient_id),
        )


def mark_recipient_failed(recipient_id: int, error: str, account_id: int | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE recipients
            SET status = 'failed', last_error = ?, sent_by_account_id = ?
            WHERE id = ?
            """,
            (error[:500], account_id, recipient_id),
        )


def reset_failed_recipients() -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE recipients
            SET status = 'pending', last_error = '', sent_by_account_id = NULL, sent_at = NULL
            WHERE status = 'failed'
            """
        )
        return cursor.rowcount


def delete_recipient(recipient_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM recipients WHERE id = ?", (recipient_id,))


def clear_recipients(status: str | None = None) -> int:
    with get_db() as conn:
        if status:
            cursor = conn.execute("DELETE FROM recipients WHERE status = ?", (status,))
        else:
            cursor = conn.execute("DELETE FROM recipients")
        return cursor.rowcount


def _load_folder_chats(conn: sqlite3.Connection, folder_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT contact FROM chat_folder_items WHERE folder_id = ? ORDER BY id",
        (folder_id,),
    ).fetchall()
    return [row["contact"] for row in rows]


def save_chat_folder(name: str, chats: list[str], emoticon: str = "📁") -> int:
    name = name.strip()
    if not name:
        raise ValueError("Укажите название папки")
    if not chats:
        raise ValueError("Добавьте хотя бы один чат в папку")

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM chat_folders WHERE name = ?", (name,)).fetchone()
        if existing:
            folder_id = existing["id"]
            conn.execute(
                "UPDATE chat_folders SET emoticon = ? WHERE id = ?",
                (emoticon or "📁", folder_id),
            )
            conn.execute("DELETE FROM chat_folder_items WHERE folder_id = ?", (folder_id,))
        else:
            cursor = conn.execute(
                "INSERT INTO chat_folders (name, emoticon) VALUES (?, ?)",
                (name, emoticon or "📁"),
            )
            folder_id = cursor.lastrowid

        for contact in chats:
            contact = contact.strip()
            if contact:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_folder_items (folder_id, contact) VALUES (?, ?)",
                    (folder_id, contact),
                )
        return folder_id


def get_chat_folders() -> list[ChatFolderTemplate]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, emoticon FROM chat_folders ORDER BY name"
        ).fetchall()
        return [
            ChatFolderTemplate(
                id=row["id"],
                name=row["name"],
                emoticon=row["emoticon"] or "📁",
                chats=_load_folder_chats(conn, row["id"]),
            )
            for row in rows
        ]


def get_chat_folder(folder_id: int) -> Optional[ChatFolderTemplate]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name, emoticon FROM chat_folders WHERE id = ?",
            (folder_id,),
        ).fetchone()
        if not row:
            return None
        return ChatFolderTemplate(
            id=row["id"],
            name=row["name"],
            emoticon=row["emoticon"] or "📁",
            chats=_load_folder_chats(conn, row["id"]),
        )


def delete_chat_folder(folder_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM chat_folders WHERE id = ?", (folder_id,))
