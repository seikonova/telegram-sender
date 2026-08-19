import re

from telethon import utils as tg_utils

# t.me/..., telegram.me/..., tg://join?invite=...
LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:telegram\.(?:me|dog)|t\.me)/(?:\+|joinchat/|c/)?[a-zA-Z0-9_\-+]+(?:/\d+)?",
    re.IGNORECASE,
)
# tg://join?invite=...
TG_JOIN_PATTERN = re.compile(r"tg://join\?invite=[A-Za-z0-9_-]+", re.IGNORECASE)

USERNAME_PATTERN = re.compile(r"@[a-zA-Z][a-zA-Z0-9_]{4,31}")
NUMERIC_ID_PATTERN = re.compile(r"^-?\d+$")


def normalize_chat_link(value: str) -> str | None:
    """Приводит строку к формату, понятному для вступления в чат."""
    value = value.strip().strip("<>\"'()[]")
    if not value:
        return None

    # Пропускаем addlist ссылки на папки (требуют ручного импорта в Telegram)
    if "addlist/" in value.lower():
        return None

    username, is_invite = tg_utils.parse_username(value)
    if username:
        if is_invite:
            return f"https://t.me/+{username}"
        if value.startswith("http"):
            return value.split("?")[0].rstrip("/")
        return f"@{username}"

    if value.startswith("@"):
        return value

    if NUMERIC_ID_PATTERN.match(value):
        return value

    # tg://join?invite=aaaa -> https://t.me/+aaaa
    if value.lower().startswith("tg://join") and "invite=" in value:
        try:
            invite = value.split("invite=", 1)[1].split("&")[0]
            return f"https://t.me/+{invite}"
        except Exception:
            return None

    if "t.me" in value.lower() or "telegram." in value.lower():
        return value.split("?")[0].rstrip("/")

    return None


def parse_telegram_links(text: str) -> list[str]:
    """
    Извлекает ссылки, @username и строки из текста.
    Поддерживает вставку из файлов, HTML, списков через запятую/перенос строки.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        normalized = normalize_chat_link(item)
        if not normalized:
            return
        key = normalized.lower()
        if key not in seen:
            seen.add(key)
            found.append(normalized)

    for match in LINK_PATTERN.finditer(text):
        add(match.group(0))

    for match in USERNAME_PATTERN.finditer(text):
        add(match.group(0))

    for part in re.split(r"[\n,;]+", text):
        part = part.strip()
        if part:
            add(part)

    return found
