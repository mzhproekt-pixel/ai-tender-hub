"""
Чтение и запись .env прямо из веб-интерфейса.

Простой парсер: KEY=VALUE построчно, комментарии и пустые строки сохраняем.
Значения, в которых есть пробелы, экранируем двойными кавычками.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Поля, которыми управляем через UI.
# secret=True → в форме показываем placeholder, а не значение.
FIELDS = [
    ("MAILRU_LOGIN", "Логин Mail.ru (полный e-mail)", False),
    ("MAILRU_APP_PASSWORD", "Пароль приложения Mail.ru", True),
    ("MAILRU_SENDER_NAME", "Имя отправителя", False),
    ("ANTHROPIC_API_KEY", "Anthropic API key (sk-ant-...)", True),
    ("ANTHROPIC_MODEL", "Модель Claude (можно оставить пустым)", False),
    ("START_DATE", "Тянуть письма начиная с даты (YYYY-MM-DD)", False),
]

LINE_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def read_env() -> dict[str, str]:
    """Возвращает текущие значения из .env (только наши поля)."""
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        # снимаем кавычки, если есть
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key] = val
    return values


def _quote(value: str) -> str:
    if not value:
        return ""
    if re.search(r"[\s#'\"]", value):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def write_env(updates: dict[str, str]) -> None:
    """
    Обновляет .env: для каждого ключа из updates подменяет значение,
    остальные строки/комментарии сохраняет. Если ключа не было — дописывает.
    Пустые значения => строка удаляется.
    """
    existing_lines: list[str] = []
    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    seen_keys: set[str] = set()
    out: list[str] = []
    for line in existing_lines:
        m = LINE_RE.match(line)
        if not m or line.lstrip().startswith("#"):
            out.append(line)
            continue
        key = m.group(1)
        if key in updates:
            seen_keys.add(key)
            new_val = updates[key]
            if new_val == "":
                continue  # удаляем строку
            out.append(f"{key}={_quote(new_val)}")
        else:
            out.append(line)

    # дописываем недостающие ключи
    for key, new_val in updates.items():
        if key in seen_keys or new_val == "":
            continue
        out.append(f"{key}={_quote(new_val)}")

    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    # права 600, чтобы секреты не светились
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass


def apply_to_process(values: dict[str, str]) -> None:
    """
    Подставляем значения в os.environ текущего процесса,
    чтобы запуски пайплайна сразу подхватили новые настройки.
    Пустые значения — удаляем из окружения.
    """
    for k, v in values.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def current_view() -> list[dict]:
    """
    Возвращает данные для шаблона: для каждого поля — текущее значение
    (или маска для секрета). Берём из os.environ, иначе из .env.
    """
    env_file = read_env()
    rows = []
    for key, label, secret in FIELDS:
        raw = os.environ.get(key) or env_file.get(key, "")
        rows.append({
            "key": key,
            "label": label,
            "secret": secret,
            "value": "" if secret else raw,
            "is_set": bool(raw),
        })
    return rows


# Подстроки, по которым опознаём незаполненные значения из .env.example.
PLACEHOLDER_MARKERS = ("замените", "sk-ant-замените")

# Ключи, без которых пайплайн объективно не работает.
CRITICAL_KEYS = ("MAILRU_APP_PASSWORD", "ANTHROPIC_API_KEY")


def find_placeholders() -> list[dict]:
    """
    Возвращает список критичных ключей, чьи значения всё ещё являются
    плейсхолдерами из .env.example. Используется баннером на /settings.
    """
    labels = {key: label for key, label, _ in FIELDS}
    env_file = read_env()
    out: list[dict] = []
    for key in CRITICAL_KEYS:
        raw = os.environ.get(key) or env_file.get(key, "")
        if not raw:
            continue
        low = raw.lower()
        if any(m in low for m in PLACEHOLDER_MARKERS):
            out.append({
                "key": key,
                "label": labels.get(key, key),
                "value_preview": raw[:40],
            })
    return out
