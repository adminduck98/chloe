"""Задания: план → согласие → шаги по одному через главный цикл → отчёты → пауза при перезапуске."""
import pathlib
import queue
import tempfile
import unittest
from unittest import mock

from chloe import missions as ms
from chloe.tools import task


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.m = ms.Missions(self.dir / "t.db")
        p = mock.patch.object(ms, "missions", self.m)
        p.start()
        self.addCleanup(p.stop)

    def new(self, n=3):
        return self.m.create("Подготовить проект", ["шаг %d" % i for i in range(n)], "подготовь проект к запуску")


class Store(Base):
    def test_plan_needs_two_to_ten_steps(self):
        with self.assertRaises(ms.MissionError):
            self.m.create("Мало", ["один"])
        with self.assertRaises(ms.MissionError):
            self.m.create("Много", ["x"] * 11)

    def test_steps_report_and_finish(self):
        m = self.m.approve(self.new(2)["id"])
        s = self.m.begin_step(m)
        self.assertEqual(s["title"], "шаг 0")
        self.m.report(m["id"], "done", "тесты прошли")
        self.m.begin_step(self.m.get(m["id"]))
        m = self.m.report(m["id"], "done", "отчёт готов")
        self.assertEqual(m["status"], "done")
        self.assertEqual(m["done_n"], 2)

    def test_need_user_waits_and_resumes_with_answer(self):
        m = self.m.approve(self.new()["id"])
        self.m.begin_step(m)
        m = self.m.report(m["id"], "need_user", question="Какую ветку проверять?")
        self.assertEqual(m["status"], "waiting")
        self.assertEqual(m["steps"][0]["status"], "todo")                  # шаг повторится
        m = self.m.resume(m["id"], "main")
        self.assertEqual((m["status"], m["answer"]), ("running", "main"))
        self.assertIn("Ответ пользователя: main", ms.step_request(m, m["steps"][0]))

    def test_failed_step_blocks_then_skip_moves_on(self):
        m = self.m.approve(self.new()["id"])
        self.m.begin_step(m)
        m = self.m.report(m["id"], "failed", "нет доступа к серверу")
        self.assertEqual(m["status"], "blocked")
        m = self.m.skip(m["id"])
        self.assertEqual(m["status"], "running")
        self.assertEqual(m["steps"][0]["status"], "skipped")
        self.assertEqual(self.m.begin_step(m)["title"], "шаг 1")

    def test_restart_pauses_and_does_not_continue_by_itself(self):
        m = self.m.approve(self.new()["id"])
        self.m.begin_step(m)
        self.assertEqual(self.m.recover(), 1)
        m = self.m.get(m["id"])
        self.assertEqual(m["status"], "paused")
        self.assertEqual(m["steps"][0]["status"], "todo")
        self.assertIsNone(self.m.active())

    def test_only_one_runs_at_a_time(self):
        self.m.approve(self.new()["id"])
        with self.assertRaises(ms.MissionError):
            self.m.approve(self.new()["id"])

    def test_find_by_words_or_last(self):
        a = self.new()
        self.assertEqual(self.m.find("проект")["id"], a["id"])
        self.assertEqual(self.m.find()["id"], a["id"])
        self.assertIsNone(self.m.find("бизнес"))


