"""Экран, мышь и клавиатура."""
import base64
import io
import time

from ..config import OS_NAME


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True   # мышь в левый верхний угол = аварийная остановка
    pyautogui.PAUSE = 0.12
    return pyautogui


state = {"ratio": 1.0}   # во сколько раз экран больше скриншота


def tool_screenshot(_):
    pg = _pyautogui()
    img = pg.screenshot()
    logical_w, _h = pg.size()
    target_w = min(1280, img.width)
    new_h = int(img.height * target_w / img.width)
    img = img.resize((target_w, new_h))
    state["ratio"] = logical_w / target_w
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)   # в 4–6 раз легче PNG: до модели доходит быстрее
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.standard_b64encode(buf.getvalue()).decode()}},
        {"type": "text", "text": "Скриншот {}x{} пикселей.".format(target_w, new_h)},
    ]


def tool_mouse_click(a):
    pg = _pyautogui()
    pg.click(int(a["x"] * state["ratio"]), int(a["y"] * state["ratio"]),
             clicks=2 if a.get("double") else 1, button=a.get("button", "left"))
    return "Клик выполнен."


def tool_type_text(a):
    import pyperclip

    pg = _pyautogui()
    try:
        saved = pyperclip.paste()
    except Exception:
        saved = None
    pyperclip.copy(a["text"])
    pg.hotkey("command" if OS_NAME == "Darwin" else "ctrl", "v")
    if saved is not None:
        time.sleep(0.3)   # даём программе забрать текст, потом возвращаем буфер обмена пользователя
        pyperclip.copy(saved)
    if a.get("press_enter"):
        pg.press("enter")
    return "Текст введён."


def tool_press_keys(a):
    pg = _pyautogui()
    keys = [k.lower() for k in a["keys"]]
    if OS_NAME == "Darwin" and len(keys) > 1:
        keys = ["command" if k in ("ctrl", "control") else k for k in keys]
    pg.press(keys[0]) if len(keys) == 1 else pg.hotkey(*keys)
    return "Нажато: " + "+".join(keys)


def tool_scroll(a):
    _pyautogui().scroll(int(a["amount"]))
    return "Прокручено."
