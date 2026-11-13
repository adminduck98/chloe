# Как устроена Chloe

Код лежит в одной папке-пакете `chloe/`, по файлу на каждую часть. Запускает его `run.py`.

## Как проходит одна просьба

```
микрофон ──► voice.record()      поток записи: микрофон открыт всегда, режет речь на части
             │ audio_q
             ▼
             voice.listener()    поток слуха: распознаёт части (Google); пока Chloe занята — ловит только «стоп»
             │ heard_q
             ▼
app.assistant()                  главный цикл
  finish_speech()                дослушать: склеить части, сказанные с паузами
  strip_wake()                   обращались ли к «Хлое»
  journal.add("heard")           записать просьбу
  thinking.think()               модель думает и вызывает инструменты
    └─ router.Route              быстрый мозг; сильный — для сложного (слова, сложный инструмент, ошибка, много шагов)
    └─ tools.run_tool()          выполнить инструмент, показать в мозге, записать в журнал
         └─ voice.confirm()      необратимое — только после «да»
  voice.say()                    ответить голосом
```

«Стоп» в любой момент ставит `signals.interrupt`: голос замолкает, оставшиеся шаги не выполняются,
история разговора закрывается репликой «Остановилась», чтобы следующая просьба начиналась как обычно.

## Файлы

| Файл | За что отвечает | От чего зависит |
|---|---|---|
| `config.py` | пути, ключи, модели, голос, слова; переменные `CHLOE_*` | — |
| `signals.py` | общие сигналы потоков: `busy`, `interrupt`, очереди `audio_q`, `heard_q`, `commands` | config |
| `brain.py` | мост к окну с мозгом (`brain.use`, `brain.state`…) | — |
| `journal.py` | журнал событий в `~/.chloe/chloe.db`, скриншоты в `~/.chloe/screens` | brain, config |
| `changes.py` | изменения файлов (таблица `changes` в `chloe.db`) и их отмена; копии заменённого в `~/.chloe/backups` | brain, journal, config |
| `settings.py` | то, что Chloe узнала о месте пользователя (город) — `~/.chloe/settings.json` | config |
| `telegram.py` | Telegram от имени пользователя (Telethon, свой цикл asyncio в потоке); вход `--login-telegram`, сессия `~/.chloe/telegram.session` | config |
| `reminders.py` | напоминания и таймеры (таблица `reminders` в `chloe.db`), поток `watcher` озвучивает в срок | journal, signals, config |
| `experience.py` | мозг как карта опыта: предметы из мира пользователя в шаге (`things_of`), какие воспоминания пригодились (`recalled`) | config |
| `topics.py` | зоны по смыслу: темы из того, что встречается вместе в задачах журнала; названия — быстрая модель или частые слова | journal, memory, settings, experience |
| `sleep.py` | настоящий сон: ночью объединяет повторы в памяти, помечает важное, отчёт → `chloeSleep` в мозге | memory, journal, settings |
| `skillbook.py` | навыки Claude: папки с SKILL.md в `~/.chloe/skills` и `skills/`, подсказка, установка (`--add-skill`) | config |
| `remote.py` | телефон-пульт: HTTPS в домашней сети, код входа, белый список методов `Api`, события мозга (long-poll); страница — `ui/remote.js` | config |
| `snapshots.py` | копии мозга и памяти: раз в день и перед стиранием, 7 дней; `--restore` | config |
| `memory.py` | память о пользователе в `~/.chloe/memory.json`; `forget_memory`, `rewrite_memory` | brain, config |
| `ears.py` | офлайн-слух Vosk: слышит «Хлоя» без интернета, `~/.chloe/ears` | config, signals |
| `voice.py` | слух (`route_phrase`: офлайн решает, что отправлять в Google), голос (Светлана → Piper → системный), `confirm()` | ears, brain, journal, signals, config |
| `speech_stream.py` | голос потоком: Светлана говорит с первого кусочка звука (miniaudio), следующая часть качается, пока звучит эта | — |
| `youtube_api.py` | YouTube-канал пользователя: статистика и ролики, только чтение (Data + Analytics API); вход — общий OAuth-клиент с календарём, свой токен `youtube_token.json` | google_calendar, config |
| `publish.py` | пакет «к публикации»: обложки, название, описание с главами, теги, субтитры — для мультфильмов Chloe и для любого видео пользователя (`package_video`, Shorts — свой пакет) | clipper, studio, screenplay |
| `holyarrs.py` | медиасервер [HolyArrs](https://github.com/HolyArrs/HolyArrs) в Docker (`~/holyarrs`, порт 6262): загрузки, календарь, поиск, медиатека, запросы (`POST /api/v1/asks`, без дублей); ключ `HOLYARRS_KEY` в keys.env; поток `watcher` раз в 3 минуты говорит, что запрошенное стало «available» (не ночью, не посреди разговора, каждое — один раз, `holyarrs_announced` в settings) | config, settings, voice, signals |
| `tools/` | всё, что Chloe умеет делать | voice, memory, journal, brain |
| `thinking/` | мышление: `prompt.py` (системная подсказка), `router.py` (быстрый или сильный мозг), `claude.py`, `gemini.py`, `openai_chat.py` (Qwen и DeepSeek), `claude_bridge.py` (Claude вместе с ними) | tools, memory, journal, signals |
| `app.py` | главный цикл, окно (pywebview), `Api` для страницы мозга | всё выше |
| `ui/chloe-mind.html` | страница мозга (three.js); панели «Журнал», «Память», «Статистика» | вызывает `Api` |

Зависимости идут только сверху вниз по этой таблице — так нет циклических импортов.

## Куда добавлять новое

**Новый инструмент, который меняет файлы**: перед заменой — `replacing(dst, операция)` из `tools/files.py`,
после — `changes.record(...)`; тогда появится в панели «Файлы» и отменится.

**Новый инструмент** (например, громкость):
1. В подходящий файл `tools/` (или новый) — функция `tool_<имя>(a)`, возвращает строку для модели.
   Необратимое — через `confirm("…?")`. Пути пользователя — через `P()` и проверки из `tools/paths.py`.
2. Новый файл добавить в список модулей в `tools/__init__.py` (`HANDLERS`).
3. В `tools/__init__.py`: описание в `TOOLS` (для модели) и навык в `SKILLS` (нейрон в мозге).
4. Тест в `tests/`.

Журнал, мозг и «стоп» подключаются сами — через `run_tool()`.

**Новая модель** (например, ChatGPT): файл `thinking/<имя>.py` с `think_<имя>(client, history, text)`,
выбор в `thinking/__init__.py` (`think`, `forget_old`, `make_client`) и в `config.PROVIDER`.

**Новая панель в окне** (модуль мозга): методы в `app.Api`, панель в `ui/chloe-mind.html`
по образцу «Журнала» и «Памяти»: смотреть, искать, изменять или удалять.

## Данные пользователя

Всё в `~/.chloe/`, в проекте данных нет:
`brain.json` (мозг), `memory.json` (память), `chloe.db` (журнал), `screens/` (скриншоты, хранятся `CHLOE_KEEP_SCREENS` дней),
`backups/` (что Chloe заменила — для отмены), `voices/` (модели офлайн-голоса Piper, ставятся командой `python run.py --install-voice`).

## Тесты

```
.venv/bin/python -m unittest discover -s tests -t .
```

`tests/__init__.py` подменяет домашнюю папку на временную **до** импорта `chloe`, поэтому настоящие `~/.chloe`
не трогаются. `chloe/__init__.py` не пускает поиск тестов внутрь пакета: иначе пакет загрузился бы
с настоящей папкой раньше этой подмены.
