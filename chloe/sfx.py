"""Звуки для мультиков, сделанные кодом: без записей, без интернета, без чужих файлов.

Методика — по мотивам earshot (github.com/Leonxlnx/earshot, MIT), код свой, только numpy:
- хороший звук — несколько слоёв, у каждого своя полоса и своя работа: щелчок (момент удара), тело (вес), низ (мощь);
- у всего, что движется, звук тоже движется: полоса шума плывёт, громкость растёт к самому быстрому моменту;
- громче всего — точно на кадре действия: можно на кадр раньше, нельзя на два позже (ITU-R BT.1359: заметно
  45 мс раньше и 125 мс позже);
- повторяющийся звук (шаги, удары) каждый раз чуть другой: высота ±, громкость ±, свежий шум;
- звуки — акценты под голосом, а не поверх него: тише голоса на 10–15 дБ, удары — громче всех остальных.

Сцена мультфильма отдаёт список событий (что, когда, где по горизонтали) — здесь из них собирается дорожка.
check() — проверка любого звука без моделей (щелчки на краях, перегруз, тишина), listen() — «слух» Хлои
на готовом ролике: где громко, где тихо, где пропал звук, совпадают ли звуки с событиями.
"""
import math
import wave

import numpy as np

SR = 44100
LEAD = 0.010          # с: звук чуть раньше кадра — так он читается «вовремя»


# --- основа ---
def _rng(seed):
    return np.random.default_rng(int(seed) & 0xFFFFFFFF)


def pink(n, rng):
    """Розовый шум (мягче белого): белый шум со спадом 3 дБ на октаву через спектр."""
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = f[1] if n > 1 else 1
    spec /= np.sqrt(f)
    out = np.fft.irfft(spec, n)
    return out / (np.max(np.abs(out)) + 1e-9)


def band(x, lo, hi, soft=0.25):
    """Полосовой фильтр через спектр с мягкими краями (без звона)."""
    n = len(x)
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    lo, hi = max(1.0, lo), min(SR / 2 - 1, hi)
    up = 1 / (1 + np.exp(-(np.log(f + 1) - math.log(lo)) / soft))
    down = 1 / (1 + np.exp((np.log(f + 1) - math.log(hi)) / soft))
    return np.fft.irfft(spec * up * down, n)


def sweep_band(x, centers, q=1.6, block=1024):
    """Полоса, которая плывёт во времени (свист движения): центр полосы — по centers (Гц на каждый сэмпл)."""
    n = len(x)
    hop = block // 2
    win = np.hanning(block)
    out = np.zeros(n + block)
    pad = np.concatenate([x, np.zeros(block)])
    f = np.fft.rfftfreq(block, 1 / SR)
    for start in range(0, n, hop):
        seg = pad[start:start + block] * win
        c = centers[min(n - 1, start + hop)]
        lo, hi = c / (1 + 1 / q), c * (1 + 1 / q)
        mask = np.exp(-0.5 * ((np.log(f + 1) - math.log(c)) / (math.log(hi / lo) / 2.3)) ** 2)
        out[start:start + block] += np.fft.irfft(np.fft.rfft(seg) * mask, block) * win
    return out[:n]


def env_adsr(n, attack, decay_tau, power=1.0):
    """Быстрая атака и экспоненциальный спад (время — в секундах)."""
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1) ** 2
    d = np.exp(-np.maximum(0, t - attack) / max(decay_tau, 1e-4))
    return (a * d) ** power


def tone(n, f0, f1=None, tau=0.05):
    """Синус, высота которого падает от f0 к f1 (барабан, удар, «бум»)."""
    t = np.arange(n) / SR
    f = f0 if f1 is None else f1 + (f0 - f1) * np.exp(-t / tau)
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def saturate(x, drive=2.0):
    """Мягкий перегруз — обертоны, чтобы низ было слышно и в маленьких динамиках."""
    return np.tanh(x * drive) / math.tanh(drive)


