// Телефон-пульт: эта же страница мозга, но связь с Chloe — через сеть, а не через окно программы.
// Работает только с ?remote=1 (так открывает сервер телефона, см. chloe/remote.py); на компьютере ничего не делает.
(function () {
  var params = new URLSearchParams(location.search);
  if (!params.has("remote")) return;
  var KEY = "chloe-phone-key", SPEAK = "chloe-phone-speak", key = null;
  var m = location.hash.match(/key=([\w-]+)/);
  try { if (m) localStorage.setItem(KEY, m[1]); key = localStorage.getItem(KEY); } catch (e) { key = m ? m[1] : null; }
  if (m) history.replaceState(null, "", location.pathname + location.search);   // код не остаётся в адресной строке
  // пульт уже открыт, а код отсканировали заново — браузер не перезагружает страницу из-за одной части после #
  window.addEventListener("hashchange", function () {
    var k = location.hash.match(/key=([\w-]+)/);
    if (!k) return;
    try { localStorage.setItem(KEY, k[1]); } catch (e) {}
    location.replace(location.pathname + location.search);
  });
  document.documentElement.classList.add("phone");

  function call(name, args) {
    return fetch("/api/" + name, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Chloe-Key": key || "" },
      body: JSON.stringify({ args: args || [] })
    }).then(function (r) {
      if (r.status === 401) { needKey(); throw new Error("нужен код"); }
      return r.json();
    }).then(function (d) {
      if (d && d.error && typeof d.error === "string") throw new Error(d.error);
      return d;
    });
  }
  // страница зовёт window.pywebview.api.<метод>() — как в программе на компьютере
  window.pywebview = { api: new Proxy({}, { get: function (_, name) {
    if (name === "then") return undefined;
    return function () { return call(name, Array.prototype.slice.call(arguments)); };
  } }) };

  // ---------- события Chloe → мозг на телефоне ----------
  var after = -1, online = null;
  function setOnline(on) {
    if (online === on) return;
    online = on;
    var dot = document.getElementById("phoneDot");
    if (dot) { dot.style.background = on ? "#CACACA" : "#E05555"; dot.title = on ? "Связь с компьютером есть" : "Нет связи с компьютером"; }
  }
  function poll() {
    fetch("/api/events?after=" + after, { headers: { "X-Chloe-Key": key || "" }, cache: "no-store" }).then(function (r) {
      if (r.status === 401) { needKey(); return null; }
      return r.json();
    }).then(function (d) {
      if (!d) return;
      setOnline(true);
      if (d.reset) { location.reload(); return; }
      after = d.next;
      (d.events || []).forEach(function (e) {
        var f = window[e[0]];
        if (typeof f === "function") { try { f.apply(null, e[1] || []); } catch (x) {} }
      });
      setTimeout(poll, 30);
    }).catch(function () { setOnline(false); setTimeout(poll, 2500); });
  }

  // ---------- голос: ответ Chloe звучит на телефоне ----------
  var speakOn = true;
  try { speakOn = localStorage.getItem(SPEAK) !== "0"; } catch (e) {}
  // Говорит Светлана — тот же голос, что на компьютере: компьютер озвучивает (api tts), телефон проигрывает.
  // Длинный ответ — частями по предложениям, следующая часть готовится, пока звучит текущая.
  // Голос браузера — только если компьютер не смог озвучить (нет интернета).
  var player = new Audio(), speakGen = 0;
  function pieces(text, size) {
    size = size || 300;
    var out = [], cur = "";
    String(text).trim().split(/(?<=[.!?…])\s+|\n+/).forEach(function (s) {
      s = s.trim();
      while (s.length > size) {
        var cut = Math.max(s.lastIndexOf(", ", size), s.lastIndexOf(" ", size));
        cut = cut > size / 2 ? cut + 1 : size;
        if (cur) { out.push(cur); cur = ""; }
        out.push(s.slice(0, cut).trim()); s = s.slice(cut).trim();
      }
      if (!s) return;
      if (cur && cur.length + 1 + s.length > size) { out.push(cur); cur = s; } else cur = (cur + " " + s).trim();
    });
    if (cur) out.push(cur);
    return out;
  }
  function browserSay(text) {
    if (!window.speechSynthesis) return;
    var u = new SpeechSynthesisUtterance(text);
    u.lang = "ru-RU";
    speechSynthesis.speak(u);
  }
  function stopSpeech() {
    speakGen++;
    try { player.pause(); } catch (e) {}
    if (window.speechSynthesis) speechSynthesis.cancel();
  }
  function say(text) {
    if (!speakOn || !text) return;
    stopSpeech();
    var gen = speakGen, parts = pieces(text), jobs = [];
    function fetchPart(i) { if (i < parts.length && !jobs[i]) jobs[i] = call("tts", [parts[i]]); }
    function play(i) {
      if (gen !== speakGen || i >= parts.length) return;
      fetchPart(i); fetchPart(i + 1);
      jobs[i].then(function (d) {
        if (gen !== speakGen) return;
        player.src = "data:audio/mpeg;base64," + d.audio;
        player.onended = function () { play(i + 1); };
        return player.play();
      }).catch(function () {
        if (gen === speakGen) browserSay(parts.slice(i).join(" "));
      });
    }
    play(0);
  }
  // браузер телефона разрешает звук только после касания — «разблокируем» плеер первым касанием
  document.addEventListener("pointerdown", function unlock() {
    player.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
    player.play().catch(function () {});
    document.removeEventListener("pointerdown", unlock);
  });

  // ---------- микрофон: сказанное уходит Chloe как команда ----------
  var Rec = window.SpeechRecognition || window.webkitSpeechRecognition, rec = null, listening = false;
  function send(text) {
    text = String(text || "").trim();
    if (!text) return;
    if (window.chloeHeard) window.chloeHeard(text);
    call("command", [text]).catch(function (e) { if (window.chloeReply) window.chloeReply("Не дошло до компьютера: " + e.message); });
  }
  function mic() {
    var btn = document.getElementById("phoneMic"), input = document.getElementById("phoneText");
    stopSpeech();   // заговорили — Chloe на телефоне замолкает
    if (!Rec) { input.focus(); input.placeholder = "Микрофон браузера недоступен — используйте микрофон на клавиатуре"; return; }
    if (listening && rec) { rec.stop(); return; }
    rec = new Rec();
    rec.lang = "ru-RU"; rec.interimResults = true; rec.maxAlternatives = 1;
    rec.onstart = function () { listening = true; btn.classList.add("on"); input.value = ""; input.placeholder = "Слушаю…"; };
    rec.onresult = function (ev) {
      var text = "", final = false;
      for (var i = ev.resultIndex; i < ev.results.length; i++) { text += ev.results[i][0].transcript; final = final || ev.results[i].isFinal; }
      input.value = text;
      if (final) { send(text); input.value = ""; }
    };
    rec.onerror = function (ev) {
      input.placeholder = ev.error === "not-allowed" ? "Разрешите микрофон для этого сайта в настройках браузера" : "Не расслышала — ещё раз";
    };
    rec.onend = function () { listening = false; btn.classList.remove("on"); if (input.placeholder === "Слушаю…") input.placeholder = "Напишите Хлое…"; };
    try { rec.start(); } catch (e) {}
  }

  function needKey() {
    if (document.getElementById("phoneKey")) return;
    var d = document.createElement("div");
    d.id = "phoneKey";
    d.innerHTML = "<b>Нужен код</b>На компьютере в окне Хлои нажмите «Все функции» → «Телефон» и отсканируйте QR-код этим телефоном.";
    document.body.appendChild(d);
  }

  var css = document.createElement("style");
  css.textContent = [
    // мобильная версия: стиль Channel Studio — чёрный, тонкие линии, один коралловый цвет
    "html.phone #cmd { display: none; }",
    "#phoneBar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 6; display: flex; gap: 14px; align-items: center;",
    "  padding: 10px 20px calc(12px + env(safe-area-inset-bottom, 0px)); background: #0A0A0A; border-top: 1px solid #2A2A2A; }",
    "#phoneBar input { flex: 1; min-width: 0; font-size: 16px; padding: 12px 0; }",
    "#phoneBar button { flex: none; width: 44px; height: 44px; border-radius: 50%; border: 0; background: transparent;",
    "  color: #CACACA; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0; }",
    "#phoneBar svg { width: 22px; height: 22px; }",
    "#phoneMic { width: 56px !important; height: 56px !important; border: 1px solid #FF7777 !important; color: #FF7777 !important; }",
    "#phoneMic.on { background: #FF7777 !important; color: #0A0A0A !important; animation: phonePulse 1.2s infinite; }",
    "@keyframes phonePulse { 50% { box-shadow: 0 0 0 10px rgba(255, 119, 119, .18); } }",
    "#phoneSpeak.off { color: #5a5a5a; }",
    "#phoneSpeak.off .wave { display: none; }",
    "#phoneDot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #5a5a5a; flex: none; }",
    "#phoneKey { position: fixed; left: 20px; right: 20px; top: 28%; z-index: 20; background: #0A0A0A; border: 1px solid #2A2A2A;",
    "  border-top: 2px solid #FF7777; padding: 24px 22px; color: #CACACA; font-size: 16px; line-height: 1.5; }",
    "#phoneKey b { display: block; color: #F2F2F2; font-weight: 400; font-size: 30px; letter-spacing: -.04em; line-height: 1; margin-bottom: 12px; }",
    "html.phone #moreBtn { font-size: 13px; }",
    "body.wall #phoneBar { display: none; }",
    "html.phone .panel { bottom: calc(80px + env(safe-area-inset-bottom, 0px)); }"
  ].join("\n");
  document.head.appendChild(css);

  window.addEventListener("load", function () {
    var bar = document.createElement("div");
    bar.id = "phoneBar";
    bar.innerHTML = "<i id='phoneDot'></i><input id='phoneText' placeholder='Напишите Хлое…' autocomplete='off' enterkeyhint='send'>" +
      "<button id='phoneSpeak' title='Озвучивать ответы на телефоне' aria-label='Озвучивать ответы'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M4 10v4h4l5 4V6L8 10z'/><path class='wave' d='M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11'/></svg></button><button id='phoneMic' title='Сказать' aria-label='Сказать'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' aria-hidden='true'><rect x='9' y='3' width='6' height='11' rx='3'/><path d='M5 11a7 7 0 0 0 14 0M12 18v3'/></svg></button>";
    document.body.appendChild(bar);
    var input = document.getElementById("phoneText"), speakBtn = document.getElementById("phoneSpeak");
    input.addEventListener("keydown", function (e) { e.stopPropagation(); if (e.key === "Enter") { send(input.value); input.value = ""; } });
    document.getElementById("phoneMic").onclick = mic;
    speakBtn.classList.toggle("off", !speakOn);
    speakBtn.onclick = function () {
      speakOn = !speakOn;
      try { localStorage.setItem(SPEAK, speakOn ? "1" : "0"); } catch (e) {}
      speakBtn.classList.toggle("off", !speakOn);
      if (!speakOn) stopSpeech();
    };
    var reply = window.chloeReply;   // ответ Chloe — ещё и голосом телефона
    // голосом телефона — только ответы на просьбы с телефона; просьбы с компьютера озвучивает компьютер
    window.chloeReply = function (text, where) { if (reply) reply(text); if (where === "phone") say(text); };
    if (!key) needKey();
    window.dispatchEvent(new Event("pywebviewready"));
    poll();
  });
})();
