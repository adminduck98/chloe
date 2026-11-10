"""Self-Improvement Lab: проблемы из журнала, предложение, защита, проверка и внедрение. Модель и песочница подменены;
внедрение — во временный git-репозиторий, не в настоящий проект."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from chloe import lab as L
from chloe.journal import journal
from chloe.lab import Lab
from chloe.tools import HANDLERS
from chloe.tools import improve

GOOD = "--- a/chloe/news.py\n+++ b/chloe/news.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"


def answer(**kw):
    return lambda prompt: "Вот ответ:\n" + json.dumps(dict({"diagnosis": "причина", "summary": "станет лучше"}, **kw), ensure_ascii=False)


class Problems(unittest.TestCase):
    def test_grouped_refusals_skipped(self):
        for chat in ("Облако UZ", "Onepress", "Облако"):
            journal.add("tool", "Telegram", "tg_read", {"tool": "tg_read", "args": {"chat": chat}, "result": "Не найдено чата «{}» в Telegram.".format(chat)}, ok=False)
        journal.add("tool", "Команды", "run_command", {"tool": "run_command", "args": {}, "result": "Пользователь отклонил команду."}, ok=False)
        journal.add("heard", "Голос", "нет, неправильно, я же сказал закрыть только браузер")
        found = L.problems(1)
        tg = next(p for p in found if p["tool"] == "tg_read")
        self.assertEqual(tg["count"], 3)                                    # три разных чата — одна проблема
        self.assertEqual(len(tg["examples"]), 3)
        self.assertFalse(any(p["tool"] == "run_command" for p in found))    # отказ пользователя — не ошибка
        self.assertTrue(any(p["kind"] == "correction" for p in found))

    def test_normalize(self):
        self.assertEqual(L.normalize("Не найдено окно «Google Cloud» за 12 с"), L.normalize("Не найдено окно «Telegram» за 3 с"))


class Guard(unittest.TestCase):
    def test_check_diff(self):
        self.assertIsNone(L.check_diff(GOOD))
        for bad, why in ((GOOD.replace("chloe/news.py", "chloe/permissions.py"), "защитный слой"),
                         (GOOD.replace("chloe/news.py", "chloe/lab.py"), "защитный слой"),
                         (GOOD.replace("chloe/news.py", "tests/test_security.py"), "защитный слой"),
                         (GOOD.replace("chloe/news.py", "../.bashrc"), "вне кода"),
                         ("--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,2 +1,1 @@\n-def test_one(self):\n-    pass\n+x\n", "удаляет тесты"),
                         (GOOD.replace("+x = 2", "+@unittest.skip('мешает')"), "выключает тесты"),
                         (GOOD.replace("+x = 2", "+print(os.environ['DEEPSEEK_API_KEY'])"), "ключи"),
                         ("", "пустой")):
            self.assertIn(why, L.check_diff(bad) or "", bad[:60])


class Propose(unittest.TestCase):
    def setUp(self):
        self.lab = Lab(":memory:")
        self.issue = {"key": "k", "kind": "tool", "title": "tg_read: не найдено", "tool": "tg_read", "count": 5, "examples": [{"x": 1}]}

    def test_lesson_ready_at_once(self):
        iid, problem = L.propose(self.issue, self.lab, answer(kind="lesson", lesson="Сначала спроси точное название чата."))
        item = self.lab.get(iid)
        self.assertEqual((item["kind"], item["status"], problem), ("lesson", "ready", None))

    def test_code_to_protected_file_rejected(self):
        iid, problem = L.propose(self.issue, self.lab, answer(kind="code", diff=GOOD.replace("news.py", "security.py")))
        self.assertIn("защитный слой", problem)
        self.assertEqual(self.lab.get(iid)["status"], "rejected")

    def test_none_and_bad_answers(self):
        iid, _ = L.propose(self.issue, self.lab, answer(kind="none", diagnosis="сайт был недоступен"))
        self.assertEqual(self.lab.get(iid)["kind"], "none")
        with self.assertRaises(L.LabError):
            L.propose(self.issue, self.lab, lambda p: "не знаю")
        with self.assertRaises(L.LabError):
            L.propose(self.issue, self.lab, answer(kind="lesson", lesson=""))

    def test_prompt_shows_module_source(self):
        seen = {}
        L.propose(self.issue, self.lab, lambda p: seen.setdefault("p", p) and answer(kind="none")(p))
        self.assertIn("def find_chat", seen["p"])                           # помощники инструмента видны модели
        self.assertIn("chloe/permissions.py", seen["p"])                    # и список того, что трогать нельзя


class ApplyInTempRepo(unittest.TestCase):
    """Внедрение и отмена — на временном репозитории."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="lab-repo-")
        os.makedirs(os.path.join(self.repo, "chloe"))
        with open(os.path.join(self.repo, "chloe", "news.py"), "w") as f:
            f.write("x = 1\n")
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "."], ["commit", "-qm", "init"]):
            subprocess.run(["git", "-C", self.repo] + cmd, check=True, capture_output=True)
        p = mock.patch.object(L, "PROJECT", self.repo)
        p.start()
        self.addCleanup(p.stop)
        self.lab = Lab(":memory:")

    def item(self, status="ready"):
        iid = self.lab.add({"key": "k", "title": "тест"}, "code", "причина", diff=GOOD, files=["chloe/news.py"])
        self.lab.set(iid, status=status, test_result="тесты прошли: 1 шт.")
        return self.lab.get(iid)

    def test_apply_commits_and_undo_reverts(self):
        sha = L.apply(self.item())
        with open(os.path.join(self.repo, "chloe", "news.py")) as f:
            self.assertEqual(f.read(), "x = 2\n")
        log = subprocess.run(["git", "-C", self.repo, "log", "-1", "--format=%s"], capture_output=True, text=True).stdout
        self.assertIn("Self-Improvement Lab", log)
        item = dict(self.lab.get(1), commit_sha=sha)
        L.undo(item)
        with open(os.path.join(self.repo, "chloe", "news.py")) as f:
            self.assertEqual(f.read(), "x = 1\n")

    def test_untested_or_dirty_refused(self):
        with self.assertRaises(L.LabError):
            L.apply(self.item(status="failed"))
        with open(os.path.join(self.repo, "chloe", "news.py"), "a") as f:
            f.write("# правка человека\n")
        with self.assertRaises(L.LabError) as c:
            L.apply(self.item())
        self.assertIn("несохранённые", str(c.exception))

    def test_test_patch_uses_sandbox_and_cleans_up(self):
        with mock.patch("chloe.sandbox.available", return_value=True), \
                mock.patch("chloe.sandbox.try_command", return_value={"ran": True, "output": "Ran 5 tests in 1s\nOK\n", "timeout": False}) as t:
            ok, rep = L.test_patch(GOOD)
        self.assertTrue(ok)
        self.assertIn("5 шт.", rep)
        self.assertIn("unittest discover", t.call_args[0][0])
        wts = subprocess.run(["git", "-C", self.repo, "worktree", "list"], capture_output=True, text=True).stdout
        self.assertEqual(len(wts.strip().splitlines()), 1)                    # копия удалена
        with mock.patch("chloe.sandbox.available", return_value=True), \
                mock.patch("chloe.sandbox.try_command", return_value={"ran": True, "output": "FAIL: x\nRan 5 tests\nFAILED (failures=1)", "timeout": False}):
            self.assertFalse(L.test_patch(GOOD)[0])
        self.assertIn("не ложится", L.test_patch(GOOD.replace("-x = 1", "-y = 7"))[1])