class Feeder(Base):
    def setUp(self):
        super().setUp()
        self.q = queue.Queue()
        self.busy = mock.Mock(is_set=mock.Mock(return_value=False))
        self.voice = mock.Mock(saying="", awaiting=False, recognizing=False, last_loud=0, last_said="Проверила: всё чисто.")
        for p in (mock.patch("chloe.signals.commands", self.q), mock.patch("chloe.signals.busy", self.busy),
                  mock.patch("chloe.voice.voice", self.voice), mock.patch("chloe.settings.settings.get", return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        ms._feed.update(step=None, pushed=0.0)

    def test_gives_one_step_when_idle(self):
        m = self.m.approve(self.new()["id"])
        step = ms.tick(now=1000)
        self.assertEqual(step["title"], "шаг 0")
        request = self.q.get_nowait()
        self.assertIn("шаг 1 из 3", request)
        self.assertIn("mission(action=report, id={}".format(m["id"]), request)
        self.assertIsNone(ms.tick(now=1001))                           # шаг ещё идёт — второй не даём

    def test_waits_while_chloe_is_busy_or_user_talks(self):
        self.m.approve(self.new()["id"])
        self.busy.is_set.return_value = True
        self.assertIsNone(ms.tick(now=1000))
        self.busy.is_set.return_value = False
        self.voice.last_loud = 999
        self.assertIsNone(ms.tick(now=1000))
        self.assertTrue(self.q.empty())

    def test_forgotten_report_closes_step_with_last_answer(self):
        m = self.m.approve(self.new(2)["id"])
        ms.tick(now=1000)
        self.q.get_nowait()
        nxt = ms.tick(now=1000 + ms.QUIET_AFTER + 1)
        self.assertEqual(nxt["title"], "шаг 1")
        self.assertEqual(self.m.get(m["id"])["steps"][0]["result"], "Проверила: всё чисто.")

    def test_reported_steps_run_to_the_end(self):
        m = self.m.approve(self.new(2)["id"])
        ms.tick(now=1000)
        self.q.get_nowait()                                            # главный цикл забрал шаг
        self.m.report(m["id"], "done", "a")
        ms.tick(now=2000)
        self.q.get_nowait()
        self.m.report(m["id"], "done", "b")
        self.assertEqual(self.m.get(m["id"])["status"], "done")
        self.assertIsNone(ms.tick(now=3000))

    def test_forgotten_last_report_announces_done(self):
        m = self.m.approve(self.new(2)["id"])
        said = []
        ms.tick(now=1000)
        self.q.get_nowait()
        self.m.report(m["id"], "done", "a")
        ms.tick(now=2000)
        self.q.get_nowait()
        ms.tick(now=2000 + ms.QUIET_AFTER + 1, say=said.append)       # последний шаг без отчёта
        self.assertEqual(self.m.get(m["id"])["status"], "done")
        self.assertIn("готово", said[0])

    def test_safe_mode_pauses(self):
        self.m.approve(self.new()["id"])
        with mock.patch("chloe.settings.settings.get", return_value=True):
            self.assertIsNone(ms.tick(now=1000))
        self.assertTrue(self.q.empty())


class Tool(Base):
    def test_plan_asks_before_starting(self):
        with mock.patch.object(task, "confirm", return_value=True) as ask:
            out = task.tool_mission({"action": "plan", "title": "Подготовить проект", "steps": ["тесты", "отчёт"]})
        self.assertIn("Начинаю задание", out)
        self.assertIn("1) тесты; 2) отчёт", ask.call_args[0][0])
        self.assertEqual(self.m.active()["title"], "Подготовить проект")

    def test_declined_plan_is_kept_not_started(self):
        with mock.patch.object(task, "confirm", return_value=False):
            out = task.tool_mission({"action": "plan", "title": "Подготовить проект", "steps": ["тесты", "отчёт"]})
        self.assertIn("не начинаю", out)
        self.assertIsNone(self.m.active())

    def test_report_and_resume_by_voice(self):
        m = self.m.approve(self.new()["id"])
        self.m.begin_step(m)
        out = task.tool_mission({"action": "report", "id": m["id"], "outcome": "need_user", "question": "Какой сервер?"})
        self.assertIn("Какой сервер?", out)
        self.assertIn("ждёт вашего ответа", task.tool_mission({"action": "list"}))
        task.tool_mission({"action": "resume", "answer": "боевой"})
        self.assertEqual(self.m.get(m["id"])["status"], "running")

    def test_cancel_asks(self):
        self.new()
        with mock.patch.object(task, "confirm", return_value=False):
            self.assertEqual(task.tool_mission({"action": "cancel"}), "Не отменяю.")


if __name__ == "__main__":
    unittest.main()
