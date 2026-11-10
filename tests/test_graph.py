"""Граф связей и Timeline: узлы подставлены, база — в памяти."""
import unittest
from unittest import mock

from chloe.graph import Graph
from chloe.permissions import TOOL_CATEGORY
from chloe.tools import HANDLERS
from chloe.tools import links

T = 1794300000.0


def nodes():
    filler = [{"id": "note:%d" % i, "type": "idea", "title": "Заметка номер %d про разное" % i, "text": "", "ts": T, "project": "chloe"}
              for i in range(50, 62)]
    return [
        {"id": "project:chloe", "type": "project", "title": "chloe", "text": "", "ts": T - 9000},
        {"id": "task:1", "type": "task", "title": "Voice Studio: озвучка и аудиокниги", "text": "", "ts": T - 5000, "project": "chloe",
         "status": "done", "done_at": T - 100},
        {"id": "note:2", "type": "idea", "title": "Voice Studio: озвучка видео и аудиокниги", "text": "", "ts": T - 8000, "project": "chloe"},
        {"id": "doc:3", "type": "doc", "title": "Chloe Voice Studio Concept", "text": "озвучка, аудиокниги и голос", "ts": T - 7000, "path": "/x.pdf"},
        {"id": "task:4", "type": "task", "title": "Финансы: подписки и платежи", "text": "", "ts": T - 4000, "project": "chloe", "status": "todo",
         "done_at": None},
        {"id": "memory:5", "type": "memory", "title": "Обращаться к пользователю «босс»", "text": "", "ts": T - 3000},
    ] + filler


class Base(unittest.TestCase):
    def setUp(self):
        self.g = Graph(":memory:", sources=nodes)


class Links(Base):
    def test_project_and_auto_links_with_reason(self):
        near = {x["node"]["id"]: x for x in self.g.neighbors("task:1")}
        self.assertEqual(near["project:chloe"]["kind"], "project")
        self.assertEqual(near["note:2"]["kind"], "auto")
        self.assertIn("общее:", near["note:2"]["why"])
        self.assertIn("doc:3", near)
        self.assertNotIn("task:4", near)                          # финансы с озвучкой не связаны
        self.assertEqual([x["node"]["id"] for x in self.g.neighbors("memory:5")], [])

    def test_manual_link_and_unlink(self):
        self.assertTrue(self.g.link("memory:5", "task:4", "босс просил"))
        x = self.g.neighbors("memory:5")[0]
        self.assertEqual((x["node"]["id"], x["kind"], x["why"]), ("task:4", "manual", "босс просил"))
        self.assertTrue(self.g.unlink("task:4", "memory:5"))
        self.assertEqual(self.g.neighbors("memory:5"), [])
        self.assertFalse(self.g.link("memory:5", "нет:1"))

    def test_hidden_auto_link_stays_hidden(self):
        self.assertTrue(self.g.unlink("task:1", "note:2"))
        self.assertNotIn("note:2", [x["node"]["id"] for x in self.g.neighbors("task:1")])
        self.g.build(fresh=True)
        self.assertNotIn("note:2", [x["node"]["id"] for x in self.g.neighbors("task:1")])
        self.g.link("task:1", "note:2")                           # вручную — возвращается
        self.assertIn("note:2", [x["node"]["id"] for x in self.g.neighbors("task:1")])

    def test_project_link_cannot_be_removed(self):
        self.assertFalse(self.g.unlink("task:1", "project:chloe"))


class Find(Base):
    def test_by_id_number_and_words(self):
        self.assertEqual(self.g.find("doc:3")[0]["id"], "doc:3")
        self.assertEqual(self.g.find("задача 4")[0]["id"], "task:4")
        self.assertEqual(self.g.find("подписки")[0]["id"], "task:4")
        self.assertEqual(self.g.find("ничего такого xyz"), [])


class Timeline(Base):
    def test_order_done_event_and_filters(self):
        ev = self.g.timeline(limit=100)
        self.assertEqual(ev[0]["node"]["id"], "note:50")           # самое новое
        done = [e for e in ev if e["what"] == "сделана задача"]
        self.assertEqual(done[0]["node"]["id"], "task:1")
        self.assertTrue(all(a["ts"] >= b["ts"] for a, b in zip(ev, ev[1:])))
        ids = {e["node"]["id"] for e in self.g.timeline(query="doc:3")}
        self.assertEqual(ids, {"doc:3", "task:1", "note:2"})        # документ и то, что с ним связано
        self.assertEqual(len(self.g.timeline(days=1, now=T + 10 * 86400)), 0)


class Tool(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(links, "graph", self.g)
        p.start()
        self.addCleanup(p.stop)

    def test_registered(self):
        self.assertIn("knowledge_map", HANDLERS)
        self.assertEqual(TOOL_CATEGORY["knowledge_map"], "knowledge")

    def test_related_timeline_link(self):
        out = links.tool_knowledge_map({"query": "Voice Studio Concept"})
        self.assertTrue(out.startswith(links.NOTE))
        self.assertIn("[task:1]", out)
        self.assertIn("сделана задача", links.tool_knowledge_map({"action": "timeline"}))
        self.assertIn("Связала", links.tool_knowledge_map({"action": "link", "a": "memory:5", "b": "подписки"}))
        self.assertIn("Убрала связь", links.tool_knowledge_map({"action": "unlink", "a": "memory:5", "b": "task:4"}))
        self.assertIn("Не нашла", links.tool_knowledge_map({"query": "xyz qwe"}))
        self.assertIn("объектов", links.tool_knowledge_map({"action": "stats"}))


class RealData(unittest.TestCase):
    def test_builds_from_chloe_stores_and_window_api(self):
        from chloe.app import Api
        from chloe.graph import graph

        graph.build(fresh=True)
        ov = Api().graph_overview()
        self.assertIn("nodes", ov["stats"])
        self.assertIsInstance(Api().graph_timeline("", 0), list)
        self.assertIsNone(Api().graph_node("task:999999"))


if __name__ == "__main__":
    unittest.main()
