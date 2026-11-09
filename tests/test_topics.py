"""Зоны по смыслу: темы из настоящих задач журнала. Всё во временной домашней папке."""
import unittest
from unittest import mock

from chloe import sleep, topics
from chloe.brain import brain
from chloe.config import HOME
from chloe.experience import things_of
from chloe.journal import journal
from chloe.memory import memory
from chloe.settings import settings
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False


def task(text, *tools, recall=None):
    journal.add("heard", "Голос", text)
    for name, args in tools:
        journal.add("tool", "X", name, {"tool": name, "args": args, "result": "ok", "seconds": 0.5})
    if recall:
        journal.add("memory", "Память", "Вспомнила: " + recall, {"recall": True})


SHOP = "Работает в магазине POINT TECH"


def fill_journal():
    with journal.lock:
        journal.db.execute("DELETE FROM events")
        journal.db.commit()
    for m in list(memory.items):
        memory.delete(m["id"])
    memory.add(SHOP, "Работа")
    memory.add("Любит чёрный кофе", "Личное")
    memory.add("Прайс магазина обновляется по понедельникам", "Работа")   # ещё не пригодилось, но о том же
    shop_site = ("open_url", {"url": "https://pointtech.uz/catalog"})
    shop_dir = ("write_text_file", {"path": str(HOME / "Документы/Магазин/прайс.txt"), "content": "x"})
    task("открой сайт магазина", shop_site, recall=SHOP)
    task("сохрани прайс магазина в папку", shop_dir, shop_site)
    task("напиши Ахмеду про магазин", ("tg_send", {"chat": "Ахмед", "text": "привет"}), shop_dir, recall=SHOP)
    task("включи музыку", ("open_url", {"url": "https://music.youtube.com"}))   # одна задача — не тема


class Topics(unittest.TestCase):
    def setUp(self):
        settings.set("topics", {})
        fill_journal()

    def test_shop_topic_from_real_tasks(self):
        found = topics.find_topics()
        self.assertEqual(len(found), 1, found)
        name, members = next(iter(found.items()))
        self.assertTrue(name.startswith("Магазин"), name)
        got = {m.get("name") or m.get("text") for m in members}
        self.assertTrue({"pointtech.uz", "~/Документы/Магазин", "Ахмед", SHOP} <= got, got)
        self.assertIn("Прайс магазина обновляется по понедельникам", got)   # по словам
        self.assertNotIn("Любит чёрный кофе", got)
        self.assertNotIn("music.youtube.com", got)

    def test_model_names_topic_and_name_is_kept(self):
        first = topics.find_topics(namer=lambda prompt: "Магазин POINT TECH")
        self.assertEqual(list(first), ["Магазин POINT TECH"])
        again = topics.find_topics(namer=lambda prompt: "Совсем другое")   # тема та же — имя не меняется
        self.assertEqual(list(again), ["Магазин POINT TECH"])

    def test_bad_model_answer_falls_back_to_words(self):
        found = topics.find_topics(namer=lambda prompt: "Вот название темы:\nМагазин")
        self.assertTrue(next(iter(found)).startswith("Магазин"))

    def test_memory_and_new_things_go_to_topic(self):
        found = topics.find_topics(namer=lambda prompt: "Магазин POINT TECH")
        topics.apply_to_memory(found)
        self.assertEqual(next(m for m in memory.items if m["text"] == SHOP)["zone"], "Магазин POINT TECH")
        self.assertEqual(next(m for m in memory.items if m["text"].startswith("Любит"))["zone"], "Личное")
        self.assertEqual(things_of("open_url", {"url": "https://pointtech.uz/x"})[0]["zone"], "Магазин POINT TECH")
        self.assertEqual(things_of("open_url", {"url": "https://wikipedia.org"})[0]["zone"], "Сайты")

    def test_sleep_reports_topics(self):
        calls = []
        sleep.namer = lambda prompt: "Магазин POINT TECH"
        try:
            with mock.patch.object(brain, "js", side_effect=lambda fn, *a: calls.append((fn,) + a)):
                out = run_tool("sleep_now", {})[0]
        finally:
            sleep.namer = None
        self.assertIn("Магазин POINT TECH", out)
        report = [c for c in calls if c[0] == "chloeSleep"][0][1]
        self.assertIn("Магазин POINT TECH", report["zones"])
        self.assertTrue(any(e["title"].startswith("Новая тема: Магазин POINT TECH") for e in journal.list(limit=20)))


if __name__ == "__main__":
    unittest.main()
