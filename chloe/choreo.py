"""Постановщик драк: сценарист пишет хореографию по тактам — движок сам расставляет время, дистанцию и ответы.

Формат (в описании сцены мультфильма):
  "fight": {"from": 0.1, "to": 0.9, "tempo": "fast" | "normal" | "slow",
            "beats": [{"who": "hero", "move": "punch", "answer": "guard", "power": "light"},
                      {"who": "rival", "move": "kick", "answer": "duck"},
                      {"who": "hero", "move": "jumpkick", "answer": "hit", "power": "heavy"},
                      {"who": "rival", "move": "taunt"}]}
who — кто действует в такте (второй участник — противник); move — удар (punch, kick, jumpkick, spinkick, fight) или
не удар (taunt — дразнит, guard — встаёт в защиту, backflip, cartwheel, roll… — просто движение);
answer — как отвечает противник: hit (пропускает удар), guard (блок), duck, slide, roll, diveroll, backflip, jump (уклоны);
power — light (вздрогнул) или heavy (отлетел; по умолчанию heavy — последний удар, остальные light).

Что делает движок: каждому удару — его настоящая длительность из записи движения (с темпом), уклон или блок
начинается чуть раньше удара и накрывает его момент; следующий такт — когда оба закончили; нападающий сам подходит
на длину удара (animator._reach). Всё не уместившееся в отрезок сцены сжимается темпом, а что не влезло и тогда — не играется.
"""
STRIKES = ("punch", "kick", "jumpkick", "spinkick", "fight")
ANSWERS = ("hit", "guard", "duck", "slide", "roll", "diveroll", "backflip", "jump", "sideflip", "cartwheel")
TEMPO = {"fast": 1.3, "normal": 1.0, "slow": 0.8}
LEAD = {"guard": 0.4, "duck": 0.3, "slide": 0.45, "roll": 0.45, "diveroll": 0.5, "backflip": 0.55, "jump": 0.3,
        "sideflip": 0.5, "cartwheel": 0.5}                     # за сколько секунд до удара начинать ответ
GAP = 0.18                                                     # пауза между тактами
NON_STRIKE = {"taunt": ("angry", 0.9), "wait": ("stand", 0.6), "cheer": ("cheer", 1.0), "shrug": ("shrug", 0.9)}


def _len(move, tempo):
    """Сколько секунд займёт движение при таком темпе (по записи; удары формулой — по их циклу)."""
    from . import animator as A
    from . import mocap as MC

    if move in MC.library():
        return max(0.4, MC.duration(move) / tempo)
    if move in NON_STRIKE:
        return NON_STRIKE[move][1] / tempo
    if move == "fight":
        return 1.0 / tempo
    if move in A.POSES:
        return 0.8 / tempo
    return 0.8 / tempo


def _hit_at(move, dur):
    """Через сколько секунд от начала движения удар попадает."""
    from . import animator as A
    from . import mocap as MC

    if move in MC.library() and MC.library()[move]["hits"]:
        h = MC.hits_in(move, dur)
        return h[0] if h else dur * 0.5
    if move in A.STRIKE:
        rate, peak = A.STRIKE[move]
        return peak / rate
    return None


def expand(fight, ids, secs):
    """Хореография → отрезки acting (доли сцены). ids — герои сцены по порядку (первые два — бойцы по умолчанию)."""
    from . import animator as A

    beats = fight.get("beats") or []
    if len(ids) < 2 or not beats:
        return []
    a = fight.get("a") if fight.get("a") in ids else ids[0]
    b = fight.get("b") if fight.get("b") in ids and fight.get("b") != a else next(i for i in ids if i != a)
    t0 = max(0.0, float(fight.get("from", 0.05))) * secs
    t1 = min(1.0, float(fight.get("to", 0.95))) * secs
    tempo = TEMPO.get(fight.get("tempo"), 1.0)

    def norm(word, allowed=None):
        w = str(word or "").lower().strip()
        w = w if w in A.ACTIONS or w in NON_STRIKE or w == "hit" else A.SYNONYMS.get(w, w)
        return w if (allowed is None or w in allowed) else None

    for squeeze in (1.0, 1.25, 1.55):                             # не влезает — быстрее; не влезло и так — обрезать
        out, t, ok = [], t0, True
        strikes = [i for i, bt in enumerate(beats) if norm(bt.get("move")) in STRIKES]
        for i, bt in enumerate(beats):
            who = bt.get("who") if bt.get("who") in (a, b) else (a if i % 2 == 0 else b)
            foe = b if who == a else a
            move = norm(bt.get("move")) or "taunt"
            sp = tempo * squeeze
            dur = _len(move, sp)
            if t + dur > t1 + 1e-6:
                ok = False
                break
            seg = {"who": who, "do": move if move not in NON_STRIKE else NON_STRIKE[move][0], "from": t, "to": t + dur}
            end = t + dur
            if move in STRIKES:
                seg["target"] = foe
                heavy = bt.get("power") == "heavy" or (bt.get("power") is None and i == strikes[-1])
                seg["power"] = "heavy" if heavy else "light"
                answer = norm(bt.get("answer"), ANSWERS) or "hit"
                hit = t + (_hit_at(move, dur) or dur * 0.5)
                if answer != "hit":
                    lead = LEAD.get(answer, 0.35) / max(0.8, sp)
                    a_dur = max(_len(answer, sp * 1.2) if answer != "guard" else 0.0, lead + 0.35)
                    a0 = max(t - 0.05, hit - lead)
                    out.append({"who": foe, "do": answer, "from": a0, "to": a0 + a_dur, "_answer": True})
                    end = max(end, a0 + a_dur)
            out.append(seg)
            t = end + GAP / sp
        if ok or squeeze == 1.55:
            break
    for s in out:                                                  # секунды → доли сцены
        s["from"], s["to"] = round(s["from"] / secs, 4), round(min(s["to"], secs) / secs, 4)
    return out
