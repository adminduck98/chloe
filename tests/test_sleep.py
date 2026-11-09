"""Настоящий сон: объединение повторов, укрепление важного, повтор задач дня. Всё во временной домашней папке."""
import datetime
import json
import time
import unittest
from unittest import mock

from chloe import sleep
from chloe.brain import brain
from chloe.config import HOME
from chloe.journal import journal
from chloe.memory import memory
from chloe.settings import settings
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False


def clear_memory(*texts):
    for m in list(memory.items):
        memory.delete(m["id"])
    return [memory.add(t, "Личное") for t in texts]


class Merges(unittest.TestCase):
    def pairs(self, *texts):
        items = [{"id": i, "text": t, "time": "2026-11-0{} 10:00".format(i)} for i, t in enumerate(texts, 1)]
        return [(k["text"], d["text"]) for k, d in sleep.find_merges(items)]

    def test_same_and_part_of_more_complete(self):
        self.assertEqual(self.pairs("Любит чёрный кофе", "любит черный кофе."), [("любит черный кофе.", "Любит чёрный кофе")])
        self.assertEqual(self.pairs("Любит чёрный кофе", "Любит чёрный кофе без сахара по утрам"),
                         [("Любит чёрный кофе без сахара по утрам", "Любит чёрный кофе")])

    def test_different_facts_stay(self):
        self.assertEqual(self.pairs("Любит чёрный кофе", "Сестру зовут Мадина", "Любит зелёный чай"), [])

    def test_each_memory_merged_once(self):
        got = self.pairs("Живёт в Ташкенте", "живёт в Ташкенте", "Живёт в ташкенте!")
        self.assertEqual(len(got), 2)
        self.assertEqual(len({k for k, _ in got}), 1)


class Night(unittest.TestCase):
    def setUp(self):
        settings.set("slept_on", "")
        self.calls = []
        p = mock.patch.object(brain, "js", side_effect=lambda fn, *a: self.calls.append((fn,) + a))
        p.start()
        self.addCleanup(p.stop)

    def test_sleep_merges_strengthens_and_replays(self):
        clear_memory("Любит чёрный кофе", "Любит чёрный кофе без сахара", "Сестру зовут Мадина")
        for _ in range(2):
            journal.add("memory", "Память", "Вспомнила: Сестру зовут Мадина", {"recall": True})
        journal.add("heard", "Голос", "покажи домашнюю папку")
        run_tool("list_folder", {"path": str(HOME)})
        out, _, failed = run_tool("sleep_now", {})
        self.assertFalse(failed, out)
        self.assertEqual([m["text"] for m in memory.items], ["Любит чёрный кофе без сахара", "Сестру зовут Мадина"])
        self.assertTrue(memory.items[1].get("important"))
        report = [c for c in self.calls if c[0] == "chloeSleep"][0][1]
        self.assertEqual(report["merged"], [{"keep": "Любит чёрный кофе без сахара", "drop": "Любит чёрный кофе"}])
        self.assertEqual(report["strong"], ["Сестру зовут Мадина"])
        self.assertIn("покажи домашнюю папку", [t["title"] for t in report["tasks"]])
        backups = list(sleep.SLEEP_DIR.glob("memory-*.json"))
        self.assertTrue(any("Любит чёрный кофе" in [m["text"] for m in json.loads(b.read_text())] for b in backups))   # ничего не потеряно
        self.assertTrue(any(e["title"].startswith("Объединила") for e in journal.list(limit=10)))

    def test_important_stays_in_prompt_when_old(self):
        first = clear_memory("Сестру зовут Мадина")[0]
        memory.mark(first["id"], True)
        for i in range(90):
            memory.add("факт номер {}".format(i), "Разное")
        self.assertIn("Сестру зовут Мадина (важное)", memory.prompt())

    def test_when_to_sleep(self):
        with mock.patch.object(sleep, "journal_last", return_value=0):
            night = datetime.datetime(2026, 11, 6, 3, 0).timestamp()
            day = datetime.datetime(2026, 11, 6, 15, 0).timestamp()
            self.assertTrue(sleep.should_sleep(night))
            self.assertFalse(sleep.should_sleep(day))
            settings.set("slept_on", "2026-11-06")
            self.assertFalse(sleep.should_sleep(night))   # уже спала этой ночью
        with mock.patch.object(sleep, "journal_last", return_value=time.time()):
            settings.set("slept_on", "")
            self.assertFalse(sleep.should_sleep(time.time() + 60))   # только что говорили — не спать


if __name__ == "__main__":
    unittest.main()
