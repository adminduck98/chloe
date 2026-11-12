"""Стикмен-стили: как выглядит мультфильм и его герой — одинаково в каждом кадре.

Приём из режиссуры стикмен-роликов (stickman-video-director, MIT): у героя есть «паспорт» — неизменное описание,
которое вставляется в описание КАЖДОГО кадра дословно. Без этого нейросеть рисует в каждой сцене другого человечка.
Паспорт и фон — по-английски: так их точнее понимают генераторы картинок и видео. Закадровый текст — по-русски.

Стиль выбирает пользователь («в тёмном стиле», «как пещерные люди»); не выбрал — сценарист подбирает по теме.
"""

STYLES = {
    "classic_light": {
        "name": "Классика, светлый",
        "when": "объяснения, идеи, обучение, логика — чисто и понятно",
        "anchor": ("a minimalist 2D stick figure: hollow round head outline, single-line torso, two thin arms and two thin legs, "
                   "uniform medium black line weight, no clothes, simple line face only when emotion matters"),
        "world": ("flat pure white background, no texture, no gradient; black line art; at most three bright accent colors "
                  "(vivid red, electric blue, warm gold) used only on props and graphics, never on the figure"),
        "music": "лёгкое пианино",
    },
    "classic_dark": {
        "name": "Классика, тёмный",
        "when": "тайны, психология, мотивация, «правда, которую не говорят»",
        "anchor": ("a minimalist 2D stick figure: hollow round head outline, single-line torso, two thin arms and two thin legs, "
                   "uniform medium white line weight, no clothes, simple line face only when emotion matters"),
        "world": ("flat deep black background; white glowing line art; at most three bright accent colors "
                  "(vivid red, electric blue, warm gold) on props and graphics only"),
        "music": "тихий синтезатор",
    },
    "neon_desktop": {
        "name": "Неон на экране компьютера",
        "when": "компьютеры, игры, программы, битвы стикменов внутри экрана",
        "anchor": ("a glowing 2D stick figure with a solid filled round head, thick clean limbs, bright neon outline glow, "
                   "same color and proportions in every shot; other stick characters each keep their own single neon color"),
        "world": ("inside a computer screen: dark desktop wallpaper, app windows, icons, cursor, taskbar as a playground; "
                  "crisp flat 2D animation, neon blue, red, yellow and green accents, dynamic action poses"),
        "music": "электроника, бодро",
    },
    "beanie": {
        "name": "Студия, герой в красной шапке",
        "when": "технологии, ИИ, карьера, советы, разбор инструментов",
        "anchor": ("a minimalist 2D animated stick figure wearing a bright red knit beanie (no pom-pom) and a yellow t-shirt, "
                   "simple black stick arms and legs, dark shorts, no detailed eyes"),
        "world": ("bright white studio space with a faint light-gray perspective grid on the floor, high-key lighting, "
                  "floating cyan and blue glass interface panels; strictly minimalist, no clutter, no sci-fi textures"),
        "music": "современный лёгкий бит",
    },
    "cozy": {
        "name": "Уютные истории",
        "when": "жизненные истории, чувства, рост, добрые поучительные сюжеты",
        "anchor": ("an expressive 2D cartoon character with a white filled round head, a simple expressive face, a slim white torso "
                   "and dark stick arms and legs"),
        "world": ("full-color 2D cartoon locations with soft atmospheric light (home, cafe, street, station, park); "
                  "each scene a different recognizable place, gentle colors, cinematic shot variety"),
        "music": "тёплая акустика",
    },
    "prehistoric": {
        "name": "Пещерный юмор",
        "when": "сатира, ирония, «как это было бы у древних людей», смешные аналогии",
        "anchor": ("an expressive hand-drawn cartoon caveman with a white filled round head, big expressive cartoon face, "
                   "black stick limbs and a simple animal-hide tunic"),
        "world": ("earthy prehistoric world: caves, rocks, campfire, mammoths, warm fire light, subtle paper texture, "
                  "hand-drawn 2D comedy style"),
        "music": "барабаны и юмор",
    },
    "historical": {
        "name": "Исторический мультфильм",
        "when": "история, эпохи, древние цивилизации, быт прошлого",
        "anchor": ("a cartoon character with a white filled round head and a short white neck, expressive face with solid black oval eyes, "
                   "thin black stick limbs and small black mitten-shaped hands, wearing period clothes of the story's era"),
        "world": ("full-color painterly historical setting with clean cel shading, era-correct architecture, clothes and props"),
        "music": "оркестровая, эпоха",
    },
    "action": {
        "name": "Экшен: драка на рабочем столе",
        "when": "драки, погони, трюки стикменов, «стикмен против интерфейса» — динамично, как в профессиональных стикмен-сериях",
        "anchor": ("a bold 2D stick figure with thick solid-color limbs outlined in dark ink and a solid filled round head, "
                   "simple dot eyes, each character keeps one bright color"),
        "world": ("inside a computer screen: dark desktop wallpaper, app windows, icons, cursor and taskbar as an arena; "
                  "dynamic fight choreography, smear frames, sparks, impact frames"),
        "music": "драйвовая электроника",
    },
    "whiteboard": {
        "name": "Белая доска (рисуется маркером)",
        "when": "обучение, объяснение по шагам, как это устроено, лекции — картинка появляется вслед за словами",
        "anchor": ("a minimalist hand-drawn stick figure in dark graphite marker lines: hollow round head, single-line torso and limbs, "
                   "simple line face, sketchy notebook doodle look"),
        "world": ("warm beige paper background (#F5EBD7), minimalist hand-drawn sketch, dark graphite lines, lots of empty space, "
                  "only red, orange and blue as small concept accents; no text, no photo details, no 3D, no textures"),
        "music": "тихое пианино или без музыки",
    },
}
DEFAULT = "classic_light"
ALIASES = {"экшен": "action", "драк": "action", "боевик": "action", "доск": "whiteboard", "маркер": "whiteboard", "от руки": "whiteboard", "рисует": "whiteboard", "whiteboard": "whiteboard",
           "тёмн": "classic_dark", "темн": "classic_dark", "чёрн": "classic_dark", "черн": "classic_dark",
           "светл": "classic_light", "бел": "classic_light", "классик": "classic_light", "неон": "neon_desktop",
           "компьютер": "neon_desktop", "экран": "neon_desktop", "шапк": "beanie", "студи": "beanie", "уют": "cozy",
           "истори": "historical", "пещер": "prehistoric", "древн": "prehistoric"}   # основы слов: «в тёмном стиле»


def find(text):
    """Ключ стиля по ключу или по словам пользователя («в тёмном стиле») или None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in STYLES:
        return t
    for word, key in ALIASES.items():
        if word in t:
            return key
    return None


def catalog():
    """Список стилей для сценариста (и для ответа «какие есть стили?»)."""
    return "\n".join("- {}: «{}» — {}".format(k, v["name"], v["when"]) for k, v in STYLES.items())


def frame(picture, key, characters=""):
    """Описание кадра для генератора: паспорт героя + действие кадра + мир стиля. Паспорт — дословно, в каждом кадре."""
    s = STYLES.get(key) or STYLES[DEFAULT]
    cast = (characters or "").strip() or s["anchor"]
    return "{}. Characters: {}. Style: {}. No text, letters or numbers in the image.".format(picture.strip().rstrip("."), cast, s["world"])
