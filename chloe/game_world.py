"""Игровой мир для мультфильмов «персонаж внутри игры»: экран выбора уровня с кнопкой Play, уровень-платформер
(земля из плиток, потолок, шипы, низкие балки, светящиеся порталы), уровень едет (прокрутка), гравитация
переворачивается, герой исчезает в кнопке или портале, надписи на экране.

Всё рисуется кодом (cairo) — свой яркий игровой стиль, не копия чьей-то игры. Координаты препятствий — в «мире»
(доли ширины кадра от начала уровня); на экране — со сдвигом прокрутки.
"""
import math

SKY = ((0.16, 0.08, 0.36), (0.05, 0.2, 0.45))          # градиент неба уровня: сверху вниз
GROUND_COL = (0.12, 0.75, 0.55)
TILE = (0.09, 0.55, 0.42)
SPIKE = (0.95, 0.25, 0.35)
PORTAL = (0.35, 0.95, 1.0)
CEIL = 0.16                                          # потолок уровня — доля высоты от верха


def _rr(c, x, y, w, h, r):
    c.new_sub_path()
    c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    c.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    c.close_path()


# --- экран выбора уровня ---
def select_screen(c, w, h, t, ground, play=None, glow=0.0, press=0.0, new_level=0.0):
    """Яркий экран выбора уровня: полосатый фон, плитки уровней, большая кнопка Play (play — центр (x, y))."""
    import cairo

    g = cairo.LinearGradient(0, 0, w, h)
    g.add_color_stop_rgb(0, 0.35, 0.15, 0.75)
    g.add_color_stop_rgb(1, 0.95, 0.35, 0.55)
    c.set_source(g)
    c.paint()
    c.set_source_rgba(1, 1, 1, 0.06)                                     # бегущие полосы
    for i in range(-10, 30):
        x = i * w * 0.08 + (t * w * 0.03) % (w * 0.08)
        c.move_to(x, 0)
        c.line_to(x + w * 0.04, 0)
        c.line_to(x - h * 0.6 + w * 0.04, h)
        c.line_to(x - h * 0.6, h)
        c.close_path()
        c.fill()
    s = h * 0.11                                                        # плитки уровней (без цифр — точки звёзд)
    for i in range(6):
        x, y = w * 0.06 + (i % 3) * s * 1.25, h * 0.14 + (i // 3) * s * 1.25
        c.set_source_rgba(1, 1, 1, 0.9 if i == 0 else 0.35)
        _rr(c, x, y, s, s, s * 0.18)
        c.fill()
        for j in range(3):
            c.set_source_rgb(*((1.0, 0.8, 0.2) if i == 0 else (0.6, 0.6, 0.7)))
            c.arc(x + s * (0.25 + j * 0.25), y + s * 0.78, s * 0.07, 0, 2 * math.pi)
            c.fill()
    if new_level > 0:                                                   # появляется новый уровень: плитка выпрыгивает и светится
        k = min(1.0, new_level)
        pop = k * (1 + 0.25 * math.sin(math.pi * min(1.0, k * 1.6)))
        x, y = w * 0.06 + 3 * s * 1.25 + s / 2, h * 0.14 + s / 2
        for j in range(3):
            c.set_source_rgba(1.0, 0.85, 0.3, 0.15 * (3 - j) * (0.6 + 0.4 * math.sin(t * 7)))
            _rr(c, x - s * pop * (0.6 + 0.15 * j), y - s * pop * (0.6 + 0.15 * j), s * pop * (1.2 + 0.3 * j), s * pop * (1.2 + 0.3 * j), s * 0.3)
            c.fill()
        c.set_source_rgb(1.0, 0.85, 0.3)
        _rr(c, x - s * pop / 2, y - s * pop / 2, s * pop, s * pop, s * 0.18 * pop)
        c.fill()
        c.set_source_rgb(0.95, 0.3, 0.4)                                # на плитке — шип нового уровня
        c.move_to(x - s * 0.22 * pop, y + s * 0.2 * pop)
        c.line_to(x, y - s * 0.22 * pop)
        c.line_to(x + s * 0.22 * pop, y + s * 0.2 * pop)
        c.close_path()
        c.fill()
    c.set_source_rgba(0.1, 0.05, 0.25, 0.55)                            # пол экрана — на нём стоит герой
    c.rectangle(0, ground, w, h - ground)
    c.fill()
    if play:
        draw_play(c, play, h * 0.13, t, glow, press)


def draw_play(c, at, r, t, glow=0.0, press=0.0):
    """Большая круглая кнопка Play: тень, кольцо, треугольник; press — нажата (0..1), glow — светится (0..1)."""
    x, y = at
    r2 = r * (1 - 0.08 * press)
    if glow > 0:
        for k in range(4):
            c.set_source_rgba(1.0, 0.9, 0.3, 0.12 * glow * (1 + math.sin(t * 6)) / (k + 1))
            c.arc(x, y, r2 * (1.25 + 0.25 * k), 0, 2 * math.pi)
            c.fill()
    c.set_source_rgba(0, 0, 0, 0.35)
    c.arc(x + r * 0.06, y + r * 0.12 * (1 - press), r2, 0, 2 * math.pi)
    c.fill()
    c.set_source_rgb(0.2, 0.85, 0.35)
    c.arc(x, y + r * 0.1 * press, r2, 0, 2 * math.pi)
    c.fill_preserve()
    c.set_source_rgb(0.05, 0.3, 0.12)
    c.set_line_width(r * 0.08)
    c.stroke()
    c.set_source_rgb(1, 1, 1)
    yy = y + r * 0.1 * press
    c.move_to(x - r2 * 0.28, yy - r2 * 0.42)
    c.line_to(x + r2 * 0.45, yy)
    c.line_to(x - r2 * 0.28, yy + r2 * 0.42)
    c.close_path()
    c.fill()


# --- уровень ---
def level(c, w, h, t, ground, offset, ceiling=True):
    """Уровень-платформер: небо, далёкие горы (параллакс — медленнее), земля из плиток и потолок; offset — прокрутка (пиксели)."""
    import cairo

    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgb(0, *SKY[0])
    g.add_color_stop_rgb(1, *SKY[1])
    c.set_source(g)
    c.paint()
    c.set_source_rgba(1, 1, 1, 0.5)                                     # звёзды
    for i in range(40):
        sx = ((i * 197.3 - offset * 0.1) % w)
        sy = (i * 71.7) % (h * 0.55) + h * 0.18
        c.arc(sx, sy, max(1.0, h * 0.0025), 0, 2 * math.pi)
        c.fill()
    c.set_source_rgba(0.3, 0.15, 0.55, 0.8)                             # горы (параллакс)
    c.move_to(0, ground)
    for i in range(0, 14):
        x = i * w * 0.12 - (offset * 0.3) % (w * 0.24)
        c.line_to(x, ground - h * (0.18 if i % 2 else 0.08))
    c.line_to(w, ground)
    c.close_path()
    c.fill()
    _tiles(c, w, h, ground, h - ground, offset)                          # земля
    if ceiling:
        _tiles(c, w, h, 0, h * CEIL, offset, top=True)


def _tiles(c, w, h, y, hh, offset, top=False):
    s = h * 0.06
    c.set_source_rgb(*TILE)
    c.rectangle(0, y, w, hh)
    c.fill()
    c.set_source_rgb(*GROUND_COL)
    edge = y + hh - s * 0.25 if top else y
    c.rectangle(0, edge, w, s * 0.25)
    c.fill()
    c.set_source_rgba(0, 0, 0, 0.18)
    c.set_line_width(max(1.0, h * 0.002))
    x0 = -(offset % s)
    for i in range(int(w / s) + 2):
        c.move_to(x0 + i * s, y)
        c.line_to(x0 + i * s, y + hh)
    c.stroke()


def draw_spike(c, x, base, size, up=True):
    """Острый треугольный шип (up=False — растёт с потолка вниз)."""
    s = size * (1 if up else -1)
    c.move_to(x - size * 0.5, base)
    c.line_to(x, base - s * 1.1)
    c.line_to(x + size * 0.5, base)
    c.close_path()
    c.set_source_rgb(*SPIKE)
    c.fill_preserve()
    c.set_source_rgb(0.25, 0.02, 0.08)
    c.set_line_width(size * 0.08)
    c.stroke()
    c.set_source_rgba(1, 1, 1, 0.35)                                     # блик
    c.move_to(x - size * 0.15, base - s * 0.2)
    c.line_to(x - size * 0.02, base - s * 0.85)
    c.line_to(x + size * 0.04, base - s * 0.25)
    c.close_path()
    c.fill()


def draw_barrier(c, x, ground, size, h):
    """Низкая балка на столбах: под ней — только подкатом."""
    top = ground - size * 0.55
    c.set_source_rgb(0.98, 0.75, 0.2)
    c.rectangle(x - size * 0.8, top - size * 0.14, size * 1.6, size * 0.14)
    c.fill()
    c.set_source_rgb(0.15, 0.1, 0.05)
    for dx in (-0.8, 0.0, 0.8):                                         # чёрно-жёлтые полосы
        c.rectangle(x + size * (dx - 0.05) * 0.95, top - size * 0.14, size * 0.12, size * 0.14)
    c.fill()
    c.set_source_rgb(0.5, 0.5, 0.6)
    for dx in (-0.75, 0.75):
        c.rectangle(x + size * dx - size * 0.04, top, size * 0.08, ground - top)
    c.fill()


def draw_portal(c, x, ground, size, t, flip=False):
    """Светящийся овальный портал: вращающиеся кольца и искры."""
    cy = ground - size * 0.6 if not flip else size * 0.6 + ground
    for k in range(5, 0, -1):
        c.save()
        c.translate(x, cy)
        c.scale(0.45, 1.0)
        c.set_source_rgba(*PORTAL, 0.12 * k)
        c.arc(0, 0, size * (0.55 + 0.06 * k + 0.02 * math.sin(t * 8 + k)), 0, 2 * math.pi)
        c.fill()
        c.restore()
    c.save()
    c.translate(x, cy)
    c.scale(0.45, 1.0)
    c.set_line_width(size * 0.08)
    c.set_source_rgb(1, 1, 1)
    c.arc(0, 0, size * 0.55, 0, 2 * math.pi)
    c.stroke()
    c.restore()
    for i in range(10):                                                  # искры по кругу
        a = t * 3 + i * 0.63
        c.set_source_rgba(1, 1, 1, 0.8)
        c.arc(x + math.cos(a) * size * 0.28, cy + math.sin(a) * size * 0.62, size * 0.025, 0, 2 * math.pi)
        c.fill()


def title(c, w, h, text, k=1.0):
    """Надпись на экране крупно по центру (k — проявление 0..1)."""
    c.save()
    c.identity_matrix()
    c.select_font_face("Noto Sans", 0, 1)
    c.set_font_size(h * 0.09)
    ext = c.text_extents(text)
    x, y = (w - ext.width) / 2 - ext.x_bearing, h / 2 - ext.height / 2 - ext.y_bearing
    c.set_source_rgba(1, 1, 1, k)
    c.move_to(x, y)
    c.show_text(text)
    c.restore()
