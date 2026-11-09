"""Настройки, которые Chloe узнаёт в разговоре (город пользователя). Файл ~/.chloe/settings.json — его можно открыть и поправить."""
import json
import threading

from .config import SETTINGS_FILE


class Settings:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, key, default=None):
        with self.lock:
            return self._load().get(key, default)

    def set(self, key, value):
        with self.lock:
            data = self._load()
            data[key] = value
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)


settings = Settings(SETTINGS_FILE)