def finish(x, peak=0.9, fade_in=0.0015, fade_out=0.008):
    """Без щелчков на краях, без постоянной составляющей, пик — заданный."""
    x = x - np.mean(x)
    n = len(x)
    a, b = int(fade_in * SR), int(fade_out * SR)
    if a:
        x[:a] *= np.linspace(0, 1, a)
    if b and b < n:
        x[-b:] *= np.linspace(1, 0, b) ** 2
    m = np.max(np.abs(x)) + 1e-9
    return x * (peak / m)


def _n(sec):
    return max(16, int(sec * SR))


# --- звуки (каждый возвращает (сигнал, где пик в секундах)) ---
def whoosh(dur=0.45, peak_at=0.6, lo=350, hi=3200, seed=0, heavy=False):
    """Свист движения: шум в полосе, которая взлетает к пику и опускается; громкость растёт как скорость в кубе."""
    rng = _rng(seed)
    n = _n(dur)
    t = np.linspace(0, 1, n)
    speed = np.where(t < peak_at, (t / peak_at) ** 2.5, np.exp(-(t - peak_at) / max(1e-3, (1 - peak_at) * 0.45)))
    centers = lo + (hi - lo) * speed ** 0.7
    x = sweep_band(pink(n, rng), centers, q=1.4)
    x += 0.5 * sweep_band(pink(n, rng), centers * 1.6, q=2.2)
    if heavy:
        x += 0.35 * tone(n, 70, 55, 0.3) * speed
    return finish(x * speed ** 1.2, 0.8), peak_at * dur


def swish(dur=0.16, seed=0):
    """Тонкий быстрый взмах (бросок, удар мимо): ярче и короче."""
    return whoosh(dur, 0.55, 1200, 7000, seed)


def punch(seed=0, size=1.0):
    """Удар: щелчок (момент), тело (вес, 150→60 Гц), низ; лёгкий перегруз."""
    rng = _rng(seed)
    p = 2 ** (rng.uniform(-0.6, 0.6) / 12) / size
    n = _n(0.32)
    crack = band(rng.standard_normal(n), 1800, 9000) * env_adsr(n, 0.0008, 0.006, 3)
    body = tone(n, 160 * p, 58 * p, 0.045) * env_adsr(n, 0.002, 0.09)
    sub = tone(n, 75 * p, 45 * p, 0.12) * env_adsr(n, 0.004, 0.14) * 0.5
    slap = band(rng.standard_normal(n), 500, 2500) * env_adsr(n, 0.001, 0.025) * 0.5
    return finish(saturate(crack * 0.9 + body + sub + slap, 2.5), 0.95), 0.002


def thud(seed=0, size=1.0):
    """Падение на землю: глухой удар с пыльным шорохом."""
    rng = _rng(seed)
    n = _n(0.5)
    body = tone(n, 110 / size, 42 / size, 0.06) * env_adsr(n, 0.003, 0.12)
    dirt = band(rng.standard_normal(n), 250, 1800) * env_adsr(n, 0.004, 0.09) * 0.6
    grit = band(rng.standard_normal(n), 1500, 6000) * env_adsr(n, 0.02, 0.15) * 0.15
    return finish(saturate(body + dirt + grit, 1.8), 0.9), 0.004


def step(seed=0, weight=1.0):
    """Шаг: короткий мягкий стук пятки и шорох. Каждый — чуть другой."""
    rng = _rng(seed)
    p = 2 ** (rng.uniform(-1.0, 1.0) / 12)
    n = _n(0.09)
    heel = tone(n, 140 * p, 90 * p, 0.02) * env_adsr(n, 0.001, 0.018)
    scuff = band(rng.standard_normal(n), 700 * p, 4000) * env_adsr(n, 0.002, 0.012) * 0.7
    return finish(heel * weight + scuff, 0.6 + 0.2 * rng.random()), 0.002


