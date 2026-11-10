"""Proactive Intelligence: подсказки с причиной, режимы, «не надо», правила «сказать вслух»."""
import threading
import time
import unittest
from unittest import mock

from chloe import proactive as pr
from chloe.settings import settings
from chloe.tools import HANDLERS
from chloe.tools import hints


def at(hour, day="2026-11-11"):
    return time.mktime(time.strptime("{} {:02d}:00".format(day, hour), "%Y-%m-%d %H:%M"))


TIPS = [pr.tip("a", "Важное", "потому что", "тест", 1, "сделай"), pr.tip("b", "Второе", "причина", "тест", 2)]


class Base(unittest.TestCase):
    def setUp(self):
        for k in ("proactive_mode", "proactive_snooze", "proactive_said", "safe_mode"):
            settings.set(k, None)
            self.addCleanup(settings.set, k, None)


class Collect(Base):
    def test_sorted_dedup_and_broken_source(self):
        srcs = (lambda now: [TIPS[1], TIPS[1]], lambda now: 1 / 0, lambda now: [TIPS[0]])
        with mock.patch.object(pr, "SOURCES", srcs):
            got = pr.collect()
        self.assertEqual([t["key"] for t in got], ["a", "b"])            # важное первым, повтор убран, сломанный — не мешает

    def test_snooze(self):
        with mock.patch.object(pr, "SOURCES", (lambda now: list(TIPS),)):
            pr.snooze("a")
            self.assertEqual([t["key"] for t in pr.collect()], ["b"])
            self.assertEqual(len(pr.collect(time.time() + 8 * 86400)), 2)   # через неделю — снова

    def test_stale_project_has_reason(self):
        from chloe.project_memory import project_memory as pm

        tid = pm.add_task("старый-проект", "что-то сделать")
        with pm.lock:
            pm.db.execute("UPDATE proj_tasks SET updated = ?, created = ? WHERE id = ?", (time.time() - 20 * 86400,) * 2 + (tid,))
            pm.db.commit()
        tips = pr.from_projects(time.time())
        mine = [t for t in tips if t["key"] == "project-stale:старый-проект"]
        self.assertEqual(len(mine), 1)
        self.assertIn("не обновлялся 20 дней", mine[0]["why"])
        pm.delete_task(tid)


class Speak(Base):
    def test_only_in_proactive_mode_daytime_with_gap(self):
        self.assertIsNone(pr.pick_to_say(TIPS, at(12)))                    # режим «Подсказки» — молчит
        pr.set_mode("proactive")
        self.assertIsNone(pr.pick_to_say(TIPS, at(23)))                    # ночью — нет
        t = pr.pick_to_say(TIPS, at(12))
        self.assertEqual(t["key"], "a")
        pr.mark_said("a", at(12))
        self.assertIsNone(pr.pick_to_say(TIPS, at(13)))                    # чаще раза в 2 часа — нет
        self.assertEqual(pr.pick_to_say(TIPS, at(15))["key"], "b")        # то же самое — не второй раз за день
        self.assertEqual(pr.pick_to_say(TIPS, at(12, "2026-11-12"))["key"], "a")   # назавтра — можно

    def test_phrase(self):
        self.assertEqual(pr.phrase(TIPS[0]), "Важное Потому что. Скажите «сделай», если да.")

    def test_watcher_speaks_once_and_respects_safe_mode(self):
        pr.set_mode("proactive")
        said = []
        with mock.patch.object(pr, "collect", return_value=list(TIPS)), mock.patch.object(pr, "SAY_HOURS", (0, 24)):
            settings.set("safe_mode", True)
            stop = threading.Event()
            th = threading.Thread(target=pr.watcher, args=(said.append, 0.01, stop))
            th.start()
            time.sleep(0.05)
            self.assertEqual(said, [])
            settings.set("safe_mode", False)
            from chloe.signals import state

            state["listen_until"] = 0
            for _ in range(100):
                if said:
                    break
                time.sleep(0.01)
            time.sleep(0.05)
            stop.set()
            th.join(2)
        self.assertEqual(len(said), 1)                                      # одна подсказка, а не поток


class Tool(Base):
    def test_modes_list_dismiss(self):
        self.assertIn("proactive", HANDLERS)
        self.assertIn("Подсказки", hints.tool_proactive({"action": "mode"}))
        self.assertIn("не чаще раза в 2 часа", hints.tool_proactive({"action": "mode", "mode": "сама"}))
        self.assertEqual(pr.mode(), "proactive")
        with mock.patch.object(pr, "SOURCES", (lambda now: list(TIPS),)):
            out = hints.tool_proactive({"action": "list"})
            self.assertIn("1. Важное — потому что", out)
            self.assertIn("неделю молчу", hints.tool_proactive({"action": "dismiss", "number": 1}))
            self.assertNotIn("Важное", hints.tool_proactive({"action": "list"}))
        self.assertIn("режим", hints.tool_proactive({"action": "mode", "mode": "громко"}))


if __name__ == "__main__":
    unittest.main()
