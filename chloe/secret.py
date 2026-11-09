"""Ключи, токены и пароли: Chloe их не запоминает и не показывает — ни в журнале, ни в терминале, ни вслух.

Ключам место в ~/.config/chloe/keys.env (или в ~/.chloe/telegram.json для Telegram), а не в памяти: память уходит модели
с каждой просьбой и видна в окне «Память» и на телефоне.
"""
import re

PATTERNS = [
    r"sk-ant-[A-Za-z0-9_-]{16,}",                  # Anthropic
    r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}",            # DeepSeek, OpenAI и похожие
    r"AIza[0-9A-Za-z_-]{30,}",                     # Google / Gemini
    r"gh[pousr]_[A-Za-z0-9]{30,}",                 # GitHub
    r"xox[abprs]-[A-Za-z0-9-]{10,}",               # Slack
    r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",             # бот Telegram
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
]
SECRET = re.compile("|".join(PATTERNS))
# «пароль: …», «api_key = …», export X_TOKEN="…" — значение после слова
NAMED = re.compile(r"(?i)((?:api[_-]?key|api[_-]?hash|token|secret|password|passwd|пароль|ключ)[A-Za-z_]*\"?\s*[:=]\s*[\"']?)"
                   r"([^\s\"']{6,})")


def has_secret(text):
    text = str(text or "")
    return bool(SECRET.search(text) or NAMED.search(text))


def redact(text):
    """Тот же текст, но вместо ключей — звёздочки (первые символы оставлены, чтобы было понятно, что это за ключ)."""
    if not isinstance(text, str):
        return text
    text = SECRET.sub(lambda m: m.group(0)[:3] + "***", text)
    return NAMED.sub(lambda m: m.group(1) + "***", text)
