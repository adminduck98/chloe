"""Инструмент system_state — «как ты?», «проверь себя», «всё ли работает?»."""
from .. import system_state as ss


def tool_system_state(a):
    items = ss.deep() if a.get("deep") else ss.quick()
    ss.save(items)
    return (ss.report(items) + "\n\nРасскажи коротко: сначала общий итог одной фразой, потом только то, что не в порядке, "
            "и что с этим сделать. Если всё хорошо — так и скажи, без перечисления.")
