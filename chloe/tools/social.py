"""Инструмент social — контент-план и посты для Telegram-канала, Instagram, YouTube и TikTok."""
import datetime
import threading
import time
import webbrowser

from .. import social as sc
from ..social import SocialError, social
from ..voice import confirm


def when(text):
    """'2026-11-12T10:00' → время; пусто — None."""
    text = (text or "").strip()
    if not text:
        return None
    d = datetime.datetime.fromisoformat(text)
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


def when_text(ts):
    if not ts:
        return "без даты"
    d = datetime.datetime.fromtimestamp(ts)
    today = datetime.date.today()
    day = {0: "сегодня", 1: "завтра"}.get((d.date() - today).days, "{:%d.%m}".format(d))
    return "{} в {:%H:%M}".format(day, d)


def describe(p, full=False):
    head = "[{}] {}{} — {}, {}".format(p["id"], sc.NETWORKS[p["network"]], " «{}»".format(p["channel"]) if p["channel"] else "",
                                       sc.STATUS.get(p["status"], p["status"]), when_text(p["due"]))
    if p["title"]:
        head += ": «{}»".format(p["title"])
    if p["media"]:
        head += " [файлов: {}]".format(len(p["media"]))
    text = p["text"] if full else (p["text"][:120] + ("…" if len(p["text"]) > 120 else ""))
    return head + "\n   " + text.replace("\n", " ")


def _ask(post, what):
    where = sc.NETWORKS[post["network"]] + (" «{}»".format(post["channel"]) if post["channel"] else "")
    media = ", с {} файл.".format(len(post["media"])) if post["media"] else ""
    return confirm("{} в {}{}{}: «{}»?".format(what, where, " " + when_text(post["due"]) if post["due"] and what == "Запланировать" else "",
                                               media, post["text"][:400]))


def release(post, announce=None):
    """Выпустить пост: Telegram — опубликовать; остальные — собрать пакет и открыть страницу загрузки."""
    if post["network"] == "telegram":
        try:
            name = sc.publish_telegram(post)
        except Exception as e:
            social.set_status(post["id"], "failed", str(e)[:300])
            raise SocialError(str(e)) from None
        social.set_status(post["id"], "published", "канал " + name)
        return "Опубликовала в канале «{}».".format(name)
    folder = sc.export(post)
    social.set_status(post["id"], "exported", str(folder))
    try:
        import subprocess

        subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        webbrowser.open(sc.UPLOAD[post["network"]])
    except Exception:
        pass
    return ("Пакет для {} готов: {} (подпись — подпись.txt, файлы рядом). Открыла папку и страницу загрузки — "
            "выложите сами, потом скажите «опубликовала пост {}».".format(sc.NETWORKS[post["network"]], folder, post["id"]))


def tool_social(a):
    action = a.get("action", "list")
    try:
        if action == "list":
            posts = social.posts(include_done=bool(a.get("all")))
            if not posts:
                return "Контент-плана пока нет. Предложи пользователю темы и напиши посты (action=add, posts=[…])."
            return "\n".join(describe(p) for p in posts)
        if action == "show":
            p = social.get(int(a.get("id") or 0))
            return describe(p, full=True) if p else "Нет такого поста."
        if action == "add":
            posts = a.get("posts") or [a]
            added = []
            for item in posts[:30]:
                added.append(social.add(item.get("network"), item.get("text"), item.get("title"), item.get("channel"),
                                        item.get("media"), when(item.get("when"))))
            return ("Записала в контент-план черновиками ({}):\n".format(len(added)) + "\n".join(describe(p) for p in added) +
                    "\nНичего не опубликовано: Telegram-посты — после «одобряю» (approve), остальные — пакетом.")
        pid = int(a.get("id") or 0)
        post = social.get(pid)
        if not post:
            return "Нет поста №{}. Номера — в action=list.".format(pid)
        if action == "edit":
            fields = {k: a.get(k) for k in ("text", "title", "channel", "network", "media")}
            if a.get("when") is not None:
                fields["due"] = when(a.get("when"))
            p = social.update(pid, **fields)
            note = " Изменён — одобрить нужно заново." if post["status"] == "approved" and p["status"] == "draft" else ""
            return "Исправила:\n" + describe(p, full=True) + note
        if action == "delete":
            if not confirm("Удалить из плана пост №{} ({})?".format(pid, sc.NETWORKS[post["network"]])):
                return "Оставила."
            social.set_status(pid, "cancelled")
            return "Убрала пост №{} из плана.".format(pid)
        if action == "approve":
            if post["network"] != "telegram":
                return "Одобрение нужно только для Telegram: Instagram, YouTube и TikTok вы выкладываете сами (action=publish — пакет)."
            if not post["due"]:
                return "Сначала время (edit с when), или публикуй сразу: action=publish."
            if not _ask(post, "Запланировать"):
                return "Не одобряю."
            social.set_status(pid, "approved")
            return "Одобрен: уйдёт в канал {} сам.".format(when_text(post["due"]))
        if action == "publish":
            if post["status"] == "published":
                return "Пост №{} уже опубликован.".format(pid)
            if post["network"] == "telegram" and not _ask(post, "Опубликовать сейчас"):
                return "Не публикую."
            return release(post)
        if action == "done":
            social.set_status(pid, "published", "выложено вручную")
            return "Отметила пост №{} опубликованным.".format(pid)
    except SocialError as e:
        return "Не могу: {}.".format(e)
    except ValueError:
        return "Не поняла дату или номер (время — 2026-11-12T10:00)."
    return "Неизвестное действие: " + action


def watcher(say, every=60, stop=None):
    """В срок: одобренный Telegram-пост уходит сам; для остальных — напоминание и пакет. Неодобренный — только напоминание."""
    while not (stop and stop.is_set()):
        for p in social.due_now():
            try:
                if p["network"] == "telegram" and p["status"] == "approved":
                    say("Пост в канале: " + release(p))
                elif p["network"] == "telegram":
                    social.update(p["id"], due=None)
                    say("Пора было выложить пост №{} в Telegram, но он не одобрен. Скажите «опубликуй пост {}», "
                        "если всё верно.".format(p["id"], p["id"]))
                else:
                    say("Пора выложить пост в {}. {}".format(sc.NETWORKS[p["network"]], release(p)))
            except Exception as e:
                say("Пост №{} не вышел: {}.".format(p["id"], str(e)[:120]))
        (stop.wait(every) if stop else time.sleep(every))


def start(say):
    threading.Thread(target=watcher, args=(say,), daemon=True, name="social").start()
