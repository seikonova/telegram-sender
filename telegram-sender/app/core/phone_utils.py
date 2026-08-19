import re


def normalize_phone(phone: str) -> str:
    """Приводит номер к формату +7XXXXXXXXXX для РФ и международному виду."""
    digits = re.sub(r"\D", "", phone.strip())

    if not digits:
        raise ValueError("Введите номер телефона")

    # Россия: 8XXXXXXXXXX или 7XXXXXXXXXX (11 цифр)
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits[0] == "9":
        digits = "7" + digits

    if len(digits) < 10:
        raise ValueError("Номер слишком короткий. Пример: +79991234567 или 89991234567")

    return "+" + digits


def session_name_from_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"account_{digits}"