class Tool(unittest.TestCase):
    def setUp(self):
        self.lab = Lab(":memory:")
        p = mock.patch.object(improve, "lab", self.lab)
        p.start()
        self.addCleanup(p.stop)

    def test_flow(self):
        self.assertIn("self_improve", HANDLERS)
        with mock.patch.object(L, "problems", return_value=[]):
            self.assertIn("ошибок нет", improve.tool_self_improve({"action": "review"}))
        iid = self.lab.add({"key": "k", "title": "тест"}, "lesson", "причина", lesson="Сначала спроси название.")
        self.assertIn("готово к внедрению", improve.tool_self_improve({"action": "list"}))
        self.assertIn("Урок:", improve.tool_self_improve({"action": "show", "id": iid}))
        with mock.patch.object(improve, "confirm", return_value=False):
            self.assertEqual(improve.tool_self_improve({"action": "apply", "id": iid}), "Не внедряю.")
        with mock.patch.object(improve, "confirm", return_value=True), mock.patch("chloe.learning.learn_lesson") as learn:
            self.assertIn("Внедрила", improve.tool_self_improve({"action": "apply", "id": iid}))
        learn.assert_called_once_with("Сначала спроси название.")
        bad = self.lab.add({"key": "k", "title": "т"}, "code", "п", diff=GOOD, files=["chloe/news.py"])
        self.lab.set(bad, status="failed")
        self.assertIn("нельзя внедрить", improve.tool_self_improve({"action": "apply", "id": bad}))

    def test_propose_runs_in_background(self):
        issue = {"key": "k", "kind": "tool", "title": "t", "tool": "", "count": 2, "examples": []}
        said = []
        with mock.patch.object(L, "problems", return_value=[issue]), \
                mock.patch.object(L, "propose", return_value=(self.lab.add(issue, "none", "внешний сбой"), None)), \
                mock.patch.object(improve, "_say", side_effect=said.append):
            out = improve.tool_self_improve({"action": "propose", "number": 1})
            for _ in range(50):
                if said:
                    break
                time.sleep(0.05)
        self.assertIn("Начала разбирать", out)
        self.assertIn("исправлять нечего", said[0])


if __name__ == "__main__":
    unittest.main()
