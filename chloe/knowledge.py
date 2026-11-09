"""База знаний из документов пользователя: «Хлоя, изучи эти файлы» → «Что мы решили про Voice Studio?».

Документы (PDF, Word, тексты, Markdown, HTML) разбираются на фрагменты и хранятся в ~/.chloe/chloe.db
(таблицы kb_docs и kb_chunks — полнотекстовый поиск SQLite FTS5). Поэтому они попадают в ежедневные копии
вместе с напоминаниями и журналом. Сами файлы не копируются и не меняются — только читаются.
Ответ всегда с источником: название документа и страница.
"""
import hashlib
import pathlib
import re
import sqlite3
import threading
import time

from .config import JOURNAL_FILE

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".rst", ".org", ".yaml", ".yml"}
HTML_EXT = {".html", ".htm"}
SUPPORTED = TEXT_EXT | HTML_EXT | {".pdf", ".docx"}
MAX_FILE = 50 << 20          # больше — скорее всего не документ, а архив или видео
MAX_CHARS = 2_000_000        # длинная книга — да, вся библиотека в одном файле — нет
MAX_FILES = 300              # за один раз из папки
CHUNK, OVERLAP = 900, 150    # символов во фрагменте и перекрытие соседних
STOP = set("""и в во на не что как это мы вы ты он она они я по за из к ко от до для о об про с со у же ли бы
то та те тот эта этот эти там тут где когда был была были быть есть все всё его её их мне меня нам нас
или но а да нет уже ещё так очень можно нужно надо какой какая какие каких который которая которые
the a an of to in on for and or is are was were be by with at from this that what which how""".split())


def _stem(word):
    """Грубая основа слова: «решили» и «решение» сходятся на «реш…» — для русского этого хватает."""
    if len(word) <= 4:
        return word
    return word[:max(4, len(word) - 3)] if len(word) > 6 else word[:max(4, len(word) - 2)]


def fts_query(text):
    words = [w for w in re.findall(r"[\w]+", text.lower().replace("ё", "е")) if len(w) > 1 and w not in STOP]
    stems = list(dict.fromkeys(_stem(w) for w in words))[:12]
    return " OR ".join('"{}"*'.format(s.replace('"', "")) for s in stems)


def chunks(text, size=CHUNK, overlap=OVERLAP):
    """Фрагменты по абзацам и предложениям: не режем слово и по возможности мысль."""
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = max(text.rfind("\n\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
            if cut > start:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        nxt = re.search(r"\s", text[start:end])          # перекрытие начинаем с целого слова
        if nxt:
            start += nxt.end()
    return out


def extract(path):
    """[(страница, текст)] из файла. Страница — у PDF; у остальных 0."""
    p = pathlib.Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        import logging

        logging.getLogger("pypdf").setLevel(logging.ERROR)   # эмодзи в PDF — предупреждения в лог Chloe не нужны
        pages = []
        try:
            from pypdf import PdfReader

            for i, page in enumerate(PdfReader(str(p)).pages, 1):
                pages.append((i, page.extract_text() or ""))
        except Exception:
            pages = []
        if not any(t.strip() for _, t in pages):   # pypdf ничего не достал — пробуем pdfplumber
            try:
                import pdfplumber

                with pdfplumber.open(str(p)) as pdf:
                    pages = [(i, pg.extract_text() or "") for i, pg in enumerate(pdf.pages, 1)]
            except Exception:
                pass
        return pages
    if ext == ".docx":
        from docx import Document

        return [(0, "\n".join(par.text for par in Document(str(p)).paragraphs))]
    raw = p.read_text(encoding="utf-8", errors="replace")
    if ext in HTML_EXT:
        raw = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
        import html

        raw = html.unescape(raw)
    return [(0, raw)]


class Knowledge:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS kb_docs (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL, title TEXT NOT NULL, kind TEXT, pages INTEGER,
            chars INTEGER, sha1 TEXT, added REAL)""")
        self.db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks USING fts5(
            text, doc_id UNINDEXED, page UNINDEXED, tokenize = 'unicode61 remove_diacritics 2')""")
        self.db.commit()

    # --- добавить ---
    def files_in(self, path):
        p = pathlib.Path(path)
        if p.is_file():
            return [p]
        found = []
        for f in sorted(p.rglob("*")):
            if f.is_file() and f.suffix.lower() in SUPPORTED and not any(part.startswith(".") for part in f.relative_to(p).parts):
                found.append(f)
                if len(found) >= MAX_FILES:
                    break
        return found

    def add(self, path):
        """Изучает файл. Возвращает (документ, что произошло): new / updated / same / empty / unsupported / too_big."""
        p = pathlib.Path(path)
        if p.suffix.lower() not in SUPPORTED:
            return None, "unsupported"
        if p.stat().st_size > MAX_FILE:
            return None, "too_big"
        pages = extract(p)
        text_len = sum(len(t) for _, t in pages)
        if not text_len or not any(t.strip() for _, t in pages):
            return None, "empty"   # например, скан без текстового слоя
        sha1 = hashlib.sha1("\n".join(t for _, t in pages).encode("utf-8", "replace")).hexdigest()
        with self.lock:
            same = self.db.execute("SELECT * FROM kb_docs WHERE sha1 = ?", (sha1,)).fetchone()
            if same:
                return dict(same), "same"
            old = self.db.execute("SELECT * FROM kb_docs WHERE path = ?", (str(p),)).fetchone()
            if old:
                self._delete(old["id"])
            cur = self.db.execute(
                "INSERT INTO kb_docs (path, title, kind, pages, chars, sha1, added) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(p), p.stem.replace("_", " "), p.suffix.lower().lstrip("."), len(pages), text_len, sha1, time.time()))
            doc_id = cur.lastrowid
            total = 0
            for page, text in pages:
                for piece in chunks(text[:MAX_CHARS]):
                    self.db.execute("INSERT INTO kb_chunks (text, doc_id, page) VALUES (?, ?, ?)", (piece, doc_id, page))
                    total += len(piece)
                    if total > MAX_CHARS:
                        break
            self.db.commit()
            doc = dict(self.db.execute("SELECT * FROM kb_docs WHERE id = ?", (doc_id,)).fetchone())
        return doc, "updated" if old else "new"

    # --- найти ---
    def search(self, question, limit=6, doc_id=None):
        q = fts_query(question)
        if not q:
            return []
        sql = ("SELECT kb_chunks.text, kb_chunks.page, kb_docs.id AS doc_id, kb_docs.title, kb_docs.path, "
               "bm25(kb_chunks) AS score FROM kb_chunks JOIN kb_docs ON kb_docs.id = kb_chunks.doc_id "
               "WHERE kb_chunks MATCH ?" + (" AND kb_chunks.doc_id = ?" if doc_id else "") + " ORDER BY score LIMIT ?")
        args = (q, doc_id, limit) if doc_id else (q, limit)
        with self.lock:
            try:
                return [dict(r) for r in self.db.execute(sql, args)]
            except sqlite3.OperationalError:
                return []

    # --- список и удаление ---
    def docs(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM kb_docs ORDER BY added DESC")]

    def get(self, doc_id):
        with self.lock:
            r = self.db.execute("SELECT * FROM kb_docs WHERE id = ?", (doc_id,)).fetchone()
        return dict(r) if r else None

    def _delete(self, doc_id):
        self.db.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))
        self.db.execute("DELETE FROM kb_docs WHERE id = ?", (doc_id,))

    def forget(self, doc_id):
        with self.lock:
            self._delete(doc_id)
            self.db.commit()


knowledge = Knowledge(JOURNAL_FILE)
