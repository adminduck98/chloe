"""Goal System: цель → этапы → шаги, прогресс, следующий шаг, связь с задачами, граф и Action Center."""
import time
import unittest
from unittest import mock

from chloe.goals import GoalError, Goals
from chloe.permissions import TOOL_CATEGORY
from chloe.tools import HANDLERS
from chloe.tools import goal as tg

STAGES = [{"title": "Исследование", "steps": ["рынок Ташкента", "конкуренты"]}, {"title": "Демо-стенд", "steps": ["купить сервер"]},
          {"title": "Запуск"}]


class Store(unittest.TestCase):
    def setUp(self):
        self.g = Goals(":memory:")
        self.goal = self.g.add("Бизнес Smart Home", "свой доход", "chloe", "2027-03-01", STAGES)

    def test_tree_progress_next(self):
        g = self.goal
        self.assertEqual((g["total_n"], g["done_n"], g["progress"]), (4, 0, 0))
        self.assertEqual(g["next"]["step"], "рынок Ташкента")
        steps = {s["title"]: s["id"] for st in g["stages"] for s in st["steps"]}
        g = self.g.set_step(steps["рынок Ташкента"], "done")
        self.assertEqual((g["progress"], g["next"]["step"]), (25, "конкуренты"))

    def test_stage_without_steps_and_goal_done(self):
        for st in self.goal["stages"]:
            self.g.set_step(st["id"], "done")                             # этап целиком — и его шаги
        g = self.g.get(self.goal["id"])
        self.assertEqual(g["progress"], 100)
        self.assertEqual(g["status"], "done")                             # все шаги — цель достигнута
        self.assertIsNone(g["next"])

    def test_add_step_find_and_errors(self):
        stage = self.goal["stages"][1]["id"]
        self.g.add_step(self.goal["id"], "собрать стенд", stage)
        self.assertEqual(len(self.g.get(self.goal["id"])["stages"][1]["steps"]), 2)
        self.assertEqual([s["title"] for s in self.g.find_step(self.goal["id"], "стенд")], ["Демо-стенд", "собрать стенд"])   # похоже на два — спросит
        self.assertEqual(self.g.find_step(self.goal["id"], "собрать")[0]["title"], "собрать стенд")
        with self.assertRaises(GoalError):
            self.g.add("x")
        with self.assertRaises(GoalError):
            self.g.add("Цель", deadline="в марте")
        with self.assertRaises(GoalError):
            self.g.add_step(self.goal["id"], "шаг", stage_id=999)

    def test_linked_task_marks_step(self):
        step = self.goal["stages"][0]["steps"][0]
        self.g.link_task(step["id"], 77)
        fake = mock.Mock()
        fake.task.return_value = {"id": 77, "status": "done"}
        with mock.patch("chloe.project_memory.project_memory", fake):
            self.assertEqual(self.g.sync_tasks(), 1)
        self.assertEqual(self.g.step(step["id"])["status"], "done")

    def test_attention(self):
        now = time.time()
        soon = Goals(":memory:")
        a = soon.add("Скоро срок", deadline=time.strftime("%Y-%m-%d", time.localtime(now + 3 * 86400)), stages=["этап"])
        late = soon.add("Просрочено", deadline="2020-01-01", stages=["этап"])
        whys = {x["goal"]["id"]: x["why"] for x in soon.attention(now)}
        self.assertIn("до срока", whys[a["id"]])
        self.assertIn("срок прошёл", whys[late["id"]])
        self.assertTrue(any("без движения" in x["why"] for x in soon.attention(now + 20 * 86400)))


class Tool(unittest.TestCase):
    def setUp(self):
        self.g = Goals(":memory:")
        p = mock.patch.object(tg, "goals", self.g)
        p.start()
        self.addCleanup(p.stop)

    def test_flow(self):
        self.assertIn("goals", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["goals"], "projects")
        self.assertIn("пока нет", tg.tool_goals({"action": "list"}))
        out = tg.tool_goals({"action": "add", "title": "Бизнес Smart Home", "stages": STAGES})
        self.assertIn("Дальше: Исследование — рынок Ташкента", out)
        self.assertIn("25%", tg.tool_goals({"action": "step_done", "goal": "smart", "step": "рынок"}))
        self.assertIn("конкуренты", tg.tool_goals({"action": "next", "goal": "1"}))
        self.assertIn("Какой шаг", tg.tool_goals({"action": "step_done", "goal": "1", "step": "е"}))
        self.assertIn("на паузе", tg.tool_goals({"action": "pause", "id": 1}))
        with mock.patch.object(tg, "confirm", return_value=False):
            self.assertEqual(tg.tool_goals({"action": "delete", "id": 1}), "Оставила.")
        self.assertIn("нет такой цели", tg.tool_goals({"action": "show", "goal": "космос"}))


class Wiring(unittest.TestCase):
    def test_graph_and_action_center(self):
        from chloe import actions
        from chloe.goals import goals
        from chloe.graph import graph

        g = goals.add("Тестовая цель для графа", project="chloe", deadline="2020-01-01", stages=[{"title": "Этап графа", "steps": ["шаг"]}])
        nodes, _ = graph.build(fresh=True)
        self.assertIn("bigoal:{}".format(g["id"]), nodes)
        near = [x["node"]["id"] for x in graph.neighbors("bigoal:{}".format(g["id"]))]
        self.assertIn("gstep:{}".format(g["stages"][0]["id"]), near)
        self.assertTrue(any(w.get("kind") == "goal" and w["id"] == g["id"] for w in actions.waiting()))
        goals.delete(g["id"])


if __name__ == "__main__":
    unittest.main()