def tap(seed=0, pitch=900):
    """Лёгкий стук (ладонь о ступеньку, поймал предмет)."""
    rng = _rng(seed)
    n = _n(0.12)
    x = tone(n, pitch, pitch * 0.8, 0.02) * env_adsr(n, 0.0008, 0.03) + \
        band(rng.standard_normal(n), 1500, 6000) * env_adsr(n, 0.0005, 0.004) * 0.6
    return finish(x, 0.7), 0.001


def pop(seed=0, f0=520):
    """Круглый «поп»: предмет оказался в руке, мысль появилась."""
    rng = _rng(seed)
    p = 2 ** (rng.uniform(-0.5, 0.5) / 12)
    n = _n(0.16)
    x = tone(n, f0 * p * 0.7, f0 * p, 0.015) * env_adsr(n, 0.004, 0.04)
    x += 0.25 * tone(n, f0 * p * 2, f0 * p * 2, 1) * env_adsr(n, 0.002, 0.02)
    return finish(x, 0.75), 0.006


def ding(seed=0, f0=1320):
    """Колокольчик-идея: неровные обертоны, как у металла, затухают по-разному."""
    n = _n(0.9)
    x = np.zeros(n)
    for ratio, amp, tau in ((1.0, 1.0, 0.45), (2.76, 0.45, 0.22), (5.4, 0.22, 0.1), (8.93, 0.1, 0.05)):
        x += amp * tone(n, f0 * ratio) * env_adsr(n, 0.001, tau)
    return finish(x, 0.6), 0.002


def sparkle(seed=0):
    """Искры радости: россыпь высоких колокольчиков."""
    rng = _rng(seed)
    n = _n(0.9)
    x = np.zeros(n)
    for i in range(6):
        at = int(rng.uniform(0, 0.35) * SR)
        f = rng.choice([1760, 2093, 2349, 2637, 3136])
        m = n - at
        x[at:] += (0.5 + 0.5 * rng.random()) * tone(m, f) * env_adsr(m, 0.001, 0.12)
    return finish(x, 0.45), 0.002


def boop(seed=0):
    """Мягкое «буп» (сердечко, вопрос, удивление): нота с лёгким спадом высоты."""
    n = _n(0.25)
    x = tone(n, 740, 620, 0.08) * env_adsr(n, 0.006, 0.07)
    return finish(x, 0.5), 0.008


def stinger(seed=0):
    """Резкий акцент «шок»: короткий диссонанс с ударом."""
    n = _n(0.4)
    x = 0.6 * tone(n, 466) + 0.6 * tone(n, 494) + 0.4 * tone(n, 988)
    x = saturate(x * env_adsr(n, 0.002, 0.12), 2.0)
    hit, _ = punch(seed, 1.3)
    m = min(len(hit), n)
    x[:m] += 0.5 * hit[:m]
    return finish(x, 0.7), 0.003


def flutter(seed=0):
    """Возня, шорох (ползёт, лезет): мягкий короткий шорох ткани."""
    rng = _rng(seed)
    n = _n(0.14)
    x = band(rng.standard_normal(n), 900, 5000) * env_adsr(n, 0.012, 0.035)
    return finish(x, 0.35), 0.012


def click(seed=0):
    """Щелчок мыши: два очень коротких сухих тика (нажал — отпустил)."""
    rng = _rng(seed)
    n = _n(0.07)
    x = np.zeros(n)
    for at, amp in ((0, 1.0), (rng.uniform(0.035, 0.05), 0.55)):
        m = n - int(at * SR)
        x[int(at * SR):] += amp * (band(rng.standard_normal(m), 2500, 9000) * env_adsr(m, 0.0003, 0.0025) +
                                   0.5 * tone(m, 2200, 1800, 0.004) * env_adsr(m, 0.0003, 0.004))
    return finish(x, 0.7, 0.0005, 0.005), 0.001


