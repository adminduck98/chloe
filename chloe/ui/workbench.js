// Мини-окна на главном экране: Терминал, Файлы, Проекты.
// Лежат поверх мозга, их можно двигать и менять размер; где стояли и открыты ли — помнится.
// Кнопки — в шапке рядом с «Chloe». Терминал: Ctrl+` (или Ctrl+Ё).
// Работают в программе Chloe (python run.py); на телефоне-пульте их нет — менять файлы и запускать команды с телефона нельзя.
(function () {
  if (document.documentElement.classList.contains("phone")) return;
  var params = new URLSearchParams(location.search);
  if (params.has("remote")) return;

  function api() { return window.pywebview && window.pywebview.api && window.pywebview.api.term_start ? window.pywebview.api : null; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem("chloe-wb-" + k) || "null"); localStorage.setItem("chloe-wb-" + k, JSON.stringify(v)); } catch (e) { return null; } }
  var NOAPP = "<div class='wbEmpty'>Работает в программе Chloe — запустите <code>python run.py</code>.</div>";

  // ---------------------------------------------------------------- стиль
  var css = document.createElement("style");
  css.textContent = [
    "#wbDock { display: flex; gap: 22px; margin: 0 auto 0 40px; }",
    "#wbDock button { background: transparent; border: 0; border-bottom: 1px solid transparent; color: var(--iron); font: 400 14px var(--font);",
    "  letter-spacing: -.01em; padding: 6px 0; min-height: 36px; cursor: pointer; transition: color .15s, border-color .15s; }",
    "#wbDock button:hover { color: var(--ink); }",
    "#wbDock button.on { color: var(--ink); border-bottom-color: var(--coral); }",
    "#wbDock button kbd { font: inherit; font-size: 11px; color: var(--iron); margin-left: 6px; opacity: .7; }",
    ".mini { position: absolute; z-index: 5; display: none; flex-direction: column; min-width: 280px; min-height: 160px;",
    "  background: rgba(12,12,12,.9); border: 1px solid var(--line); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);",
    "  box-shadow: 0 18px 60px rgba(0,0,0,.55); resize: both; overflow: hidden; color: var(--bone); font-size: 13px; }",
    ".mini.open { display: flex; }",
    ".mini.front { z-index: 6; border-color: #3a3a3a; }",
    ".mini > .wbBar { flex: none; display: flex; align-items: center; gap: 12px; height: 36px; padding: 0 8px 0 14px; border-bottom: 1px solid var(--line);",
    "  cursor: move; user-select: none; touch-action: none; }",
    ".mini > .wbBar .wbTools { display: flex; flex: none; gap: 2px; }",
    ".mini > .wbBar .wbTtl { font-size: 10px; letter-spacing: .16em; text-transform: uppercase; color: var(--iron); white-space: nowrap; }",
    ".mini > .wbBar .wbSub { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--bone); font-size: 12px; }",
    ".mini > .wbBar button, .wbTool { background: transparent; border: 0; color: var(--iron); font: 400 12px var(--font); cursor: pointer;",
    "  padding: 4px 6px; white-space: nowrap; }",
    ".mini > .wbBar button:hover, .wbTool:hover { color: var(--ink); }",
    ".mini > .wbBar .x { font-size: 18px; line-height: 1; padding: 2px 6px; }",
    ".mini > .wbBar .x:hover { color: var(--coral); }",
    ".mini > .body { flex: 1; min-height: 0; display: flex; flex-direction: column; }",
    ".wbEmpty { padding: 18px 14px; color: var(--iron); line-height: 1.5; }",
    ".wbEmpty code { color: var(--ink); }",
    ".wbErr { color: var(--coral); }",
    // терминал
    "#wbTerm .body { font: 12.5px/1.5 'JetBrains Mono', 'Cascadia Mono', ui-monospace, Menlo, Consolas, monospace; }",
    "#wbOut { flex: 1; min-height: 0; margin: 0; padding: 10px 14px; overflow: auto; white-space: pre-wrap; word-break: break-word;",
    "  color: var(--bone); scrollbar-width: thin; scrollbar-color: var(--line) transparent; font: inherit; }",
    "#wbOut .cmd { color: var(--ink); }",
    "#wbOut .cmd i { color: var(--iron); font-style: normal; }",
    "#wbOut .meta { color: var(--iron); }",
    "#wbOut .bad { color: var(--coral); }",
    ".wbIn { flex: none; display: flex; align-items: center; gap: 8px; padding: 0 14px; border-top: 1px solid var(--line); }",
    ".wbIn .ps { color: var(--iron); white-space: nowrap; max-width: 45%; overflow: hidden; text-overflow: ellipsis; }",
    ".wbIn .ps b { color: var(--coral); font-weight: 400; }",
    ".wbIn input { flex: 1; min-width: 0; border: 0; padding: 10px 0; font: inherit; color: var(--ink); background: transparent; }",
    ".wbIn input:focus { border: 0; }",
    "#wbTerm.busy .wbIn .ps b { animation: wbBlink 1s steps(2) infinite; }",
    "@keyframes wbBlink { 50% { opacity: .2; } }",
    // файлы
    ".wbRow2 { flex: none; display: flex; flex-wrap: wrap; align-items: center; gap: 2px 14px; padding: 6px 14px; border-bottom: 1px solid var(--line); }",
    ".wbRow2 .pl { background: transparent; border: 0; border-bottom: 1px solid transparent; color: var(--iron); font: 400 12px var(--font); padding: 3px 0; cursor: pointer; }",
    ".wbRow2 .pl:hover { color: var(--ink); } .wbRow2 .pl.on { color: var(--ink); border-bottom-color: var(--coral); }",
    ".wbRow2 input { flex: 1; min-width: 90px; font-size: 12px; padding: 5px 0; }",
    "#wbList { flex: 1; min-height: 0; overflow: auto; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }",
    ".wbF { display: grid; grid-template-columns: 18px 1fr auto; align-items: center; gap: 10px; padding: 5px 14px; cursor: default; position: relative; }",
    ".wbF:hover, .wbF.sel { background: rgba(255,255,255,.035); }",
    ".wbF .ic { width: 12px; height: 10px; border: 1px solid var(--iron); border-radius: 1px; position: relative; justify-self: center; }",
    ".wbF.dir .ic { border-color: var(--bone); border-top-width: 3px; }",
    ".wbF.priv .ic { border-color: var(--coral); }",
    ".wbF .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--bone); }",
    ".wbF.dir .nm { color: var(--ink); cursor: pointer; }",
    ".wbF .mt { color: var(--iron); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }",
    ".wbF .acts { display: none; gap: 2px; }",
    ".wbF:hover .acts, .wbF.sel .acts { display: flex; } .wbF:hover .mt, .wbF.sel .mt { display: none; }",
    ".wbF .acts button { background: transparent; border: 0; color: var(--iron); font: 400 11px var(--font); padding: 2px 5px; cursor: pointer; }",
    ".wbF .acts button:hover { color: var(--ink); } .wbF .acts button.del:hover, .wbF .acts button.armed { color: var(--coral); }",
    ".wbF input { width: 100%; font-size: 13px; padding: 2px 0; }",
    ".wbFoot { flex: none; display: flex; justify-content: space-between; gap: 10px; padding: 6px 14px; border-top: 1px solid var(--line); color: var(--iron); font-size: 11px; }",
    // проекты
    "#wbProjList { flex: 1; min-height: 0; overflow: auto; padding: 4px 0 10px; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }",
    ".wbP { padding: 8px 14px; border-bottom: 1px solid #161616; }",
    ".wbP .hd { display: flex; align-items: baseline; gap: 10px; cursor: pointer; }",
    ".wbP .hd .n { flex: 1; color: var(--ink); font-size: 15px; letter-spacing: -.015em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
    ".wbP .hd .c { color: var(--iron); font-size: 11px; white-space: nowrap; font-variant-numeric: tabular-nums; }",
    ".wbP .hd .c b { color: var(--coral); font-weight: 400; }",
    ".wbP .hd:hover .n { color: var(--coral); }",
    ".wbP .hd .n::first-letter { text-transform: uppercase; }",
    ".wbP .bar2 { height: 2px; background: var(--line); margin-top: 6px; display: flex; }",
    ".wbP .bar2 i { display: block; height: 100%; } .wbP .bar2 i.dn { background: var(--bone); } .wbP .bar2 i.dg { background: var(--coral); }",
    ".wbT { display: grid; grid-template-columns: 22px 1fr; gap: 6px; align-items: baseline; padding: 4px 0; }",
    ".wbT button { background: transparent; border: 0; padding: 0; cursor: pointer; width: 22px; height: 18px; display: flex; align-items: center; }",
    ".wbT button i { display: block; width: 9px; height: 9px; border-radius: 50%; border: 1px solid var(--iron); box-sizing: border-box; }",
    ".wbT button:hover i { border-color: var(--coral); }",
    ".wbT.doing button i { border-color: var(--coral); background: linear-gradient(90deg, var(--coral) 50%, transparent 50%); }",
    ".wbT.done button i { border-color: var(--bone); background: var(--bone); }",
    ".wbT.doing .t { color: var(--ink); }",
    ".wbT.done .t { color: var(--iron); text-decoration: line-through; }",
    ".wbT .t { color: var(--bone); }",
    ".wbT .t i { font-style: normal; color: var(--coral); font-size: 11px; margin-left: 6px; }",
    ".wbP .tasks { margin-top: 8px; }",
    ".wbP .add { display: flex; gap: 10px; margin-top: 6px; } .wbP .add input { flex: 1; font-size: 13px; padding: 6px 0; }",
    ".wbP .more { margin-top: 6px; display: flex; justify-content: space-between; color: var(--iron); font-size: 11px; }",
    ".wbP .more span { cursor: pointer; } .wbP .more span:hover { color: var(--ink); }",
    // узкое окно: мини-окна — листами снизу, без перетаскивания
    "@media (max-width: 900px) {",
    // узкое окно (а окно Chloe по умолчанию 520 px): кнопки окон — второй строкой под шапкой, остальное — ниже на эту строку
    "  #wbDock { position: absolute; left: 0; right: 0; top: calc(56px + env(safe-area-inset-top, 0px)); height: 40px; margin: 0; padding: 0 20px;",
    "    gap: 18px; align-items: center; border-bottom: 1px solid var(--line); background: rgba(10,10,10,.82); backdrop-filter: blur(8px);",
    "    overflow-x: auto; scrollbar-width: none; z-index: 5; }",
    "  #wbDock::-webkit-scrollbar { display: none; } #wbDock button { flex: none; min-height: 32px; font-size: 13px; } #wbDock kbd { display: none; }",
    "  #moreBtn { white-space: nowrap; }",
    "  #stats { top: calc(112px + env(safe-area-inset-top, 0px)) !important; }",
    "  #filters { top: calc(134px + env(safe-area-inset-top, 0px)) !important; }",
    "  #search { top: calc(180px + env(safe-area-inset-top, 0px)) !important; }",
    "  #wbToast { top: 106px !important; }",
    "  .mini { left: 12px !important; right: 12px; top: auto !important; bottom: calc(var(--sa, 0px) + 140px) !important;",
    "    width: auto !important; height: 52vh !important; resize: none; }",
    "  .mini > .wbBar { cursor: default; }",
    "}",
    "body.wall #wbDock, body.wall .mini { display: none !important; }"
  ].join("\n");
  document.head.appendChild(css);

  // ---------------------------------------------------------------- окна
  var app = document.getElementById("app"), header = app.querySelector("header");
  var dock = document.createElement("nav");
  dock.id = "wbDock";
  header.insertBefore(dock, header.children[1]);
  var wins = {}, zTop = 0;

  function vw() { return app.clientWidth || innerWidth; }
  function vh() { return app.clientHeight || innerHeight; }
  function clampPos(w) {
    var el = w.el, W = el.offsetWidth, H = el.offsetHeight;
    var x = Math.min(Math.max(0, el.offsetLeft), Math.max(0, vw() - Math.min(W, 120)));
    var y = Math.min(Math.max(64, el.offsetTop), Math.max(64, vh() - 36));
    el.style.left = x + "px"; el.style.top = y + "px";
  }
  function save(w) {
    var el = w.el;
    store(w.id, { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight, open: el.classList.contains("open") });
  }
  function front(w) {
    Object.keys(wins).forEach(function (k) { wins[k].el.classList.remove("front"); });
    w.el.classList.add("front");
    w.el.style.zIndex = 5 + (++zTop % 50) / 100;
  }
  function setOpen(w, on) {
    w.el.classList.toggle("open", on);
    w.btn.classList.toggle("on", on);
    if (on) { clampPos(w); front(w); w.onOpen && w.onOpen(); }
    save(w);
  }

  function makeWin(id, title, label, def, keyHint) {
    var el = document.createElement("div");
    el.className = "mini"; el.id = id;
    el.innerHTML = "<div class='wbBar'><span class='wbTtl'>" + esc(title) + "</span><span class='wbSub'></span><span class='wbTools'></span>" +
      "<button class='x' title='Закрыть'>×</button></div><div class='body'></div>";
    app.appendChild(el);
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = label;
    btn.title = label + (keyHint ? " (" + keyHint + ")" : "");
    dock.appendChild(btn);
    var w = { id: id, el: el, btn: btn, bar: el.querySelector(".wbBar"), sub: el.querySelector(".wbSub"), tools: el.querySelector(".wbTools"),
              body: el.querySelector(".body") };
    var st = store(id) || {};
    var d = def();
    el.style.left = (st.x != null ? st.x : d.x) + "px";
    el.style.top = (st.y != null ? st.y : d.y) + "px";
    el.style.width = (st.w || d.w) + "px";
    el.style.height = (st.h || d.h) + "px";
    btn.onclick = function () { setOpen(w, !el.classList.contains("open")); };
    el.querySelector(".x").onclick = function () { setOpen(w, false); };
    el.addEventListener("pointerdown", function (e) { front(w); e.stopPropagation(); });
    el.addEventListener("wheel", function (e) { e.stopPropagation(); }, { passive: true });   // колесо — прокрутка окна, а не масштаб мозга
    el.addEventListener("contextmenu", function (e) { e.stopPropagation(); });
    // перетаскивание за шапку
    var drag = null;
    w.bar.addEventListener("pointerdown", function (e) {
      if (e.target.closest("button,input") || innerWidth <= 900) return;
      drag = { x: e.clientX - el.offsetLeft, y: e.clientY - el.offsetTop };
      w.bar.setPointerCapture(e.pointerId);
    });
    w.bar.addEventListener("pointermove", function (e) {
      if (!drag) return;
      el.style.left = (e.clientX - drag.x) + "px"; el.style.top = (e.clientY - drag.y) + "px";
      clampPos(w);
    });
    w.bar.addEventListener("pointerup", function () { if (drag) { drag = null; save(w); } });
    if (window.ResizeObserver) {
      var t = 0;
      new ResizeObserver(function () { clearTimeout(t); t = setTimeout(function () { save(w); }, 300); }).observe(el);
    }
    wins[id] = w;
    w.restore = function () { if (st.open) setOpen(w, true); };
    return w;
  }
  addEventListener("resize", function () { Object.keys(wins).forEach(function (k) { if (wins[k].el.classList.contains("open")) clampPos(wins[k]); }); });

  function ago(ts) {
    if (!ts) return "";
    var d = new Date(ts * 1000), now = new Date();
    if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
  }
  function size(b) {
    if (b < 1024) return b + " Б";
    var u = ["КБ", "МБ", "ГБ", "ТБ"], i = -1;
    do { b /= 1024; i++; } while (b >= 1024 && i < u.length - 1);
    return (b >= 10 ? Math.round(b) : b.toFixed(1)).toString().replace(".", ",") + " " + u[i];
  }

  // ================================================================ ТЕРМИНАЛ
  var term = makeWin("wbTerm", "Терминал", "Терминал", function () {
    var w = Math.min(680, vw() - 80);
    return { x: Math.round((vw() - w) / 2), y: Math.max(80, vh() - 370), w: w, h: 290 };
  }, "Ctrl+`");
  term.body.innerHTML = "<pre id='wbOut'></pre><div class='wbIn'><span class='ps'></span><input id='wbCmd' spellcheck='false' " +
    "autocomplete='off' placeholder='команда — Enter; ↑ история; Ctrl+C — стоп'></div>";
  term.tools.innerHTML = "<button data-t='stop' hidden>Стоп</button><button data-t='clear'>Очистить</button>";
  var out = term.body.querySelector("#wbOut"), cmdIn = term.body.querySelector("#wbCmd"), ps = term.body.querySelector(".ps");
  var tState = { cwd: "", short: "~", job: null, hist: store("hist") || [], hpos: -1 };
  function writeOut(html) {
    var stick = out.scrollTop + out.clientHeight >= out.scrollHeight - 30;
    out.insertAdjacentHTML("beforeend", html);
    if (out.textContent.length > 400000) {                 // в окне — только хвост
      while (out.firstChild && out.textContent.length > 300000) out.removeChild(out.firstChild);
    }
    if (stick) out.scrollTop = out.scrollHeight;
  }
  function setCwd(r) {
    if (r && r.short) { tState.cwd = r.cwd; tState.short = r.short; }
    ps.innerHTML = esc(tState.short) + " <b>$</b>";
    ps.title = tState.cwd;
    term.sub.textContent = tState.short;
  }
  function busy(on) {
    term.el.classList.toggle("busy", on);
    term.tools.querySelector("[data-t=stop]").hidden = !on;
  }
  function run(cmd) {
    var a = api();
    writeOut("<div class='cmd'><i>" + esc(tState.short) + " $</i> " + esc(cmd) + "</div>");
    if (!a) { writeOut("<div class='bad'>Терминал работает в программе Chloe (python run.py).</div>"); return; }
    var t0 = Date.now();
    a.term_start(cmd).then(function (r) {
      setCwd(r);
      if (r.error) { writeOut("<div class='bad'>" + esc(r.error) + "</div>"); return; }
      if (r.cd || !r.id) return;
      tState.job = r.id; busy(true);
      var off = 0;
      (function poll() {
        a.term_poll(r.id, off).then(function (p) {
          if (p.skipped) writeOut("<div class='meta'>… начало вывода не поместилось …</div>");
          if (p.out) writeOut(esc(p.out));
          off = p.offset || off;
          if (p.done) {
            tState.job = null; busy(false);
            var sec = (Date.now() - t0) / 1000;
            if (p.code) writeOut("<div class='bad'>код " + esc(p.code) + (sec > 2 ? " · " + sec.toFixed(1) + " с" : "") + "</div>");
            else if (sec > 2) writeOut("<div class='meta'>готово · " + sec.toFixed(1) + " с</div>");
            return;
          }
          setTimeout(poll, p.out ? 60 : 180);
        }).catch(function (e) { tState.job = null; busy(false); writeOut("<div class='bad'>" + esc(e && e.message || e) + "</div>"); });
      })();
    }).catch(function (e) { writeOut("<div class='bad'>" + esc(e && e.message || e) + "</div>"); });
  }
  function stopJob() { var a = api(); if (a && tState.job) { a.term_stop(tState.job); writeOut("<div class='meta'>^C</div>"); } }
  term.tools.onclick = function (e) {
    var b = e.target.closest("button"); if (!b) return;
    if (b.dataset.t === "clear") out.innerHTML = "";
    if (b.dataset.t === "stop") stopJob();
    cmdIn.focus();
  };
  cmdIn.addEventListener("keydown", function (e) {
    e.stopPropagation();                                   // горячие клавиши мозга (+, −, 0) не срабатывают при наборе
    if (e.key === "c" && e.ctrlKey && tState.job && cmdIn.selectionStart === cmdIn.selectionEnd) { e.preventDefault(); stopJob(); return; }
    if (e.key === "l" && e.ctrlKey) { e.preventDefault(); out.innerHTML = ""; return; }
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      if (!tState.hist.length) return;
      e.preventDefault();
      tState.hpos = e.key === "ArrowUp" ? Math.min(tState.hist.length - 1, tState.hpos + 1) : Math.max(-1, tState.hpos - 1);
      cmdIn.value = tState.hpos < 0 ? "" : tState.hist[tState.hpos];
      return;
    }
    if (e.key !== "Enter") return;
    var cmd = cmdIn.value.trim();
    if (!cmd) return;
    if (tState.job) { writeOut("<div class='meta'>команда ещё идёт — Ctrl+C или «Стоп», чтобы остановить</div>"); return; }
    cmdIn.value = ""; tState.hpos = -1;
    if (tState.hist[0] !== cmd) { tState.hist.unshift(cmd); tState.hist = tState.hist.slice(0, 100); store("hist", tState.hist); }
    if (cmd === "clear" || cmd === "cls") { out.innerHTML = ""; return; }
    run(cmd);
  });
  out.addEventListener("click", function () { if (!getSelection().toString()) cmdIn.focus(); });
  term.onOpen = function () {
    var a = api();
    if (a) a.term_state().then(setCwd).catch(function () {});
    else if (!out.innerHTML) out.innerHTML = NOAPP;
    setCwd(); setTimeout(function () { cmdIn.focus(); }, 30);
  };
  window.chloeTerminalAt = function (path) {          // «Терминал здесь» из окна «Файлы»
    setOpen(term, true);
    var a = api(); if (!a) return;
    a.term_cd(path).then(function (r) { setCwd(r); if (r.error) writeOut("<div class='bad'>" + esc(r.error) + "</div>"); });
  };
  window.chloeTerminalInsert = function (text) {
    setOpen(term, true);
    var q = /[\s'"$`\\]/.test(text) ? "'" + text.replace(/'/g, "'\\''") + "'" : text;
    cmdIn.value = (cmdIn.value ? cmdIn.value.replace(/\s*$/, " ") : "") + q + " ";
    cmdIn.focus();
  };
  addEventListener("keydown", function (e) {
    if (e.ctrlKey && (e.key === "`" || e.key === "ё" || e.key === "Ё" || e.code === "Backquote")) {
      e.preventDefault(); setOpen(term, !term.el.classList.contains("open"));
    }
  });

  // ================================================================ ФАЙЛЫ
  var files = makeWin("wbFiles", "Файлы", "Файлы", function () {
    return { x: 40, y: 88, w: 400, h: Math.max(240, Math.min(420, vh() - 470)) };
  });
  files.tools.innerHTML = "<button data-f='up' title='Папка выше'>↑</button><button data-f='new'>+ папка</button>" +
    "<button data-f='term' title='Открыть терминал в этой папке'>терминал здесь</button><button data-f='reload' title='Обновить'>⟳</button>";
  files.body.innerHTML = "<div class='wbRow2' id='wbPlaces'></div><div class='wbRow2'><input id='wbFilter' placeholder='Найти в папке' " +
    "autocomplete='off'><button class='wbTool' id='wbHidden' title='Показать скрытые файлы'>скрытые</button></div>" +
    "<div id='wbList'></div><div class='wbFoot'><span id='wbCount'></span><span id='wbMsg'></span></div>";
  var fList = files.body.querySelector("#wbList"), fFilter = files.body.querySelector("#wbFilter"),
      fPlaces = files.body.querySelector("#wbPlaces"), fCount = files.body.querySelector("#wbCount"),
      fMsg = files.body.querySelector("#wbMsg"), fHidden = files.body.querySelector("#wbHidden");
  var fState = { path: store("path") || "", data: null, hidden: false, armed: null, renaming: null, creating: false, sel: null };
  function msg(text, bad) { fMsg.innerHTML = text ? "<span class='" + (bad ? "wbErr" : "") + "'>" + esc(text) + "</span>" : ""; }
  function load(path) {
    var a = api();
    if (!a) { fList.innerHTML = NOAPP; return; }
    a.files_dir(path || "", fState.hidden).then(function (d) {
      if (d.error && !d.path) { msg(d.error, true); return; }
      if (d.path !== fState.path) { fFilter.value = ""; fState.sel = null; msg(""); }
      fState.data = d; fState.path = d.path || fState.path; fState.armed = null; fState.renaming = null;
      store("path", fState.path);
      if (d.error) msg(d.error, true);
      render();
    }).catch(function (e) { msg(e && e.message || String(e), true); });
  }
  function render() {
    var d = fState.data; if (!d) return;
    files.sub.textContent = d.short || d.path;
    files.sub.title = d.path;
    fPlaces.innerHTML = (d.places || fState.places || []).map(function (p) {
      return "<button class='pl" + (p.path === d.path ? " on" : "") + "' data-go='" + esc(p.path) + "'>" + esc(p.name) + "</button>";
    }).join("");
    if (d.places) fState.places = d.places;
    var q = fFilter.value.trim().toLowerCase();
    var items = (d.items || []).filter(function (i) { return !q || i.name.toLowerCase().indexOf(q) >= 0; });
    var h = [];
    if (fState.creating) h.push("<div class='wbF dir'><span class='ic'></span><input id='wbNew' placeholder='Имя новой папки'><span></span></div>");
    items.forEach(function (i, k) {
      var cls = "wbF" + (i.dir ? " dir" : "") + (i.private ? " priv" : "") + (fState.sel === i.path ? " sel" : "");
      var name = fState.renaming === i.path ? "<input class='ren' value='" + esc(i.name) + "'>" :
        "<span class='nm' title='" + esc(i.name) + "'>" + esc(i.name) + (i.private ? " · приватная" : "") + "</span>";
      var meta = i.dir ? ago(i.mtime) : size(i.size) + " · " + ago(i.mtime);
      h.push("<div class='" + cls + "' data-i='" + k + "'><span class='ic'></span>" + name +
        "<span class='mt'>" + esc(meta) + "</span><span class='acts'>" +
        (i.dir ? "" : "<button data-a='open'>открыть</button>") +
        "<button data-a='term'>" + (i.dir ? "терминал" : "путь в терминал") + "</button>" +
        "<button data-a='ren'>имя</button>" +
        "<button data-a='del' class='del" + (fState.armed === i.path ? " armed" : "") + "'>" + (fState.armed === i.path ? "точно в корзину?" : "в корзину") + "</button>" +
        "</span></div>");
    });
    if (!items.length && !fState.creating) h.push("<div class='wbEmpty'>" + (q ? "Ничего не найдено." : d.error ? "" : "Пустая папка.") + "</div>");
    fList.innerHTML = h.join("");
    fList._items = items;
    fCount.textContent = d.items ? (q ? items.length + " из " : "") + d.total + " " + plural(d.total, "объект", "объекта", "объектов") +
      (d.total > (d.items || []).length ? " (показаны первые " + d.items.length + ")" : "") : "";
    var ni = fList.querySelector("#wbNew"), ri = fList.querySelector("input.ren");
    if (ni) { ni.focus(); bindInput(ni, function (v) { act("mkdir", v); }, function () { fState.creating = false; render(); }); }
    if (ri) { ri.focus(); ri.setSelectionRange(0, ri.value.replace(/\.[^.]+$/, "").length || ri.value.length);
      bindInput(ri, function (v) { act("rename", v); }, function () { fState.renaming = null; render(); }); }
  }
  function plural(n, a, b, c) { n = Math.abs(n) % 100; var m = n % 10; return n > 10 && n < 20 ? c : m === 1 ? a : m > 1 && m < 5 ? b : c; }
  function bindInput(inp, ok, cancel) {
    inp.addEventListener("keydown", function (e) {
      e.stopPropagation();
      if (e.key === "Enter" && inp.value.trim()) ok(inp.value.trim());
      if (e.key === "Escape") cancel();
    });
    inp.addEventListener("blur", function () { setTimeout(cancel, 150); });
  }
  function act(kind, value, item) {
    var a = api(); if (!a) return;
    var p;
    if (kind === "mkdir") p = a.files_mkdir(fState.path, value).then(function (r) { fState.creating = false; return r; });
    if (kind === "rename") p = a.files_rename(fState.renaming, value);
    if (kind === "trash") p = a.files_trash(item.path);
    p.then(function (r) {
      if (r && r.error) { msg(r.error, true); fState.renaming = null; fState.creating = false; render(); return; }
      msg(kind === "trash" ? "В корзине: " + item.name + " — отменить можно в «Изменения файлов»" : "");
      load(fState.path);
    }).catch(function (e) { msg(e && e.message || String(e), true); });
  }
  fList.addEventListener("click", function (e) {
    var row = e.target.closest(".wbF[data-i]"); if (!row) return;
    var it = fList._items[+row.dataset.i], b = e.target.closest("button[data-a]");
    if (e.target.closest("input")) return;
    if (b) {
      var a = b.dataset.a;
      if (a === "open") api() && api().files_open(it.path).then(function (r) { if (r.error) msg(r.error, true); });
      if (a === "term") it.dir ? window.chloeTerminalAt(it.path) : window.chloeTerminalInsert(it.path);
      if (a === "ren") { fState.renaming = it.path; fState.armed = null; render(); }
      if (a === "del") { if (fState.armed === it.path) act("trash", null, it); else { fState.armed = it.path; render(); } }
      return;
    }
    if (it.dir) { if (it.private) { msg("Это приватная папка — внутрь не заглядываю", true); return; } load(it.path); return; }
    fState.sel = it.path; fState.armed = null; render();
  });
  fList.addEventListener("dblclick", function (e) {
    var row = e.target.closest(".wbF[data-i]"); if (!row || e.target.closest("button,input")) return;
    var it = fList._items[+row.dataset.i];
    if (!it.dir && api()) api().files_open(it.path).then(function (r) { if (r.error) msg(r.error, true); });
  });
  fPlaces.addEventListener("click", function (e) { var b = e.target.closest("[data-go]"); if (b) load(b.dataset.go); });
  files.tools.addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b || !fState.data) return;
    var f = b.dataset.f;
    if (f === "up" && fState.data.parent) load(fState.data.parent);
    if (f === "new") { fState.creating = true; fState.renaming = null; render(); }
    if (f === "term") window.chloeTerminalAt(fState.path);
    if (f === "reload") load(fState.path);
  });
  fFilter.addEventListener("input", render);
  fFilter.addEventListener("keydown", function (e) { e.stopPropagation(); if (e.key === "Escape") { fFilter.value = ""; render(); } });
  fHidden.onclick = function () {
    fState.hidden = !fState.hidden;
    fHidden.style.color = fState.hidden ? "var(--ink)" : "";
    load(fState.path);
  };
  files.onOpen = function () { load(fState.path); };

  // ================================================================ ПРОЕКТЫ
  var proj = makeWin("wbProj", "Проекты", "Проекты", function () {
    return { x: Math.max(40, vw() - 400), y: 88, w: 360, h: Math.max(240, Math.min(420, vh() - 470)) };
  });
  proj.tools.innerHTML = "<button data-p='new'>+ проект</button><button data-p='full' title='Все задачи, решения и цели'>подробно →</button>";
  proj.body.innerHTML = "<div id='wbProjList'></div><div class='wbFoot'><span id='wbProjCount'></span><span id='wbProjMsg'></span></div>";
  var pList = proj.body.querySelector("#wbProjList"), pCount = proj.body.querySelector("#wbProjCount");
  var pState = { open: store("proj"), list: [], detail: null, showDone: false, creating: false, newName: "" };
  var NEXT = { todo: "doing", doing: "done", done: "todo" },
      HINT = { todo: "сделать → взять в работу", doing: "в работе → готово", done: "готово → снова сделать" };
  function pLoad() {
    var a = api();
    if (!a || !a.projects_list) { pList.innerHTML = NOAPP; return; }
    a.projects_list().then(function (list) {
      pState.list = list || [];
      if (pState.open && !pState.list.some(function (p) { return p.name === pState.open; })) pState.open = null;
      if (pState.open) a.project_get(pState.open).then(function (d) { pState.detail = d; pRender(); });
      else { pState.detail = null; pRender(); }
    });
  }
  function pRender() {
    var h = [];
    if (!pState.list.length && !pState.creating) h.push("<div class='wbEmpty'>Проектов пока нет. Нажмите «+ проект» или скажите: «Хлоя, добавь задачу в проект …»</div>");
    if (pState.creating) h.push("<div class='wbP'><div class='add'>" + (pState.newName ?
      "<input id='wbNewProj' data-step='task' placeholder='Первая задача для «" + esc(pState.newName) + "» — Enter'>" :
      "<input id='wbNewProj' placeholder='Название проекта — Enter'>") + "</div></div>");
    pState.list.forEach(function (p) {
      var total = p.todo + p.doing + p.done || 1;
      h.push("<div class='wbP' data-p='" + esc(p.name) + "'><div class='hd'><span class='n'>" + esc(p.name) + "</span><span class='c'>" +
        (p.doing ? "<b>" + p.doing + " в работе</b> · " : "") + p.todo + " сделать · " + p.done + " готово</span></div>" +
        "<div class='bar2'><i class='dn' style='width:" + (p.done / total * 100) + "%'></i><i class='dg' style='width:" + (p.doing / total * 100) + "%'></i></div>");
      if (pState.open === p.name && pState.detail) {
        var tasks = pState.detail.tasks || [], done = tasks.filter(function (t) { return t.status === "done"; });
        var shown = tasks.filter(function (t) { return t.status !== "done" || pState.showDone; });
        h.push("<div class='tasks'>" + shown.map(function (t) {
          return "<div class='wbT " + t.status + "'><button data-tid='" + t.id + "' data-s='" + NEXT[t.status] + "' title='" + HINT[t.status] + "'>" +
            "<i></i></button><span class='t'>" + esc(t.title) + (t.priority === 1 ? "<i>важно</i>" : "") + "</span></div>";
        }).join("") + "</div><div class='add'><input class='newTask' placeholder='Новая задача — Enter'></div>" +
        "<div class='more'><span data-done>" + (done.length ? (pState.showDone ? "скрыть готовые" : "показать готовые (" + done.length + ")") : "") + "</span>" +
        "<span data-full>все решения и цели →</span></div>");
      }
      h.push("</div>");
    });
    pList.innerHTML = h.join("");
    pCount.textContent = pState.list.length ? pState.list.length + " " + plural(pState.list.length, "проект", "проекта", "проектов") : "";
    var nt = pList.querySelector(".newTask");
    if (pState.focusTask && nt) { nt.focus(); pState.focusTask = false; }
    if (nt) nt.addEventListener("keydown", function (e) {
      e.stopPropagation();
      if (e.key === "Enter" && nt.value.trim()) api().project_task_add(pState.open, nt.value.trim(), 2).then(function () { pState.focusTask = true; pLoad(); });
    });
    var np = pList.querySelector("#wbNewProj");
    if (np) {
      np.focus();
      np.addEventListener("keydown", function (e) {
        e.stopPropagation();
        if (e.key === "Escape") { pState.creating = false; pState.newName = ""; pRender(); return; }
        if (e.key !== "Enter" || !np.value.trim()) return;
        if (!np.dataset.step) { pState.newName = np.value.trim(); pRender(); return; }
        var name = pState.newName;                     // проект появляется вместе с первой задачей
        api().project_task_add(name, np.value.trim(), 2).then(function (d) {
          pState.creating = false; pState.newName = ""; pState.open = (d && d.name) || name; store("proj", pState.open); pLoad();
        });
      });
    }
  }
  function openFull(name) {
    var b = document.getElementById("projectsBtn");
    if (b) b.click();
    if (name && window.chloeOpenProject) window.chloeOpenProject(name);
  }
  pList.addEventListener("click", function (e) {
    var s = e.target.closest("button[data-tid]");
    if (s) { api().project_task_status(+s.dataset.tid, s.dataset.s).then(function () { pLoad(); }); return; }
    if (e.target.closest("[data-done]")) { pState.showDone = !pState.showDone; pRender(); return; }
    if (e.target.closest("[data-full]")) { openFull(pState.open); return; }
    var hd = e.target.closest(".hd");
    if (hd) {
      var name = hd.parentNode.dataset.p;
      pState.open = pState.open === name ? null : name; pState.showDone = false;
      store("proj", pState.open); pLoad();
    }
  });
  proj.tools.onclick = function (e) {
    if (e.target.closest("[data-p=full]")) openFull(pState.open);
    if (e.target.closest("[data-p=new]")) { pState.creating = true; pState.newName = ""; pRender(); }
  };
  proj.onOpen = pLoad;
  setInterval(function () { if (proj.el.classList.contains("open") && !proj.el.contains(document.activeElement)) pLoad(); }, 20000);


  // ================================================================ ОБЩЕЕ: просьба Chloe, отметка «сделано»
  function ask(text) {
    var a = api() || (window.pywebview && window.pywebview.api);
    if (a && a.command) { a.command(text); toast("Передала Chloe: «" + text.slice(0, 80) + (text.length > 80 ? "…" : "") + "»"); return true; }
    toast("Просьбы выполняет программа Chloe (python run.py)", true);
    return false;
  }
  var toastEl = document.createElement("div");
  toastEl.id = "wbToast";
  app.appendChild(toastEl);
  var toastT = 0;
  function toast(text, bad) {
    toastEl.textContent = text; toastEl.className = "show" + (bad ? " bad" : "");
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.className = ""; }, 2600);
  }
  // просьбы из строки ввода — в «Недавние» палитры
  var cmdEl = document.getElementById("cmd"), asks = store("asks") || [];
  if (cmdEl) cmdEl.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !cmdEl.value.trim()) return;
    var t = cmdEl.value.trim();
    asks = [t].concat(asks.filter(function (x) { return x !== t; })).slice(0, 30); store("asks", asks);
  }, true);

  css.textContent += [
    "#wbToast { position: absolute; left: 50%; top: 76px; transform: translate(-50%, -8px); z-index: 30; padding: 8px 14px; font-size: 13px;",
    "  background: rgba(16,16,16,.96); border: 1px solid var(--line); color: var(--bone); opacity: 0; pointer-events: none;",
    "  transition: opacity .2s, transform .2s; max-width: min(560px, 90vw); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }",
    "#wbToast.show { opacity: 1; transform: translate(-50%, 0); } #wbToast.bad { color: var(--coral); }",
    "#wbDock button .cnt { font-size: 12px; color: var(--coral); margin-left: 6px; font-variant-numeric: tabular-nums; }",
    "#wbDock .find { color: var(--iron); border: 1px solid var(--line); border-radius: 0; padding: 4px 10px; min-height: 28px; align-self: center; }",
    "#wbDock .find:hover { border-color: var(--bone); }",
    "#wbDock .find kbd { font: inherit; font-size: 11px; margin-left: 10px; color: var(--iron); }"
  ].join("\n");

  // ================================================================ ВХОДЯЩИЕ
  var inbox = makeWin("wbInbox", "Входящие", "Входящие", function () {
    return { x: Math.max(40, vw() - 420), y: 88, w: 380, h: Math.max(260, Math.min(460, vh() - 200)) };
  });
  inbox.tools.innerHTML = "<button data-i='seen' title='Отметить всё просмотренным'>всё прочитано</button><button data-i='reload' title='Обновить'>⟳</button>";
  inbox.body.innerHTML = "<div id='wbInList'></div>";
  css.textContent += [
    "#wbInList { flex: 1; min-height: 0; overflow: auto; padding-bottom: 10px; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }",
    ".wbG { margin: 12px 14px 2px; font-size: 10px; letter-spacing: .16em; text-transform: uppercase; color: var(--iron); }",
    ".wbI { padding: 9px 14px; border-bottom: 1px solid #161616; position: relative; }",
    ".wbI.new::before { content: ''; position: absolute; left: 5px; top: 15px; width: 4px; height: 4px; border-radius: 50%; background: var(--coral); }",
    ".wbI .t { color: var(--ink); line-height: 1.4; } .wbI.urgent .t { color: var(--coral); }",
    ".wbI .s { color: var(--iron); font-size: 12px; margin-top: 2px; overflow-wrap: anywhere; }",
    ".wbI .a { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 6px; }",
    ".wbI .a button { background: transparent; border: 0; border-bottom: 1px solid var(--line); color: var(--bone); font: 400 12px var(--font); padding: 2px 0; cursor: pointer; }",
    ".wbI .a button:hover { color: var(--ink); border-color: var(--coral); }",
    ".wbI .a button.first { color: var(--ink); border-color: var(--bone); }"
  ].join("\n");
  var inList = inbox.body.querySelector("#wbInList"), inState = { items: [], seen: store("seen") || {}, hidden: store("hidden") || {} };
  function inUnseen() { return inState.items.filter(function (i) { return !inState.seen[i.key]; }).length; }
  function inBadge() {
    var n = inUnseen();
    inbox.btn.innerHTML = "Входящие" + (n ? "<span class='cnt'>" + n + "</span>" : "");
    inbox.btn.title = n ? n + " новых" : "Входящие от Chloe";
  }
  function inLoad() {
    var a = api();
    if (!a || !a.inbox) { if (inbox.el.classList.contains("open")) inList.innerHTML = NOAPP; return; }
    a.inbox().then(function (items) {
      inState.items = (items || []).filter(function (i) { return !inState.hidden[i.key]; });
      inBadge(); inRender();
    }).catch(function () {});
  }
  function inRender() {
    if (!inbox.el.classList.contains("open")) return;
    var h = [], group = "";
    if (!inState.items.length) h.push("<div class='wbEmpty'>Пусто — ничего не ждёт вашего решения. Готовые работы и вопросы Chloe появятся здесь.</div>");
    inState.items.forEach(function (it, k) {
      if (it.group !== group) { group = it.group; h.push("<div class='wbG'>" + esc(group) + "</div>"); }
      h.push("<div class='wbI" + (inState.seen[it.key] ? "" : " new") + (it.urgent ? " urgent" : "") + "' data-k='" + k + "'><div class='t'>" + esc(it.title) +
        "</div>" + (it.sub ? "<div class='s'>" + esc(it.sub) + "</div>" : "") + "<div class='a'>" +
        (it.actions || []).map(function (x, j) { return "<button class='" + (j ? "" : "first") + "' data-j='" + j + "'>" + esc(x.label) + "</button>"; }).join("") +
        (it.kind === "tip" ? "" : "<button data-hide>скрыть</button>") + "</div></div>");
    });
    inList.innerHTML = h.join("");
  }
  function markSeen() {
    inState.items.forEach(function (i) { inState.seen[i.key] = 1; });
    var keys = Object.keys(inState.seen); if (keys.length > 400) keys.slice(0, keys.length - 300).forEach(function (k) { delete inState.seen[k]; });
    store("seen", inState.seen); inBadge();
  }
  inList.addEventListener("click", function (e) {
    var row = e.target.closest(".wbI"); if (!row) return;
    var it = inState.items[+row.dataset.k], a = api();
    inState.seen[it.key] = 1; store("seen", inState.seen);
    if (e.target.closest("[data-hide]")) { inState.hidden[it.key] = 1; store("hidden", inState.hidden); inLoad(); return; }
    var b = e.target.closest("button[data-j]"); if (!b || !a) { inBadge(); inRender(); return; }
    var x = it.actions[+b.dataset.j];
    if (x.do === "answer") a.answer_pending(!!x.arg).then(function () { setTimeout(inLoad, 800); });
    if (x.do === "say") ask(x.arg);
    if (x.do === "open") a.files_open(x.arg).then(function (r) { if (r && r.error) toast(r.error, true); });
    if (x.do === "reveal") { setOpen(files, true); load(String(x.arg).replace(/\/[^\/]*$/, "")); }
    if (x.do === "dismiss") a.proactive_dismiss(x.arg).then(inLoad);
    if (x.do !== "answer" && x.do !== "dismiss") { inBadge(); inRender(); }
  });
  inbox.tools.onclick = function (e) {
    var b = e.target.closest("button"); if (!b) return;
    if (b.dataset.i === "seen") { markSeen(); inRender(); }
    if (b.dataset.i === "reload") inLoad();
  };
  inbox.onOpen = function () { inLoad(); setTimeout(function () { markSeen(); }, 4000); };
  inBadge();
  setInterval(inLoad, 15000);

  // ================================================================ РАСКЛАДКИ
  var LAYOUTS = {
    "Работа": { open: ["wbTerm", "wbFiles", "wbProj"], clean: null },
    "Студия": { open: ["wbFiles", "wbInbox"], clean: null },
    "Тишина": { open: [], clean: true }
  };
  function layouts() { var s = store("layouts") || {}; var all = {}; Object.keys(LAYOUTS).forEach(function (k) { all[k] = LAYOUTS[k]; });
    Object.keys(s).forEach(function (k) { all[k] = s[k]; }); return all; }
  function setClean(on) {
    if (on === null || on === undefined) return;
    if (document.body.classList.contains("clean") !== on) { var b = document.getElementById("moreBtn"); if (b) b.click(); }
  }
  function closePanels() {
    document.querySelectorAll("#toggles button.on, #moreMenu button.on").forEach(function (b) {
      if (["micBtn", "soundBtn", "wallBtn"].indexOf(b.id) < 0) b.click();
    });
  }
  function closeAll() { Object.keys(wins).forEach(function (k) { if (wins[k].el.classList.contains("open")) setOpen(wins[k], false); }); closePanels(); }
  function applyLayout(name) {
    var all = layouts(), key = Object.keys(all).filter(function (k) { return k.toLowerCase() === String(name).toLowerCase().trim(); })[0];
    if (!key) { toast("Нет раскладки «" + name + "»", true); return false; }
    var L = all[key];
    closePanels();
    Object.keys(wins).forEach(function (id) {
      var w = wins[id], on = L.open.indexOf(id) >= 0, pos = L.pos && L.pos[id];
      if (pos) { w.el.style.left = pos.x + "px"; w.el.style.top = pos.y + "px"; w.el.style.width = pos.w + "px"; w.el.style.height = pos.h + "px"; }
      if (w.el.classList.contains("open") !== on) setOpen(w, on); else if (on) { clampPos(w); save(w); }
    });
    setClean(L.clean);
    store("layout", key);
    toast("Раскладка «" + key + "»");
    return true;
  }
  function saveLayout(name) {
    name = String(name || "").trim().slice(0, 30); if (!name) return;
    var s = store("layouts") || {}, L = { open: [], pos: {}, clean: document.body.classList.contains("clean") };
    Object.keys(wins).forEach(function (id) {
      var el = wins[id].el;
      if (el.classList.contains("open")) L.open.push(id);
      L.pos[id] = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    });
    s[name] = L; store("layouts", s); store("layout", name);
    toast("Запомнила раскладку «" + name + "»");
  }
  function deleteLayout(name) { var s = store("layouts") || {}; delete s[name]; store("layouts", s); }

  // ================================================================ БЫСТРЫЕ КНОПКИ
  var DEFAULT_BTNS = [
    { label: "Утренний план", request: "утренний план: что сегодня, сроки, задачи" },
    { label: "Что в Telegram", request: "что нового в телеграме" },
    { label: "Отчёт за неделю", request: "отчёт за неделю: расходы, доходы, что сделано" },
    { label: "Загрузки", request: "посмотри, что лежит в Загрузках, и предложи, как разложить" }
  ];
  var quick = document.createElement("div");
  quick.id = "wbQuick";
  app.appendChild(quick);
  css.textContent += [
    "#wbQuick { position: absolute; z-index: 4; left: 40px; bottom: 84px; display: flex; flex-wrap: wrap; gap: 6px 8px; max-width: min(600px, calc(100% - 560px)); }",
    "body.clean #wbQuick { left: 50%; transform: translateX(-50%); bottom: 82px; max-width: min(760px, calc(100% - 80px)); justify-content: center; opacity: .6; transition: opacity .25s; }",
    "body.clean #wbQuick:hover, body.clean #wbQuick:focus-within { opacity: 1; }",
    "#wbQuick button { position: relative; background: rgba(10,10,10,.6); border: 1px solid var(--line); color: var(--bone); font: 400 13px var(--font);",
    "  letter-spacing: -.01em; padding: 6px 12px; cursor: pointer; transition: color .15s, border-color .15s; }",
    "#wbQuick button:hover { color: var(--ink); border-color: var(--bone); }",
    "#wbQuick button.run { color: var(--coral); border-color: var(--coral); }",
    "#wbQuick button.add { color: var(--iron); border-style: dashed; padding: 6px 10px; }",
    "#wbQuick button i { display: none; position: absolute; right: -7px; top: -7px; width: 15px; height: 15px; line-height: 13px; border-radius: 50%;",
    "  background: var(--bg); border: 1px solid var(--line); color: var(--iron); font: 400 11px var(--font); font-style: normal; text-align: center; }",
    "#wbQuick.edit button i { display: block; } #wbQuick button i:hover, #wbQuick button i.armed { color: var(--coral); border-color: var(--coral); }",
    "@media (min-width: 901px) { body.clean #reply { bottom: 132px; } #reply { bottom: 150px; } }",
    "@media (max-width: 900px) { body.clean #reply { bottom: calc(var(--sa, 0px) + 116px); } }",
    "body.wall #wbQuick { display: none; }",
    "@media (max-width: 900px) { #wbQuick { left: 20px; right: 20px; max-width: none; transform: none !important; bottom: calc(var(--sa, 0px) + 66px);",
    "  flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; justify-content: flex-start !important; }",
    "  #wbQuick button { flex: none; } body:not(.clean) #wbQuick { display: none; }",
    "  #wbQuick { -webkit-mask-image: linear-gradient(90deg, #000 calc(100% - 40px), transparent); mask-image: linear-gradient(90deg, #000 calc(100% - 40px), transparent); padding-right: 40px; } }"
  ].join("\n");
  var qState = { items: DEFAULT_BTNS.slice(), edit: false, armed: null };
  function qRender() {
    quick.classList.toggle("edit", qState.edit);
    quick.innerHTML = qState.items.map(function (b, k) {
      return "<button data-q='" + k + "' title='" + esc(b.request) + "'>" + esc(b.label) + "<i data-x='" + k + "' class='" + (qState.armed === k ? "armed" : "") +
        "' title='" + (qState.armed === k ? "ещё раз — убрать" : "убрать кнопку") + "'>×</i></button>";
    }).join("") + "<button class='add' data-add title='Своя кнопка: название и просьба. Или голосом: «сделай кнопку …»'>+</button>" +
      (qState.items.length ? "<button class='add' data-edit title='Убрать кнопки'>" + (qState.edit ? "готово" : "✎") + "</button>" : "");
  }
  function qLoad() { var a = api(); if (a && a.quick_buttons_get) a.quick_buttons_get().then(function (l) { qState.items = l || []; qRender(); }); else qRender(); }
  function qSave(items) {
    qState.items = items; qRender();
    var a = api(); if (a && a.quick_buttons_save) a.quick_buttons_save(items).then(function (l) { qState.items = l; qRender(); });
  }
  quick.addEventListener("click", function (e) {
    var x = e.target.closest("i[data-x]");
    if (x) {
      e.stopPropagation(); var k = +x.dataset.x;
      if (qState.armed === k) { qState.armed = null; qSave(qState.items.filter(function (_, i) { return i !== k; })); }
      else { qState.armed = k; qRender(); }
      return;
    }
    if (e.target.closest("[data-add]")) { openPalette("button"); return; }
    if (e.target.closest("[data-edit]")) { qState.edit = !qState.edit; qState.armed = null; qRender(); return; }
    var b = e.target.closest("button[data-q]"); if (!b) return;
    if (qState.edit) return;
    var it = qState.items[+b.dataset.q];
    if (ask(it.request)) { b.classList.add("run"); setTimeout(function () { b.classList.remove("run"); }, 1500); }
  });
  quick.addEventListener("pointerdown", function (e) { e.stopPropagation(); });

  // ================================================================ ЛЕНТА «СЕЙЧАС»
  var now = document.createElement("div");
  now.id = "wbNow";
  now.innerHTML = "<div class='row'><i class='d'></i><span class='what'></span><span class='step'></span><span class='meta'></span>" +
    "<button data-n='stop'>Стоп</button><button data-n='undo'>Отменить последнее</button><button data-n='more' title='Шаги'>▾</button></div><div class='steps'></div>";
  app.appendChild(now);
  css.textContent += [
    "#wbNow { position: absolute; z-index: 7; left: 50%; top: 76px; transform: translate(-50%, -6px); opacity: 0; pointer-events: none;",
    "  max-width: min(760px, calc(100% - 520px)); min-width: 320px; background: rgba(12,12,12,.92); border: 1px solid var(--line);",
    "  backdrop-filter: blur(8px); transition: opacity .25s, transform .25s; font-size: 13px; }",
    "#wbNow.show { opacity: 1; transform: translate(-50%, 0); pointer-events: auto; }",
    "#wbNow .row { display: flex; align-items: center; gap: 10px; padding: 7px 8px 7px 14px; white-space: nowrap; }",
    "#wbNow .d { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--coral); animation: wbBlink 1.2s ease-in-out infinite; }",
    "#wbNow.done .d { background: var(--bone); animation: none; } #wbNow.fail .d { background: var(--err); animation: none; }",
    "#wbNow .what { color: var(--ink); overflow: hidden; text-overflow: ellipsis; min-width: 60px; flex: 0 1 auto; }",
    "#wbNow .step { color: var(--bone); overflow: hidden; text-overflow: ellipsis; flex: 1 0 auto; max-width: 40%; }",
    "#wbNow .meta { color: var(--iron); font-size: 12px; font-variant-numeric: tabular-nums; flex: none; }",
    "#wbNow button { flex: none; background: transparent; border: 0; color: var(--iron); font: 400 12px var(--font); padding: 3px 6px; cursor: pointer; }",
    "#wbNow button:hover { color: var(--ink); } #wbNow button[data-n=stop] { color: var(--coral); }",
    "#wbNow .steps { display: none; border-top: 1px solid var(--line); padding: 6px 14px 8px; max-height: 220px; overflow: auto; }",
    "#wbNow.open .steps { display: block; }",
    "#wbNow .steps div { display: flex; gap: 10px; padding: 2px 0; color: var(--bone); }",
    "#wbNow .steps div span:first-child { width: 14px; color: var(--iron); } #wbNow .steps div.bad { color: var(--err); }",
    "#wbNow .steps div em { margin-left: auto; color: var(--iron); font-style: normal; font-size: 11px; }",
    "body.wall #wbNow { display: none; }",
    "@media (max-width: 900px) { #wbNow { left: 12px; right: 12px; transform: none !important; max-width: none; min-width: 0; top: calc(104px + env(safe-area-inset-top, 0px)); } }"
  ].join("\n");
  var T = { task: null, hideT: 0, tick: 0 };
  function nowEl(s) { return now.querySelector(s); }
  function nowShow() {
    clearTimeout(T.hideT);
    now.classList.add("show");
    if (!T.tick) T.tick = setInterval(nowRender, 1000);
  }
  function nowHide(later) {
    clearTimeout(T.hideT);
    T.hideT = setTimeout(function () {
      if (now.matches(":hover") || now.classList.contains("open")) { nowHide(4000); return; }
      now.classList.remove("show"); clearInterval(T.tick); T.tick = 0;
    }, later);
  }
  function newTask(title) {
    T.task = { title: title || "", steps: [], t0: Date.now(), cur: "", done: false, changed: false, failed: false };
    nowShow(); nowRender();
  }
  function nowRender() {
    var t = T.task; if (!t) return;
    var sec = Math.round(((t.done ? t.t1 : Date.now()) - t.t0) / 1000);
    now.classList.toggle("done", t.done && !t.failed); now.classList.toggle("fail", t.done && t.failed);
    nowEl(".what").textContent = t.title ? "«" + t.title + "»" : "Chloe работает";
    nowEl(".step").textContent = t.done ? (t.failed ? "не получилось" : "готово") : (t.cur ? "· " + t.cur + "…" : (t.thinking ? "· думает…" : ""));
    nowEl(".meta").textContent = (t.steps.length ? t.steps.length + " " + plural(t.steps.length, "шаг", "шага", "шагов") + " · " : "") + (sec >= 60 ? Math.floor(sec / 60) + " мин " + (sec % 60) + " с" : sec + " с");
    now.querySelector("[data-n=stop]").hidden = t.done;
    now.querySelector("[data-n=undo]").hidden = !t.changed;
    now.querySelector("[data-n=more]").hidden = !t.steps.length;
    now.querySelector("[data-n=more]").textContent = now.classList.contains("open") ? "▴" : "▾";
    nowEl(".steps").innerHTML = t.steps.map(function (s) {
      return "<div class='" + (s.ok ? "" : "bad") + "'><span>" + (s.ok ? "✓" : "×") + "</span><span>" + esc(s.name) + (s.why ? " — " + esc(s.why) : "") + "</span>" +
        (s.sec ? "<em>" + (s.sec < 10 ? s.sec.toFixed(1) : Math.round(s.sec)) + " с</em>" : "") + "</div>";
    }).join("");
  }
  now.addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b) return;
    var a = (window.pywebview && window.pywebview.api) || null;
    if (b.dataset.n === "stop") { if (a && a.command) a.command("стоп"); toast("Остановила"); }
    if (b.dataset.n === "undo") {
      if (!a || !a.undo_last) return;
      a.undo_last().then(function (r) { toast((r && r.message) || (r && r.ok ? "Отменила" : "Нечего отменять"), !(r && r.ok)); if (r && r.ok && T.task) { T.task.changed = false; nowRender(); } });
    }
    if (b.dataset.n === "more") { now.classList.toggle("open"); nowRender(); }
  });
  now.addEventListener("pointerdown", function (e) { e.stopPropagation(); });
  function hook(name, fn) {
    var orig = window[name];
    window[name] = function () { try { fn.apply(null, arguments); } catch (e) {} return typeof orig === "function" ? orig.apply(this, arguments) : undefined; };
  }
  hook("chloeHeard", function (text) { newTask(String(text || "").slice(0, 120)); T.task.thinking = true; nowRender(); });
  hook("chloeUse", function (skill) {
    if (!T.task || T.task.done) newTask("");
    T.task.cur = skill; T.task.thinking = false; nowShow(); nowRender();
  });
  hook("chloeStep", function (skill, sec, ok) {
    if (!T.task || T.task.done) newTask("");
    T.task.steps.push({ name: skill, sec: +sec || 0, ok: ok !== false }); T.task.cur = ""; T.task.thinking = true;
    if (ok === false) T.task.failed = true; else T.task.failed = false;
    nowRender();
  });
  hook("chloeError", function (name, why) {
    if (!T.task) return;
    T.task.steps.push({ name: name, ok: false, why: String(why || "").slice(0, 120) }); T.task.failed = true; nowRender();
  });
  hook("chloeChange", function () { if (T.task) { T.task.changed = true; nowRender(); } });
  hook("chloeState", function (state) {
    if (!T.task) return;
    if (state === "thinking") { T.task.thinking = true; nowShow(); nowRender(); }
    if (state === "idle" && !T.task.done) {
      T.task.done = true; T.task.t1 = Date.now(); T.task.cur = "";
      nowRender(); nowHide(T.task.changed ? 15000 : (T.task.steps.length ? 7000 : 2500));
      setTimeout(inLoad, 1200);                      // результат мог появиться во «Входящих»
    }
  });

  // ================================================================ ПЕРЕТАСКИВАНИЕ ФАЙЛОВ
  var drop = document.createElement("div");
  drop.id = "wbDrop";
  drop.innerHTML = "<div class='zone'>Отпустите — Chloe спросит, что сделать с файлом</div>";
  app.appendChild(drop);
  var dmenu = document.createElement("div");
  dmenu.id = "wbDropMenu";
  app.appendChild(dmenu);
  css.textContent += [
    "#wbDrop { position: absolute; inset: 64px 0 0 0; z-index: 40; display: none; align-items: center; justify-content: center; pointer-events: none;",
    "  background: rgba(10,10,10,.55); }",
    "#wbDrop.on { display: flex; }",
    "#wbDrop .zone { border: 1px dashed var(--coral); color: var(--ink); padding: 34px 48px; font-size: 20px; letter-spacing: -.02em; background: rgba(10,10,10,.8); }",
    "#wbDropMenu { position: absolute; z-index: 41; display: none; width: 330px; background: rgba(14,14,14,.97); border: 1px solid var(--line);",
    "  box-shadow: 0 18px 60px rgba(0,0,0,.6); font-size: 13px; }",
    "#wbDropMenu.on { display: block; }",
    "#wbDropMenu .hd { padding: 12px 14px 8px; border-bottom: 1px solid var(--line); }",
    "#wbDropMenu .hd b { display: block; color: var(--ink); font-weight: 400; font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
    "#wbDropMenu .hd span { color: var(--iron); font-size: 11px; }",
    "#wbDropMenu button { display: block; width: 100%; text-align: left; background: transparent; border: 0; color: var(--bone); font: 400 13px var(--font);",
    "  padding: 8px 14px; cursor: pointer; }",
    "#wbDropMenu button:hover, #wbDropMenu button:focus { background: rgba(255,255,255,.05); color: var(--ink); outline: none; }",
    "#wbDropMenu button small { color: var(--iron); margin-left: 6px; }",
    "#wbDropMenu .sep { border-top: 1px solid var(--line); margin: 4px 0; }"
  ].join("\n");
  var EXT = {
    audio: /\.(mp3|wav|m4a|ogg|oga|opus|flac|aac|wma)$/i, video: /\.(mp4|mov|mkv|webm|avi|m4v)$/i,
    doc: /\.(pdf|docx?|odt|rtf|txt|md|html?|epub)$/i, image: /\.(png|jpe?g|webp|gif|bmp|heic)$/i
  };
  var dState = { depth: 0, pending: null, names: [] };
  function hasFiles(e) { return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0; }
  addEventListener("dragenter", function (e) { if (!hasFiles(e)) return; dState.depth++; drop.classList.add("on"); });
  addEventListener("dragleave", function (e) { if (!hasFiles(e)) return; if (--dState.depth <= 0) { dState.depth = 0; drop.classList.remove("on"); } });
  addEventListener("dragover", function (e) { if (hasFiles(e)) e.preventDefault(); });
  addEventListener("drop", function (e) {
    if (!hasFiles(e)) return;
    e.preventDefault(); dState.depth = 0; drop.classList.remove("on");
    dState.names = Array.prototype.map.call(e.dataTransfer.files || [], function (f) { return f.name; });
    dState.at = { x: e.clientX, y: e.clientY };
    clearTimeout(dState.pending);
    dState.pending = setTimeout(function () {         // программа не прислала пути: в браузере их не узнать
      toast(api() ? "Не получила путь к файлу — откройте его через «Файлы»" : "Перетаскивание работает в программе Chloe", true);
    }, 1500);
  });
  window.chloeDropped = function (paths) {
    clearTimeout(dState.pending);
    paths = (paths || []).filter(Boolean); if (!paths.length) return;
    showDropMenu(paths);
  };
  function quote(p) { return "«" + p + "»"; }
  function showDropMenu(paths) {
    var one = paths.length === 1, p = paths[0], name = p.replace(/^.*[\\\/]/, ""), list = paths.map(quote).join(", ");
    var acts = [];
    function add(label, fn, note) { acts.push({ label: label, fn: fn, note: note }); }
    var isDir = one && !/\.[^\\\/.]{1,6}$/.test(name);
    if (one && EXT.audio.test(p)) add("Расшифровать в текст", function () { ask("расшифруй запись " + quote(p)); });
    if (one && EXT.video.test(p)) {
      add("Расшифровать речь", function () { ask("расшифруй запись " + quote(p)); });
      add("Нарезать Shorts", function () { ask("нарежь Shorts из видео " + quote(p)); });
    }
    if (EXT.doc.test(p)) {
      add("Пересказать кратко", function () { ask("перескажи кратко " + (one ? "документ " : "документы ") + list); });
      add("Изучить в базу знаний", function () { ask("изучи " + (one ? "документ " : "документы ") + list); });
      if (one) add("Озвучить в mp3", function () { ask("озвучь документ " + quote(p)); });
    }
    if (one && EXT.image.test(p)) add("Что на картинке?", function () { ask("посмотри на картинку " + quote(p) + " и опиши, что на ней"); });
    if (isDir) {
      add("Открыть в «Файлах»", function () { setOpen(files, true); load(p); });
      add("Терминал в этой папке", function () { window.chloeTerminalAt(p); });
      add("Изучить документы из папки", function () { ask("изучи документы из папки " + quote(p)); });
    }
    if (!isDir) {
      add("Отправить в Telegram…", function () { fillCmd("отправь в телеграм " + (one ? "файл " : "файлы ") + list + " — кому: "); }, "впишите кому");
      if (one) add("Открыть", function () { api() && api().files_open(p); });
      add("Показать в «Файлах»", function () { setOpen(files, true); load(p.replace(/[\\\/][^\\\/]*$/, "")); });
      add("Путь в терминал", function () { paths.forEach(function (x) { window.chloeTerminalInsert(x); }); });
    }
    add("Своя просьба…", function () { fillCmd(list + " — "); }, "напишите, что сделать");
    dmenu.innerHTML = "<div class='hd'><b>" + esc(one ? name : paths.length + " " + plural(paths.length, "файл", "файла", "файлов")) + "</b><span>" +
      esc(one ? p : paths.map(function (x) { return x.replace(/^.*[\\\/]/, ""); }).join(", ").slice(0, 120)) + "</span></div>" +
      acts.map(function (x, k) { return (x.label === "Своя просьба…" ? "<div class='sep'></div>" : "") + "<button data-k='" + k + "'>" + esc(x.label) +
        (x.note ? "<small>" + esc(x.note) + "</small>" : "") + "</button>"; }).join("");
    dmenu._acts = acts;
    var x = Math.min(Math.max(12, (dState.at || {}).x || vw() / 2 - 165), vw() - 342), y = Math.min(Math.max(70, (dState.at || {}).y || vh() / 3), vh() - 40 - acts.length * 34 - 70);
    dmenu.style.left = x + "px"; dmenu.style.top = Math.max(70, y) + "px";
    dmenu.classList.add("on");
    var f = dmenu.querySelector("button"); if (f) f.focus();
  }
  function fillCmd(text) {
    if (!cmdEl) return;
    if (getComputedStyle(cmdEl).display === "none") { var b = document.getElementById("moreBtn"); if (b) b.click(); }
    cmdEl.value = text; cmdEl.focus(); cmdEl.setSelectionRange(text.length, text.length);
  }
  dmenu.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-k]"); if (!b) return;
    dmenu.classList.remove("on"); dmenu._acts[+b.dataset.k].fn();
  });
  dmenu.addEventListener("keydown", function (e) {
    e.stopPropagation();
    var bs = Array.prototype.slice.call(dmenu.querySelectorAll("button")), i = bs.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); (bs[i + 1] || bs[0]).focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); (bs[i - 1] || bs[bs.length - 1]).focus(); }
    if (e.key === "Escape") dmenu.classList.remove("on");
  });
  document.addEventListener("pointerdown", function (e) { if (!e.target.closest("#wbDropMenu")) dmenu.classList.remove("on"); }, true);

  // ================================================================ КОМАНДНАЯ ПАЛИТРА (Ctrl+K)
  var pal = document.createElement("div");
  pal.id = "wbPal";
  pal.innerHTML = "<div class='box'><input id='wbPalIn' autocomplete='off' spellcheck='false'><div class='hint'></div><div class='list'></div>" +
    "<div class='foot'><span>↑↓ выбрать · Enter — сделать · Esc — закрыть</span><span class='mode'></span></div></div>";
  app.appendChild(pal);
  css.textContent += [
    "#wbPal { position: absolute; inset: 0; z-index: 50; display: none; background: rgba(6,6,6,.55); }",
    "#wbPal.on { display: block; }",
    "#wbPal .box { position: absolute; left: 50%; top: 14vh; transform: translateX(-50%); width: min(620px, calc(100% - 32px));",
    "  background: rgba(14,14,14,.98); border: 1px solid #333; box-shadow: 0 30px 90px rgba(0,0,0,.7); }",
    "#wbPal input { width: 100%; box-sizing: border-box; padding: 18px 20px; font-size: 18px; border: 0; border-bottom: 1px solid var(--line); }",
    "#wbPal input:focus { border-bottom-color: var(--coral); }",
    "#wbPal .hint { display: none; padding: 8px 20px 0; color: var(--iron); font-size: 12px; } #wbPal .hint.on { display: block; }",
    "#wbPal .list { max-height: min(56vh, 460px); overflow: auto; padding: 6px 0; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }",
    "#wbPal .g { padding: 10px 20px 4px; font-size: 10px; letter-spacing: .16em; text-transform: uppercase; color: var(--iron); }",
    "#wbPal .it { display: flex; align-items: baseline; gap: 12px; padding: 8px 20px; cursor: pointer; color: var(--bone); }",
    "#wbPal .it .t { color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }",
    "#wbPal .it .s { color: var(--iron); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; min-width: 0; }",
    "#wbPal .it kbd { font: inherit; font-size: 11px; color: var(--iron); }",
    "#wbPal .it.sel { background: rgba(255,255,255,.055); box-shadow: inset 2px 0 0 var(--coral); }",
    "#wbPal .it mark { background: none; color: var(--coral); }",
    "#wbPal .foot { display: flex; justify-content: space-between; gap: 12px; padding: 8px 20px; border-top: 1px solid var(--line); color: var(--iron); font-size: 11px; }"
  ].join("\n");
  var palIn = pal.querySelector("input"), palList = pal.querySelector(".list"), palHint = pal.querySelector(".hint"), palMode = pal.querySelector(".mode");
  var P = { items: [], shown: [], sel: 0, mode: "", draft: null, projects: [] };
  function norm(s) { return String(s || "").toLowerCase().replace(/ё/g, "е"); }
  function panelBtn(id) { var b = document.getElementById(id); return b ? function () { closePal(); b.click(); } : null; }
  function winItem(w, kw) {
    return { g: "Окна", t: (w.el.classList.contains("open") ? "Закрыть: " : "Открыть: ") + w.btn.textContent.replace(/\d+$/, ""), kw: kw,
             run: function () { closePal(); setOpen(w, !w.el.classList.contains("open")); } };
  }
  function buildItems() {
    var L = [];
    L.push(winItem(term, "терминал консоль командная строка shell bash cmd"));
    L.push(winItem(files, "файлы папки проводник файловый менеджер"));
    L.push(winItem(proj, "проекты задачи"));
    L.push(winItem(inbox, "входящие уведомления вопросы готово"));
    L.push({ g: "Окна", t: "Закрыть всё лишнее", kw: "закрыть все окна панели", run: function () { closePal(); closeAll(); } });
    var PANELS = [["actionsBtn", "Действия", "action center что делает сделано ошибки безопасный режим"], ["projectsBtn", "Проекты — подробно", "цели решения задачи"],
      ["memoryBtn", "Память", "воспоминания что знает запомни забудь"], ["journalBtn", "Журнал", "история события что делала"],
      ["linksBtn", "Связи", "граф знания"], ["worldBtn", "Мир", "глобус новости рынки землетрясения"], ["connBtn", "Подключения", "сервисы telegram google коннекторы"],
      ["picsBtn", "Картинки", "визуальная память скриншоты"], ["filesBtn", "Изменения файлов", "отмена откатить что меняла"],
      ["phoneBtn", "Телефон", "пульт qr андроид"], ["accessBtn", "Доступ", "права разрешения vault приватные папки запрет"],
      ["statsBtn", "Статистика", "цифры нейроны"], ["wallBtn", "Обои", "заставка весь экран"], ["micBtn", "Микрофон", "слух выключить"], ["soundBtn", "Звук", "громкость звуки"],
      ["moreBtn", document.body.classList.contains("clean") ? "Показать все функции" : "Скрыть лишнее", "чистый вид все функции"],
      ["coreLabel", "Ядро: состояние, модели, расходы", "здоровье модели мозг деньги расход самочувствие"]];
    PANELS.forEach(function (p) {
      var el = document.getElementById(p[0]);
      if (!el || (el.offsetParent === null && ["phoneBtn", "micBtn", "soundBtn"].indexOf(p[0]) >= 0 && !el.closest("#moreMenu"))) return;
      if (p[0] === "phoneBtn" && getComputedStyle(el).display === "none") return;
      L.push({ g: "Разделы", t: p[1], kw: p[2], run: panelBtn(p[0]) });
    });
    var all = layouts();
    Object.keys(all).forEach(function (k) {
      L.push({ g: "Раскладки", t: "Раскладка: " + k, s: all[k].pos ? "сохранённая" : { "Работа": "терминал, файлы, проекты", "Студия": "файлы и входящие", "Тишина": "только мозг" }[k],
               kw: "раскладка вид экран", run: function () { closePal(); applyLayout(k); } });
    });
    L.push({ g: "Раскладки", t: "Сохранить текущую раскладку…", kw: "запомнить раскладка", run: function () { setMode("layout"); } });
    qState.items.forEach(function (b) { L.push({ g: "Быстрые кнопки", t: b.label, s: b.request, kw: "кнопка", run: function () { closePal(); ask(b.request); } }); });
    L.push({ g: "Быстрые кнопки", t: "Новая быстрая кнопка…", kw: "добавить кнопку сценарий", run: function () { setMode("button"); } });
    P.projects.forEach(function (p) {
      L.push({ g: "Проекты", t: p.name.charAt(0).toUpperCase() + p.name.slice(1), s: (p.doing ? p.doing + " в работе · " : "") + p.todo + " сделать",
               kw: "проект", run: function () { closePal(); pState.open = p.name; store("proj", p.name); setOpen(proj, true); } });
    });
    (fState.places || [{ name: "Дом", path: "~" }, { name: "Загрузки", path: "~/Downloads" }, { name: "Документы", path: "~/Documents" }, { name: "Рабочий стол", path: "~/Desktop" }])
      .forEach(function (p) { L.push({ g: "Папки", t: p.name, s: p.path, kw: "папка открыть", run: function () { closePal(); setOpen(files, true); load(p.path); } }); });
    asks.slice(0, 8).forEach(function (t) { L.push({ g: "Недавние просьбы", t: t, kw: "", run: function () { closePal(); ask(t); } }); });
    tState.hist.slice(0, 8).forEach(function (c) {
      L.push({ g: "Недавние команды", t: c, s: "в терминале", kw: "терминал", mono: true, run: function () { closePal(); setOpen(term, true); cmdIn.value = c; cmdIn.focus(); } });
    });
    return L;
  }
  function score(it, q) {
    if (!q) return 1;
    var t = norm(it.t), hay = t + " " + norm(it.s) + " " + norm(it.kw) + " " + norm(it.g), words = q.split(/\s+/).filter(Boolean);
    for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return 0;
    if (t.indexOf(q) === 0) return 4;
    if (t.split(/[\s:—-]+/).some(function (w) { return w.indexOf(words[0]) === 0; })) return 3;
    if (t.indexOf(q) >= 0) return 2;
    return 1;
  }
  function hi(text, q) {
    var t = esc(text); if (!q) return t;
    var i = norm(text).indexOf(q.split(/\s+/)[0]);
    return i < 0 ? t : esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.split(/\s+/)[0].length)) + "</mark>" + esc(text.slice(i + q.split(/\s+/)[0].length));
  }
  function palRender() {
    var raw = palIn.value.trim(), q = norm(raw);
    palHint.classList.toggle("on", !!P.mode);
    if (P.mode === "button") {
      palHint.textContent = P.draft ? "Кнопка «" + P.draft + "». Теперь просьба, которую она передаст Chloe — Enter" : "Новая быстрая кнопка: название — Enter";
      palIn.placeholder = P.draft ? "например: отчёт за неделю — расходы, доходы, что сделано" : "например: Отчёт";
      palList.innerHTML = ""; palMode.textContent = "новая кнопка"; return;
    }
    if (P.mode === "layout") {
      palHint.textContent = "Как назвать раскладку? Запомню, какие окна открыты и где стоят — Enter";
      palIn.placeholder = "например: Монтаж"; palList.innerHTML = ""; palMode.textContent = "раскладка"; return;
    }
    palIn.placeholder = "Что сделать? Окно, раздел, проект, папка — или просьба для Chloe";
    palMode.textContent = "Ctrl+K";
    var shown = P.items.map(function (it) { return { it: it, s: score(it, q) }; }).filter(function (x) { return x.s > 0; });
    if (q) shown.sort(function (a, b) { return b.s - a.s; });
    shown = shown.map(function (x) { return x.it; });
    if (raw) {
      shown.push({ g: "Chloe", t: "Попросить Chloe: «" + raw + "»", kw: "", run: function () { closePal(); ask(raw); } });
      if (/^[a-z0-9_.~\/-]+(\s|$)/i.test(raw)) shown.push({ g: "Chloe", t: "В терминале: " + raw, mono: true, kw: "", run: function () {
        closePal(); setOpen(term, true); cmdIn.value = raw; cmdIn.focus(); } });
    }
    if (q) shown = shown.slice(0, 40);
    P.shown = shown; P.sel = Math.min(P.sel, Math.max(0, shown.length - 1));
    var h = [], g = "";
    shown.forEach(function (it, k) {
      if (!q && it.g !== g) { g = it.g; h.push("<div class='g'>" + esc(g) + "</div>"); }
      h.push("<div class='it" + (k === P.sel ? " sel" : "") + "' data-k='" + k + "'><span class='t'" + (it.mono ? " style='font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px'" : "") + ">" +
        hi(it.t, q) + "</span><span class='s'>" + esc(it.s || "") + "</span>" + (q ? "<kbd>" + esc(it.g) + "</kbd>" : "") + "</div>");
    });
    palList.innerHTML = h.join("");
    var sel = palList.querySelector(".sel"); if (sel) sel.scrollIntoView({ block: "nearest" });
  }
  function setMode(m) { P.mode = m; P.draft = null; palIn.value = ""; palRender(); palIn.focus(); }
  function openPalette(mode) {
    P.items = buildItems(); P.sel = 0; P.mode = mode || ""; P.draft = null; palIn.value = "";
    pal.classList.add("on"); palRender(); setTimeout(function () { palIn.focus(); }, 10);
    var a = api();
    if (a && a.projects_list) a.projects_list().then(function (l) { P.projects = l || []; if (pal.classList.contains("on") && !P.mode) { P.items = buildItems(); palRender(); } });
  }
  function closePal() { pal.classList.remove("on"); P.mode = ""; }
  palIn.addEventListener("input", function () { P.sel = 0; palRender(); });
  palIn.addEventListener("keydown", function (e) {
    e.stopPropagation();
    if (e.key === "Escape") { if (P.mode) { setMode(""); } else closePal(); return; }
    if (P.mode) {
      if (e.key !== "Enter" || !palIn.value.trim()) return;
      var v = palIn.value.trim();
      if (P.mode === "layout") { saveLayout(v); closePal(); return; }
      if (!P.draft) { P.draft = v.slice(0, 40); palIn.value = ""; palRender(); return; }
      qSave(qState.items.filter(function (b) { return b.label.toLowerCase() !== P.draft.toLowerCase(); }).concat([{ label: P.draft, request: v }]));
      toast("Кнопка «" + P.draft + "» готова"); closePal(); return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); var n = P.shown.length; if (!n) return;
      P.sel = (P.sel + (e.key === "ArrowDown" ? 1 : -1) + n) % n; palRender(); return;
    }
    if (e.key === "Enter") { var it = P.shown[P.sel]; if (it && it.run) it.run(); }
  });
  palList.addEventListener("mousemove", function (e) { var r = e.target.closest(".it"); if (r && +r.dataset.k !== P.sel) { P.sel = +r.dataset.k; palRender(); } });
  palList.addEventListener("click", function (e) { var r = e.target.closest(".it"); if (r) { var it = P.shown[+r.dataset.k]; if (it && it.run) it.run(); } });
  pal.addEventListener("pointerdown", function (e) { e.stopPropagation(); if (e.target === pal) closePal(); });
  addEventListener("keydown", function (e) {
    var k = (e.key || "").toLowerCase();
    if ((e.ctrlKey || e.metaKey) && (k === "k" || k === "л" || e.code === "KeyK")) { e.preventDefault(); pal.classList.contains("on") ? closePal() : openPalette(); }
  });
  var findBtn = document.createElement("button");
  findBtn.type = "button"; findBtn.className = "find"; findBtn.title = "Найти функцию, окно, проект, папку (Ctrl+K)";
  findBtn.innerHTML = "Найти<kbd>Ctrl K</kbd>";
  findBtn.onclick = function () { openPalette(); };
  dock.insertBefore(findBtn, dock.firstChild);

  // ================================================================ ОКНО ГОЛОСОМ: Python → chloeUI
  var WIN_BY = { terminal: term, files: files, projects: proj, inbox: inbox };
  window.chloeUI = function (o) {
    o = o || {};
    if (o.action === "buttons") { qState.items = o.items || []; qRender(); return; }
    if (o.action === "close_all") { closeAll(); closePal(); return; }
    if (o.action === "layout") { applyLayout(o.name); return; }
    if (o.action === "save_layout") { saveLayout(o.name); return; }
    if (o.window === "palette") { o.action === "close" ? closePal() : openPalette(); return; }
    var w = WIN_BY[o.window]; if (!w) return;
    var on = o.action === "open" ? true : o.action === "close" ? false : !w.el.classList.contains("open");
    setOpen(w, on);
    if (on && o.window === "files" && o.path) load(o.path);
  };
  window.chloeLayouts = { apply: applyLayout, save: saveLayout, remove: deleteLayout, list: layouts };
  qLoad();
  if (!api() && params.has("app")) addEventListener("pywebviewready", function () { qLoad(); inLoad(); });
  else setTimeout(inLoad, 1500);

  // открыть то, что было открыто в прошлый раз — когда программа Chloe готова (или сразу в браузере)
  function restore() { Object.keys(wins).forEach(function (k) { wins[k].restore(); }); }
  if (api() || !params.has("app")) setTimeout(restore, 300);
  else addEventListener("pywebviewready", function () { setTimeout(restore, 100); });
})();
