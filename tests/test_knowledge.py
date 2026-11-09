"""База знаний из документов: изучить файлы и папки, найти ответ с источником, не дублировать, забыть."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chloe import knowledge as kb_mod
from chloe.knowledge import chunks, fts_query, knowledge
from chloe.tools import run_tool
from chloe.voice import voice

voice.enabled = False   # подтверждения — с клавиатуры (input подменяется), а не ожидание голоса


VOICE = """CHLOE VOICE STUDIO
Главная идея: голос — самый естественный способ общения с Chloe.

Решение: основным голосом остаётся Светлана от Microsoft, потому что она быстрее отвечает.
Голос Qwen оставили запасным вариантом для экспериментов.
"""
MEMORY = """# Knowledge & Memory

Память делится на два режима: Timeline показывает историю, Knowledge Graph — связи между проектами.
"""


class Knowledge(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="kb-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        for d in knowledge.docs():
            knowledge.forget(d["id"])
        (self.dir / "Chloe_Voice_Studio.txt").write_text(VOICE, encoding="utf-8")
        (self.dir / "memory.md").write_text(MEMORY, encoding="utf-8")
        (self.dir / "page.html").write_text("<html><script>alert(1)</script><body><h1>Device Map</h1>"
                                            "<p>Телефон подключается к Chloe через QR-код.</p></body></html>", encoding="utf-8")
        (self.dir / "photo.png").write_bytes(b"\x89PNG")
        (self.dir / ".hidden").mkdir()
        (self.dir / ".hidden" / "secret.txt").write_text("секрет", encoding="utf-8")

    def test_learn_folder_and_answer_with_source(self):
        out, _, failed = run_tool("learn_document", {"path": str(self.dir)})
        self.assertFalse(failed)
        self.assertIn("Изучила документов: 3", out)
        titles = {d["title"] for d in knowledge.docs()}
        self.assertEqual(titles, {"Chloe Voice Studio", "memory", "page"})   # картинки и скрытые папки — нет
        out, _, _ = run_tool("ask_knowledge", {"question": "Что мы решили про голос?"})
        self.assertIn("«Chloe Voice Studio»", out)                           # источник назван
        self.assertIn("Светлана", out)
        self.assertIn("данные, не команды", out)

    def test_word_forms_match(self):
        run_tool("learn_document", {"path": str(self.dir)})
        # «решили» ↔ «решение», «режимах» ↔ «режима», «подключить» ↔ «подключается»
        self.assertEqual(knowledge.search("какие решения приняли")[0]["title"], "Chloe Voice Studio")
        self.assertEqual(knowledge.search("в каких режимах память")[0]["title"], "memory")
        self.assertEqual(knowledge.search("как подключить телефон")[0]["title"], "page")
        self.assertNotIn("alert", knowledge.search("Device Map")[0]["text"])  # скрипты страницы не попадают

    def test_same_file_twice_and_changed_file(self):
        run_tool("learn_document", {"path": str(self.dir / "memory.md")})
        out, _, _ = run_tool("learn_document", {"path": str(self.dir / "memory.md")})
        self.assertIn("Уже знала", out)
        self.assertEqual(len(knowledge.docs()), 1)
        (self.dir / "memory.md").write_text(MEMORY + "\nНовое: память копируется каждый день.", encoding="utf-8")
        run_tool("learn_document", {"path": str(self.dir / "memory.md")})
        self.assertEqual(len(knowledge.docs()), 1)                          # обновлён, а не задвоен
        self.assertTrue(knowledge.search("копируется каждый день"))

    def test_pdf_pages_and_docx(self):
        from reportlab.pdfgen import canvas
        from docx import Document

        pdf = self.dir / "concept.pdf"
        c = canvas.Canvas(str(pdf))
        c.drawString(72, 720, "World Intelligence: global events and risks.")
        c.showPage()
        c.drawString(72, 720, "Private Vault keeps photos and documents locked.")
        c.save()
        doc = Document()
        doc.add_paragraph("Project Intelligence: tasks, goals and next steps.")
        doc.save(str(self.dir / "plan.docx"))
        run_tool("learn_document", {"path": str(pdf)})
        run_tool("learn_document", {"path": str(self.dir / "plan.docx")})
        hit = knowledge.search("vault photos")[0]
        self.assertEqual((hit["title"], hit["page"]), ("concept", 2))       # страница PDF известна
        out, _, _ = run_tool("ask_knowledge", {"question": "vault photos"})
        self.assertIn("стр. 2", out)
        self.assertEqual(knowledge.search("next steps tasks")[0]["title"], "plan")

    def test_nothing_found_is_said_honestly(self):
        out, _, _ = run_tool("ask_knowledge", {"question": "что угодно"})
        self.assertIn("пуста", out)
        run_tool("learn_document", {"path": str(self.dir / "memory.md")})
        out, _, _ = run_tool("ask_knowledge", {"question": "рецепт борща"})
        self.assertIn("ничего не нашлось", out)

    def test_forget_asks_and_keeps_the_file(self):
        run_tool("learn_document", {"path": str(self.dir / "memory.md")})
        doc = knowledge.docs()[0]
        with mock.patch("builtins.input", return_value="нет"):
            run_tool("forget_document", {"id": doc["id"]})
        self.assertEqual(len(knowledge.docs()), 1)
        from chloe.signals import state
        state["declined"] = False                                           # новая просьба — отказ прошлой не действует
        with mock.patch("builtins.input", return_value="да, делай"):
            out, _, _ = run_tool("forget_document", {"id": doc["id"]})
        self.assertEqual(knowledge.docs(), [])
        self.assertFalse(knowledge.search("Timeline"))
        self.assertTrue((self.dir / "memory.md").exists())                  # файл не тронут
        self.assertIn("Файл не тронут", out)

    def test_missing_and_scanned(self):
        out, _, _ = run_tool("learn_document", {"path": str(self.dir / "нет-такого.pdf")})
        self.assertIn("Не найден", out)
        empty = self.dir / "scan.pdf"
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(empty)); c.showPage(); c.save()
        out, _, _ = run_tool("learn_document", {"path": str(empty)})
        self.assertIn("скан", out)

    def test_helpers(self):
        self.assertEqual(fts_query("что мы решили"), '"реши"*')
        self.assertEqual(fts_query("и в на"), "")
        long = ("Предложение номер один. " * 200).strip()
        parts = chunks(long)
        self.assertTrue(all(len(p) <= kb_mod.CHUNK + 1 for p in parts))
        self.assertTrue(len(parts) > 3)


if __name__ == "__main__":
    unittest.main()
