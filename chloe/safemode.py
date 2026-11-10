"""Safe Mode — безопасный режим одной фразой: «Хлоя, безопасный режим».

Что происходит:
- действия закрыты: команды, файлы, мышь и клавиатура, интернет, Telegram, телефон, календарь, соцсети, картинки и видео,
  питание — работают только самопроверка, безопасность, журнал действий, напоминания (смотреть и отменять), громкость;
- автоматизации на паузе: запланированные посты не уходят, утренняя сводка не рассказывается сама;
- постоянное зрение (взгляд на экран) выключается, телефон-пульт только смотрит;
- состояние сохраняется: копия памяти и мозга, снимок самопроверки;
- в журнал — когда и почему включён.
Включить можно сразу (это усиление защиты). Выключить — только после «да» (голосом или подтверждением в окне).
"""
import time

from .settings import settings

ALLOWED_TOOLS = {"safe_mode", "actions", "system_state", "security", "system_info", "list_reminders", "cancel_reminder",
                 "volume", "brightness", "learned_list", "brain_usage", "conversation_log"}
REMOTE_ALLOWED = {"command", "system_status", "load_brain", "journal_list", "journal_get", "changes_list", "vision_get",
                  "city_get", "action_center", "system_health"}


def on():
    return bool(settings.get("safe_mode"))


def since():
    return (settings.get("safe_mode_info") or {}).get("at")


def blocks(tool):
    """Причина запрета или None."""
    if on() and tool not in ALLOWED_TOOLS:
        return "включён безопасный режим — действия на паузе; выключить: «выключи безопасный режим»"
    return None


def enable(reason="по просьбе пользователя"):
    """Включить. Возвращает список того, что сделано."""
    if on():
        return ["безопасный режим уже включён"]
    done = []
    try:
        from .vision import vision

        if vision.enabled:
            done.append("зрение выключено")   # само: vision.enabled смотрит на безопасный режим
    except Exception:
        pass
    settings.set("safe_mode_info", {"at": time.time(), "reason": reason})
    settings.set("safe_mode", True)
    done.append("действия и внешние подключения закрыты")
    done.append("автоматизации на паузе")
    try:
        from . import snapshots

        if snapshots.before("безопасный-режим"):
            done.append("копия памяти и мозга сохранена")
    except Exception:
        pass
    try:
        from . import system_state

        system_state.save(system_state.quick())
        done.append("снимок состояния сохранён")
    except Exception:
        pass
    try:
        from .journal import journal

        journal.add("brain", "Безопасность", "Безопасный режим включён: " + reason, {"reason": reason})
    except Exception:
        pass
    return done


def disable():
    if not on():
        return ["безопасный режим и так выключен"]
    info = settings.get("safe_mode_info") or {}
    settings.set("safe_mode", False)
    done = ["действия снова доступны (по карте прав)"]
    try:
        from .vision import vision

        if vision.enabled:
            vision.start()
            done.append("зрение снова включено")
    except Exception:
        pass
    try:
        from .journal import journal

        journal.add("brain", "Безопасность", "Безопасный режим выключен", {"was_on_minutes": round((time.time() - info.get("at", time.time())) / 60)})
    except Exception:
        pass
    return done
