"""Кому сказано: после ответа Chloe слушает без слова «Хлоя» (окно CHLOE_ACTIVE), но речь рядом бывает не ей —
человек диктует другому помощнику, говорит в Telegram или на созвоне. Тогда без «Хлоя» не отвечаем.

Со словом «Хлоя» — всегда ей. Без него в окне — ей, если:
- она сама только что спросила (её реплика кончилась «?») — это ответ;
- фраза короткая (продолжение: «а завтра?», «открой его», «нет, второй»), и в это время не открыто окно, где человек
  говорит с кем-то другим (CHLOE_OTHER_APPS — через запятую, по умолчанию помощники, мессенджеры, созвоны).
"""
import os

SHORT_WORDS = int(os.environ.get("CHLOE_FOLLOWUP_WORDS", "10"))   # длиннее без «Хлоя» и без её вопроса — не ей
OTHER_APPS = tuple(x.strip().lower() for x in os.environ.get(
    "CHLOE_OTHER_APPS",
    "claude,chatgpt,gemini,copilot,perplexity,telegram,whatsapp,discord,zoom,meet,skype,teams,slack,viber").split(",")
    if x.strip())


def other_app(title):
    """Активно окно, где человек говорит не с Chloe (её собственное окно — «Chloe» — сюда не попадает)."""
    t = (title or "").lower()
    if not t or t.startswith("chloe"):
        return ""
    return next((a for a in OTHER_APPS if a in t.replace("‎", "").replace("⁨", "").replace("⁩", "")), "")


def followup_for_chloe(text, last_said="", title=""):
    """(ей ли это, почему) — для фразы без «Хлоя» в окне после её ответа."""
    asked = (last_said or "").rstrip().endswith("?")
    app = other_app(title)
    if app:
        return False, "открыто «{}» — говорите там".format(app)
    if asked:
        return True, "ответ на её вопрос"
    n = len((text or "").split())
    if n > SHORT_WORDS:
        return False, "длинная фраза без «Хлоя» ({} слов), а она ничего не спрашивала".format(n)
    return True, "короткое продолжение"
