"""Долгая память: что Chloe знает о пользователе. Каждое воспоминание можно посмотреть, исправить и удалить."""
import json
import re
import threading
import time

from .brain import brain
from .config import MEMORY_FILE


def norm(text):
    """Текст без регистра, «ё» и знаков препинания — чтобы «Сестру зовут Мадина.» и «сестру зовут мадина» совпали."""
    return re.sub(r"[^\w]+", " ", str(text).lower().replace("ё", "е")).strip()


class Memory:
    """Что Chloe знает о пользователе. Каждое воспоминание можно посмотреть, исправить и удалить."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        try:
            self.items = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.items = []
        if any("id" not in m for m in self.items):   # старый файл без номеров
            for i, m in enumerate(self.items, 1):
                m["id"] = i
            self._save()

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def similar(self, text):
        """Уже записанное воспоминание о том же самом (или None).
        Почти те же значимые слова — значит, это тот же факт, может быть, в новой редакции."""
        from .experience import stems

        new, new_n = stems(text), norm(text)
        best, score = None, 0.0
        for m in self.items:
            if norm(m["text"]) == new_n:
                return m
            old = stems(m["text"])
            if len(new) >= 2 and len(old) >= 2:
                s = len(new & old) / len(new | old)
                if s > score:
                    best, score = m, s
        return best if score >= 0.75 else None

    def remember(self, text, zone):
        """Запомнить без дублей: тот же факт не пишется второй раз, новая редакция заменяет старую.
        Возвращает (запись, что произошло: "new" | "same" | "updated", старый текст)."""
        old = self.similar(text)
        if old is None:
            return self.add(text, zone), "new", None
        if norm(old["text"]) == norm(text):
            return old, "same", None
        before = self.edit(old["id"], text)
        return old, "updated", before

    def relevant(self, query, skip_ids=(), limit=5):
        """Давние воспоминания (не попавшие в подсказку), в которых есть слова просьбы: «как зовут мою сестру?»
        найдёт «сестру зовут Мадина», даже если это записано год назад и сотни фактов назад."""
        from .experience import stems

        want = stems(query)
        if not want:
            return []
        scored = []
        for m in self.items:
            if m["id"] in skip_ids:
                continue
            hit = len(want & stems(m["text"]))
            if hit:
                scored.append((hit, m.get("important", False), m["id"], m))
        scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        return [m for *_, m in scored[:limit]]

    def in_prompt(self):
        """Какие воспоминания уже стоят в подсказке (последние 80 и важные)."""
        recent = self.items[-80:]
        older_important = [m for m in self.items[:-80] if m.get("important")]
        return older_important + recent

    def add(self, text, zone):
        with self.lock:
            item = {"id": max((m["id"] for m in self.items), default=0) + 1, "text": text, "zone": zone,
                    "time": time.strftime("%Y-%m-%d %H:%M")}
            self.items.append(item)
            self._save()
        return item

    def get(self, mid):
        return next((m for m in self.items if m["id"] == mid), None)

    def edit(self, mid, text):
        """Возвращает старый текст или None, если такого воспоминания нет."""
        with self.lock:
            m = self.get(mid)
            if m is None:
                return None
            old, m["text"], m["edited"] = m["text"], text, time.strftime("%Y-%m-%d %H:%M")
            self._save()
        return old

    def delete(self, mid):
        with self.lock:
            m = self.get(mid)
            if m is not None:
                self.items.remove(m)
                self._save()
        return m

    def set_zone(self, mid, zone):
        """Тема воспоминания (раскладывает сон, см. topics.py)."""
        with self.lock:
            m = self.get(mid)
            if m is not None:
                m["zone"] = zone
                self._save()

    def mark(self, mid, important):
        """Важное (часто пригождается) — всегда в подсказке; помечает сон."""
        with self.lock:
            m = self.get(mid)
            if m is not None:
                if important:
                    m["important"] = True
                else:
                    m.pop("important", None)
                self._save()

    def prompt(self):
        if not self.items:
            return "Пока ничего не запомнено."
        # важное не выпадает, даже если давно; остальное давнее вспоминается по словам просьбы (relevant)
        return "\n".join("- [{}] {}{}{}".format(m["id"], m["text"], " (важное)" if m.get("important") else "", when(m))
                         for m in self.in_prompt())


def when(m):
    """« (записано 09.11)» — память верна на дату записи; изменчивое старше суток мозг проверяет (см. prompt.py)."""
    t = str(m.get("time") or "")
    return " (записано {}.{})".format(t[8:10], t[5:7]) if len(t) >= 10 else ""


memory = Memory(MEMORY_FILE)


def forget_memory(mid):
    """Удаляет воспоминание из памяти и его нейрон из мозга."""
    m = memory.delete(mid)
    if m:
        brain.js("chloeForget", m["text"])
        brain.expect_reload()   # окно сохранит мозг без нейрона и перезагрузится — следующие события подождут
    return m


def rewrite_memory(mid, text):
    old = memory.edit(mid, text)
    if old is not None:
        brain.js("chloeRewrite", old, text)
    return old