def shatter(seed=0):
    """Разбитое стекло: удар-щелчок, шипящий звон осколков и россыпь высоких «динь», падающих по одному."""
    rng = _rng(seed)
    n = _n(1.1)
    crack = band(rng.standard_normal(n), 2500, 12000) * env_adsr(n, 0.0005, 0.03)
    hiss = band(rng.standard_normal(n), 4000, 11000) * env_adsr(n, 0.002, 0.18) * 0.35
    body = tone(n, 180, 90, 0.03) * env_adsr(n, 0.001, 0.05) * 0.5
    x = crack + hiss + body
    for _ in range(14):
        at = int(rng.uniform(0.01, 0.75) ** 1.6 * SR)
        m = n - at
        f = rng.uniform(3200, 8200)
        x[at:] += rng.uniform(0.15, 0.4) * tone(m, f) * env_adsr(m, 0.0005, rng.uniform(0.02, 0.09))
    return finish(saturate(x, 1.5), 0.95), 0.002


def scribble(dur=1.2, seed=0):
    """Маркер по бумаге: шуршащий шум 2–7 кГц, штрихами (5–8 в секунду, каждый чуть другой), с паузами на отрыв руки."""
    rng = _rng(seed)
    n = _n(dur)
    x = band(rng.standard_normal(n), 1800, 7000, 0.3)
    env = np.zeros(n)
    t = 0.0
    while t < dur:
        ln = rng.uniform(0.08, 0.2)
        a, b = int(t * SR), min(n, int((t + ln) * SR))
        if b > a:
            seg = np.sin(np.linspace(0, np.pi, b - a)) ** 0.6 * rng.uniform(0.55, 1.0)
            env[a:b] = np.maximum(env[a:b], seg)
        t += ln + rng.uniform(0.0, 0.06)
    return finish(x * env, 0.5, 0.004, 0.03), 0.0


def room_tone(secs, seed=0, level_db=-52.0):
    """Фон комнаты: еле слышный мягкий шум. Без него пауза между сценами — «мёртвая» цифровая тишина, будто звук пропал."""
    n = _n(secs)
    rng = _rng(seed)
    x = band(pink(n, rng), 60, 1800, 0.4)
    x = x / (np.sqrt(np.mean(x ** 2)) + 1e-9) * 10 ** (level_db / 20)
    fade = min(n // 3, int(0.3 * SR))
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return np.stack([x, np.roll(x, 37)], axis=1)          # чуть разные каналы — фон «шире»


RECIPES = {"whoosh": whoosh, "swish": swish, "punch": punch, "thud": thud, "step": step, "tap": tap, "pop": pop,
           "ding": ding, "sparkle": sparkle, "boop": boop, "stinger": stinger, "flutter": flutter,
           "scribble": scribble, "click": click, "shatter": shatter}
# громкость каждого рода звуков относительно голоса (дБ): удары громче всех, шаги и шорохи — тихо
LEVEL_DB = {"punch": -9, "thud": -10, "stinger": -11, "whoosh": -16, "swish": -15, "step": -22, "tap": -18, "pop": -16,
            "ding": -14, "sparkle": -17, "boop": -17, "flutter": -24,
            "scribble": -24, "click": -17, "shatter": -9}


def make(kind, seed=0, **kw):
    fn = RECIPES[kind]
    try:
        return fn(seed=seed, **kw)
    except TypeError:
        return fn(seed=seed)


# --- дорожка сцены ---
def render(events, secs, voice_peak_db=-3.0, room=True, stop=None):
    """События [{t, kind, pan (-1..1), gain_db?, seed?, args?}] → стерео-дорожка звуков на secs секунд.
    Пик каждого звука ставится в момент события (чуть раньше — на LEAD). room — подложить фон комнаты.
    stop=(a, b) — тишина перед большим моментом: фон уходит почти в ноль (но не в цифровой ноль) и возвращается с ударом."""
    n = _n(secs)
    out = room_tone(secs, int(secs * 1000)) if room else np.zeros((n, 2))
    if stop and room:
        t = np.arange(n) / SR
        a, b = stop
        dip = np.clip((t - a) / 0.15, 0, 1) * np.clip((b + 0.05 - t) / 0.05, 0, 1)
        out *= (1 - 0.85 * dip)[:, None]
    placed = []
    for i, e in enumerate(sorted(events, key=lambda e: e["t"])):
        kind = e["kind"]
        if kind not in RECIPES:
            continue
        x, peak = make(kind, e.get("seed", i * 7919 + 13), **(e.get("args") or {}))
        start = int(round((e["t"] - peak - LEAD) * SR))
        if start >= n:
            continue
        gain = 10 ** ((LEVEL_DB.get(kind, -16) + e.get("gain_db", 0) + voice_peak_db) / 20)
        pan = max(-1.0, min(1.0, float(e.get("pan", 0.0)))) * 0.6          # не крайние стороны: на телефоне всё равно моно
        l, r = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
        a, b = max(0, start), min(n, start + len(x))
        seg = x[a - start:b - start] * gain
        out[a:b, 0] += seg * l * math.sqrt(2)
        out[a:b, 1] += seg * r * math.sqrt(2)
        placed.append({"t": e["t"], "kind": kind, "at": (start + int(peak * SR)) / SR})
    edge = min(n // 4, int(0.012 * SR))                                  # звук, обрезанный концом сцены, не щёлкает
    if edge:
        out[:edge] *= np.linspace(0, 1, edge)[:, None]
        out[-edge:] *= np.linspace(1, 0, edge)[:, None] ** 2
    m = np.max(np.abs(out)) if out.size else 0
    if m > 0.98:                                                           # мягкий предел вместо перегруза
        out = np.tanh(out / m * 1.2) * 0.95
    return out, placed


def save_wav(path, data):
    data = np.asarray(data)
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


def load_wav(path):
    with wave.open(str(path), "rb") as w:
        ch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


# --- проверка звука без моделей ---
def check(x, sr=SR):
    """Проблемы одного звука (не смеси: там удар посреди другого звука законно похож на щелчок): щелчок на краях, перегруз, постоянная составляющая, тишина. [] — чисто."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    problems = []
    peak = np.max(np.abs(x)) if len(x) else 0.0
    if peak < 10 ** (-60 / 20):
        return ["silent: звука нет"]
    if abs(x[0]) > peak * 0.05 or abs(x[-1]) > peak * 0.05:
        problems.append("edge: начинается или кончается не с нуля — будет щелчок")
    if np.sum(np.abs(x) > 0.999) > 3:
        problems.append("clipping: перегруз — обрезанные пики")
    if abs(np.mean(x)) > peak * 0.01:
        problems.append("dc: постоянная составляющая")
    # щелчок — скачок намного больше соседних (по 3 мс в обе стороны): яркий шум и задуманный удар скачут
    # вровень с соседями (в 6–8 раз выше среднего), щелчок и обрыв — в 15 и больше
    jumps = np.abs(np.diff(x))
    if len(jumps) > 64:
        win = int(0.003 * sr)
        local = np.convolve(jumps, np.ones(2 * win + 1) / (2 * win + 1), mode="same")
        onset = int(0.005 * sr)                    # первые 5 мс — атака звука (её край проверяет «edge»)
        if np.any(((jumps > peak * 0.3) & (jumps > 15 * local))[onset:]):
            problems.append("clicks: резкий скачок внутри звука")
    return problems


def onsets(x, sr=SR, hop=0.005, min_gap=0.06, rise_db=9.0):
    """Моменты, где звук резко становится громче (удары, шаги) — в секундах."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    h = max(1, int(hop * sr))
    frames = len(x) // h
    if frames < 3:
        return []
    rms = np.sqrt(np.mean(x[:frames * h].reshape(frames, h) ** 2, axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    floor = np.max(db) - 30                           # тише — это хвосты и фон, а не удары
    out, last = [], -1e9
    for i in range(2, frames):
        if db[i] > floor and db[i] - min(db[i - 2], db[i - 1]) > rise_db and (i * hop - last) > min_gap:
            # пик удара — на самом громком кадре в ближайших 20 мс
            j = i + int(np.argmax(db[i:i + max(1, int(0.02 / hop))]))
            out.append(j * hop)
            last = i * hop
    return out


def sync_report(track, placed, sr=SR, early=0.045, late=0.06):
    """Совпадают ли звуки с событиями: для ударных звуков ищем ближайший всплеск громкости."""
    hits = onsets(track, sr)
    bad = []
    checked = 0
    for p in placed:
        if p["kind"] not in ("punch", "thud", "step", "tap", "pop", "stinger"):
            continue
        checked += 1
        near = min(hits, key=lambda h: abs(h - p["t"])) if hits else None
        if near is None or not (p["t"] - early <= near <= p["t"] + late):
            bad.append({"t": round(p["t"], 3), "kind": p["kind"], "heard": None if near is None else round(near, 3)})
    return {"checked": checked, "off": bad}


def listen(path, scenes=None):
    """«Слух» Хлои на готовом ролике (wav): громкость, пики, провалы тишины; scenes — длины сцен (с): сцена громче или тише
    средней больше чем на 3 дБ — замечание. Возвращает отчёт словами и цифрами."""
    x, sr = load_wav(path)
    if not len(x):
        return {"ok": False, "notes": ["звука нет"]}
    sec = len(x) / sr
    win = int(0.4 * sr)
    frames = max(1, len(x) // win)
    rms = np.sqrt(np.mean(x[:frames * win].reshape(frames, win) ** 2, axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    peak_db = 20 * math.log10(np.max(np.abs(x)) + 1e-9)
    loud = float(np.median(db))
    notes = []
    # пропал звук — цифровая тишина дольше 0,8 с (фон комнаты так тихо не бывает); долгая пауза — тихо дольше 2 с.
    # Хвост в самом конце ролика — не провал
    def runs(mask, need):
        found, run = [], 0
        for i in range(frames - 1):
            run = run + 1 if mask[i] else 0
            if run == need:
                found.append(round((i - need + 1) * 0.4, 1))
        return found

    dead = runs(db < -70, 2)
    long = runs(db < loud - 30, 5)
    if dead:
        notes.append("звук пропадает: {} раз (первый на {} с)".format(len(dead), dead[0]))
    if long:
        notes.append("долгие паузы без звука, дольше 2 с: {} (первая на {} с)".format(len(long), long[0]))
    if peak_db > -0.3:
        notes.append("пики почти на пределе ({:.1f} дБ) — возможен перегруз".format(peak_db))
    if loud < -30:
        notes.append("в целом тихо ({:.0f} дБ)".format(loud))
    if scenes and len(scenes) > 2:
        levels, at = [], 0.0
        for d in scenes:
            seg = x[int(at * sr):int((at + d) * sr)]
            at += d
            levels.append(20 * math.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9) if len(seg) else -120.0)
        mid = float(np.median(levels))
        odd = [(i + 1, round(lv - mid, 1)) for i, lv in enumerate(levels) if abs(lv - mid) > 3]
        if odd:
            notes.append("сцены громче или тише остальных: " + ", ".join("{} ({:+} дБ)".format(i, d) for i, d in odd))
    clip = int(np.sum(np.abs(x) > 0.999))
    if clip > 10:
        notes.append("перегруз: {} обрезанных сэмплов".format(clip))
    return {"ok": not notes, "seconds": round(sec, 1), "level_db": round(loud, 1), "peak_db": round(peak_db, 1), "notes": notes}
