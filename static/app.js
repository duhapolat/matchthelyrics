import WaveSurfer from "./vendor/wavesurfer.esm.js";
import RegionsPlugin from "./vendor/regions.esm.js";
import TimelinePlugin from "./vendor/timeline.esm.js";
import { LANGS, esc, fmt, nextLang, parseLyrics, parseTime } from "./util.js";

const LANG_NAMES = { de: "Almanca", tr: "Türkçe", en: "İngilizce" };
const SEPARATION = { htdemucs: "Hızlı (htdemucs)", htdemucs_ft: "Yüksek kalite (htdemucs_ft · ~4× yavaş)" };
const sepSelect = (sel = "htdemucs") => `<label class="field"><span>Vokal ayırma</span><select id="separation">${Object.entries(SEPARATION)
  .map(([k, v]) => `<option value="${k}"${k === sel ? " selected" : ""}>${v}</option>`).join("")}</select></label>`;
const view = document.getElementById("view");
let cleanup = () => {};

// ---------------------------------------------------------------- yardımcılar

async function api(path, opts = {}) {
  const res = await fetch(path, { cache: "no-store", ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

function toast(msg, ms = 2200) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), ms);
}

// ---------------------------------------------------------------- yönlendirme

const routes = [
  [/^#\/?$/, listPage, "list"],
  [/^#\/new$/, newPage, "new"],
  [/^#\/import$/, importPage, "import"],
  [/^#\/learning$/, learningPage, "learning"],
  [/^#\/p\/(\w+)$/, projectPage, null],
];

function route() {
  cleanup();
  cleanup = () => {};
  const hash = location.hash || "#/";
  for (const [re, fn, nav] of routes) {
    const m = hash.match(re);
    if (m) {
      document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
      fn(...m.slice(1));
      return;
    }
  }
  location.hash = "#/";
}
window.addEventListener("hashchange", route);
route();

// ---------------------------------------------------------------- proje listesi

async function listPage() {
  view.innerHTML = `<h1>Projeler</h1><p class="muted">Yüklediğin şarkılar. Kaydedilenler öğrenme verisine katılır.</p><div class="card" id="plist">Yükleniyor…</div>`;
  const projects = await api("/api/projects");
  const el = document.getElementById("plist");
  if (!projects.length) {
    el.innerHTML = `Henüz proje yok. <a href="#/new">İlk şarkını ekle →</a>`;
    return;
  }
  el.innerHTML = `<table class="list"><tr><th>Şarkı</th><th>Eklendi</th><th>Durum</th><th></th></tr>${projects
    .map((p) => {
      const st = p.status === "ready"
        ? (p.saved ? `<span class="badge ok">${p.imported ? "İçe aktarıldı" : "Kaydedildi"}</span>` : `<span class="badge">Düzenlenmedi</span>`)
        : p.status === "error" ? `<span class="badge err">Hata</span>` : `<span class="badge">${esc(p.progress || "İşleniyor")}</span>`;
      return `<tr><td><a href="#/p/${p.id}">${esc(p.title)}</a></td><td class="muted">${esc(p.created)}</td><td>${st}</td>
        <td style="text-align:right"><button class="danger icon" data-del="${p.id}" title="Sil">✕</button></td></tr>`;
    })
    .join("")}</table>`;
  el.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("Bu proje ve öğrenme verisindeki katkısı silinsin mi?")) return;
      await api(`/api/projects/${b.dataset.del}`, { method: "DELETE" });
      listPage();
    })
  );
}

// ---------------------------------------------------------------- yeni şarkı

function newPage() {
  let defLang = "de";
  let lines = [];
  view.innerHTML = `
  <h1>Yeni şarkı</h1>
  <p class="muted">Ses dosyasını seç, sözleri yapıştır, her satırın dilini işaretle.</p>
  <div class="grid2">
    <div class="card stack">
      <label class="field"><span>Ses dosyası</span><input type="file" id="audio" accept="audio/*,.mp3,.wav,.flac,.m4a"></label>
      <label class="field"><span>Başlık</span><input type="text" id="title" placeholder="Sanatçı - Şarkı"></label>
      <div><b>Varsayılan dil</b><br><div class="seg" id="deflang">${LANGS.map((l) => `<button data-l="${l}">${LANG_NAMES[l]}</button>`).join("")}</div></div>
      ${sepSelect()}
      <label class="field"><span>Sözler (her satır = bir altyazı)</span>
        <textarea id="lyrics" placeholder="Her satıra bir söz satırı yaz.&#10;&#10;Dil değiştirmek için satır başına [tr], [de] veya [en] yazabilirsin.&#10;Tek başına [tr] satırı, sonraki tüm satırları Türkçe yapar."></textarea></label>
    </div>
    <div class="card stack">
      <div class="row"><b class="grow">Satırlar ve diller</b>
        <span class="muted" id="count"></span></div>
      <div class="row">${LANGS.map((l) => `<button data-all="${l}">Hepsi ${l.toUpperCase()}</button>`).join("")}</div>
      <p class="muted" style="margin:0">Dil etiketine tıklayarak değiştir.</p>
      <div class="preview" id="preview"></div>
      <button class="primary" id="go" disabled>Hizala →</button>
    </div>
  </div>`;
  const $ = (id) => document.getElementById(id);
  const renderSeg = () => $("deflang").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.l === defLang));
  const render = () => {
    $("preview").innerHTML = lines.map((l, i) => `<div><button class="chip ${l.lang}" data-i="${i}">${l.lang}</button><span>${esc(l.text)}</span></div>`).join("");
    $("count").textContent = `${lines.length} satır`;
    $("go").disabled = !lines.length || !$("audio").files.length;
  };
  const reparse = () => { lines = parseLyrics($("lyrics").value, defLang); render(); };
  $("deflang").addEventListener("click", (e) => { if (e.target.dataset.l) { defLang = e.target.dataset.l; renderSeg(); reparse(); } });
  $("lyrics").addEventListener("input", reparse);
  $("preview").addEventListener("click", (e) => {
    const i = e.target.dataset.i;
    if (i !== undefined) { lines[i].lang = nextLang(lines[i].lang); render(); }
  });
  view.querySelectorAll("[data-all]").forEach((b) => b.addEventListener("click", () => { lines.forEach((l) => (l.lang = b.dataset.all)); render(); }));
  $("audio").addEventListener("change", () => {
    const f = $("audio").files[0];
    if (f && !$("title").value) $("title").value = f.name.replace(/\.[^.]+$/, "");
    render();
  });
  $("go").addEventListener("click", async () => {
    $("go").disabled = true;
    $("go").textContent = "Yükleniyor…";
    const fd = new FormData();
    fd.append("audio", $("audio").files[0]);
    fd.append("title", $("title").value);
    fd.append("lines", JSON.stringify(lines));
    fd.append("separation", $("separation").value);
    try {
      const p = await api("/api/projects", { method: "POST", body: fd });
      location.hash = `#/p/${p.id}`;
    } catch (err) {
      toast("Hata: " + err.message, 5000);
      $("go").disabled = false;
      $("go").textContent = "Hizala →";
    }
  });
  renderSeg();
  render();
}

// ---------------------------------------------------------------- SRT içe aktar

function importPage() {
  view.innerHTML = `
  <h1>Düzeltilmiş SRT içe aktar</h1>
  <p class="muted">Daha önce elle düzelttiğin SRT dosyalarını ve şarkılarını buradan ekleyebilirsin.
  Sistem şarkıyı kendisi hizalar, senin SRT'ndeki zamanlarla karşılaştırır ve farkı öğrenir.</p>
  <div class="card stack" style="max-width:560px">
    <label class="field"><span>Ses dosyası</span><input type="file" id="audio" accept="audio/*,.mp3,.wav,.flac,.m4a"></label>
    <label class="field"><span>Düzeltilmiş .srt</span><input type="file" id="srt" accept=".srt"></label>
    <label class="field"><span>Şarkının ana dili</span><select id="lang">${LANGS.map((l) => `<option value="${l}">${LANG_NAMES[l]}</option>`).join("")}</select></label>
    ${sepSelect()}
    <p class="muted" style="margin:0">Karışık dilli şarkılarda içe aktardıktan sonra editörde satır dillerini düzeltip kaydedebilirsin.</p>
    <button class="primary" id="go">İçe aktar</button>
  </div>`;
  document.getElementById("go").addEventListener("click", async (e) => {
    const a = document.getElementById("audio").files[0];
    const s = document.getElementById("srt").files[0];
    if (!a || !s) return toast("Ses ve SRT dosyası seç.");
    e.target.disabled = true;
    const fd = new FormData();
    fd.append("audio", a);
    fd.append("srt_file", s);
    fd.append("lang", document.getElementById("lang").value);
    fd.append("title", a.name.replace(/\.[^.]+$/, ""));
    try {
      const p = await api("/api/import", { method: "POST", body: fd });
      location.hash = `#/p/${p.id}`;
    } catch (err) {
      toast("Hata: " + err.message, 5000);
      e.target.disabled = false;
    }
  });
}

// ---------------------------------------------------------------- editör

async function projectPage(pid) {
  let alive = true;
  cleanup = () => { alive = false; };
  view.innerHTML = `<div class="card status-box"><div class="spinner"></div><div id="st">Yükleniyor…</div></div>`;
  let p;
  while (alive) {
    p = await api(`/api/projects/${pid}`);
    if (p.status === "ready" || p.status === "error") break;
    const st = document.getElementById("st");
    if (st) st.innerHTML = `${esc(p.progress || "İşleniyor…")}<br><span class="muted">İlk çalıştırmada modeller indirilir, birkaç dakika sürebilir.</span>`;
    await new Promise((r) => setTimeout(r, 1500));
  }
  if (!alive) return;
  if (p.status === "error") {
    view.innerHTML = `<div class="card"><h1>${esc(p.title)}</h1><p class="badge err">Hata</p><pre>${esc(p.error)}</pre></div>`;
    return;
  }
  editor(p);
}

function editor(p) {
  let lines = p.lines.map((l) => ({ ...l }));
  let sel = 0;
  let dirty = false;
  let textDirty = false;
  let source = "original";
  let stopAt = null;
  const regions = RegionsPlugin.create();
  const AUTO_ANCHOR_SEC = 1.0;

  view.innerHTML = `
  <div class="editor-head">
    <h1 class="grow">${esc(p.title)}</h1>
    <button id="suspects" class="warn" hidden title="Hizalayıcının emin olmadığı satırlar (N / Shift+N)"></button>
    <button id="realign" title="Çapalı satırlar yerinde kalır, diğerleri yeniden hizalanır">↻ Yeniden hizala</button>
    <button id="hq" ${p.separation === "htdemucs_ft" ? "hidden" : ""} title="Vokali yüksek kalite modelle (htdemucs_ft) yeniden ayır ve hizala">Yüksek kalite vokal</button>
    <button id="repropose" title="Ham hizalamaya güncel öğrenmeyi uygula">Öğrenmeyi yeniden uygula</button>
    <button id="save">Kaydet</button>
    <span class="split">
      <select id="fmt" title="Çıktı biçimi">
        <option value="srt">.srt</option>
        <option value="lrc">.lrc (satır)</option>
        <option value="lrc-words">.lrc (kelime kelime)</option>
        <option value="ass">.ass karaoke</option>
      </select>
      <button class="primary" id="download">Kaydet ve indir</button>
    </span>
  </div>
  <div class="wave-wrap">
    <div id="waveform"></div>
    <div class="transport">
      <button id="play" class="primary">▶ Oynat</button>
      <span class="time" id="time">0:00.000</span>
      <div class="seg" id="src"><button data-s="original" class="on">Orijinal</button><button data-s="vocals">Sadece vokal</button></div>
      <label class="row" style="gap:6px">Yakınlaştır <input type="range" id="zoom" min="10" max="400" value="60"></label>
      <label class="row" style="gap:6px">Hız <select id="rate" style="width:auto"><option>0.5</option><option>0.75</option><option selected>1</option></select></label>
    </div>
    <div class="keys">
      <kbd>Boşluk</kbd> oynat/durdur · <kbd>Enter</kbd> seçili satırı çal · <kbd>↑</kbd><kbd>↓</kbd> satır seç ·
      <kbd>Q</kbd> başlangıcı imlece al · <kbd>W</kbd> bitişi imlece al ·
      <kbd>Z</kbd>/<kbd>X</kbd> başlangıç ∓50ms · <kbd>C</kbd>/<kbd>V</kbd> bitiş ∓50ms (<kbd>Shift</kbd> ile 10ms) ·
      <kbd>N</kbd> sonraki şüpheli satır · <kbd>A</kbd> çapa
    </div>
  </div>
  <div class="lines" id="lines"></div>`;
  const $ = (id) => document.getElementById(id);

  const ws = WaveSurfer.create({
    container: "#waveform",
    height: 120,
    waveColor: getComputedStyle(document.documentElement).getPropertyValue("--wave").trim(),
    progressColor: getComputedStyle(document.documentElement).getPropertyValue("--wave-progress").trim(),
    cursorColor: "#e33",
    minPxPerSec: 60,
    autoScroll: true,
    autoCenter: false,
    url: `/api/projects/${p.id}/audio/original`,
    plugins: [regions, TimelinePlugin.create({ height: 16 })],
  });

  const color = (lang, on) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(`--lang-${lang}`).trim();
    return `rgba(${v}, ${on ? 0.45 : 0.2})`;
  };
  const regionOf = new Map();

  /** Hizalayıcı emin değil ve kullanıcı henüz bu satıra dokunmadı. */
  const isSuspect = (l) => !!l.suspect && !l.anchor && !!l.proposed && l.start === l.proposed.start && l.end === l.proposed.end;
  const label = (l, i) => `${l.anchor ? "⚓ " : isSuspect(l) ? "⚠ " : ""}${i + 1}. ${l.text}`;

  function drawRegions() {
    regions.clearRegions();
    regionOf.clear();
    lines.forEach((l, i) => {
      const r = regions.addRegion({ start: l.start, end: l.end, color: color(l.lang, i === sel), content: label(l, i), drag: true, resize: true, minLength: 0.1 });
      r._idx = i;
      regionOf.set(i, r);
    });
  }

  function rowHtml(l, i) {
    const cls = ["line", i === sel && "sel", isSuspect(l) && "suspect", l.anchor && "anchored"].filter(Boolean).join(" ");
    return `<div class="${cls}" data-i="${i}">
      <span class="n" title="${isSuspect(l) ? "Hizalayıcı bu satırdan emin değil, kontrol et" : ""}">${isSuspect(l) ? "⚠" : i + 1}</span>
      <button class="chip ${l.lang}" data-act="lang" title="Dil">${l.lang}</button>
      <input class="t" type="text" value="${esc(l.text)}" data-act="text">
      <span class="tbox"><button data-act="s-">‹</button><input data-act="start" value="${fmt(l.start)}"><button data-act="s+">›</button></span>
      <span class="tbox"><button data-act="e-">‹</button><input data-act="end" value="${fmt(l.end)}"><button data-act="e+">›</button></span>
      <button class="icon anchor${l.anchor ? " on" : ""}" data-act="anchor" title="Çapa: bu satır doğru yerde, yeniden hizalamada kıpırdamasın (A)">⚓</button>
      <button class="icon" data-act="play" title="Çal">▶</button>
      <button class="icon" data-act="add" title="Altına satır ekle">＋</button>
      <button class="icon danger" data-act="del" title="Sil">✕</button>
    </div>`;
  }
  function renderLines() { $("lines").innerHTML = lines.map(rowHtml).join(""); updateBadges(); }

  /** Bir satırın görünümünü (satır listesi + dalga formu bloğu) durumuna göre tazeler. */
  function refreshRow(i) {
    const row = $("lines").querySelector(`[data-i="${i}"]`);
    const l = lines[i];
    if (row) {
      row.querySelector('[data-act="start"]').value = fmt(l.start);
      row.querySelector('[data-act="end"]').value = fmt(l.end);
      row.classList.toggle("suspect", isSuspect(l));
      row.classList.toggle("anchored", !!l.anchor);
      row.querySelector('[data-act="anchor"]').classList.toggle("on", !!l.anchor);
      const n = row.querySelector(".n");
      n.textContent = isSuspect(l) ? "⚠" : i + 1;
      n.title = isSuspect(l) ? "Hizalayıcı bu satırdan emin değil, kontrol et" : "";
    }
    regionOf.get(i)?.setOptions({ content: label(l, i) });
    updateBadges();
  }

  function updateBadges() {
    const n = lines.filter(isSuspect).length;
    $("suspects").hidden = n === 0;
    $("suspects").textContent = `⚠ ${n} şüpheli satır`;
    const a = lines.filter((l) => l.anchor).length;
    $("realign").textContent = a ? `↻ Çapalara göre hizala (⚓ ${a})` : "↻ Yeniden hizala";
  }

  function select(i, scroll = true) {
    if (i < 0 || i >= lines.length) return;
    const old = sel;
    sel = i;
    if (lines[old]) regionOf.get(old)?.setOptions({ color: color(lines[old].lang, false) });
    regionOf.get(i)?.setOptions({ color: color(lines[i].lang, true) });
    $("lines").querySelectorAll(".line").forEach((r) => r.classList.toggle("sel", +r.dataset.i === i));
    if (scroll) $("lines").querySelector(`[data-i="${i}"]`)?.scrollIntoView({ block: "nearest" });
  }

  function jumpSuspect(dir) {
    const n = lines.length;
    for (let k = 1; k <= n; k++) {
      const i = (sel + dir * k + n) % n;
      if (isSuspect(lines[i])) {
        select(i);
        ws.setTime(Math.max(0, lines[i].start - 0.5));
        return;
      }
    }
    toast("Şüpheli satır kalmadı");
  }

  function setAnchor(i, on) {
    lines[i].anchor = on;
    refreshRow(i);
    markDirty();
  }

  /** Önerilen yerden çok uzağa taşınan satır büyük olasılıkla yanlış yerdeydi: otomatik çapala. */
  function maybeAutoAnchor(i) {
    const l = lines[i];
    if (l.anchor || !l.proposed) return;
    if (Math.abs(l.start - l.proposed.start) > AUTO_ANCHOR_SEC || Math.abs(l.end - l.proposed.end) > AUTO_ANCHOR_SEC) {
      setAnchor(i, true);
      toast(`${i + 1}. satır çapalandı · diğerlerini buna göre yerleştirmek için "Çapalara göre hizala"`, 4000);
    }
  }

  function setTimes(i, start, end) {
    const l = lines[i];
    start = Math.max(0, start);
    end = Math.max(start + 0.05, end);
    l.start = +start.toFixed(3);
    l.end = +end.toFixed(3);
    regionOf.get(i)?.setOptions({ start: l.start, end: l.end });
    refreshRow(i);
    maybeAutoAnchor(i);
    markDirty();
  }

  /** Başlangıcı değiştirir; bitişi geçerse satır süresini koruyarak bütünüyle kayar. */
  function moveStart(i, start) {
    const l = lines[i];
    setTimes(i, start, start >= l.end ? start + (l.end - l.start) : l.end);
  }

  function markDirty() { dirty = true; $("save").textContent = "Kaydet •"; }
  function markText() { textDirty = true; markDirty(); }

  function playLine(i) {
    const l = lines[i];
    stopAt = l.end;
    ws.setTime(Math.max(0, l.start - 0.3));
    ws.play();
  }

  // dalga formu olayları
  ws.on("ready", () => { drawRegions(); renderLines(); select(0, false); });
  ws.on("timeupdate", (t) => {
    $("time").textContent = fmt(t);
    if (stopAt !== null && t >= stopAt + 0.15) { ws.pause(); stopAt = null; }
    const cur = lines.findIndex((l) => t >= l.start && t <= l.end);
    $("lines").querySelectorAll(".line").forEach((r) => r.classList.toggle("playing", +r.dataset.i === cur));
  });
  ws.on("play", () => ($("play").textContent = "❚❚ Durdur"));
  ws.on("pause", () => ($("play").textContent = "▶ Oynat"));
  ws.on("interaction", () => { stopAt = null; });
  regions.on("region-updated", (r) => {
    const i = r._idx;
    lines[i].start = +r.start.toFixed(3);
    lines[i].end = +r.end.toFixed(3);
    refreshRow(i);
    maybeAutoAnchor(i);
    select(i);
    markDirty();
  });
  regions.on("region-clicked", (r, e) => { e.stopPropagation(); select(r._idx); });
  regions.on("region-double-clicked", (r, e) => { e.stopPropagation(); playLine(r._idx); });

  // satır listesi olayları
  $("lines").addEventListener("click", (e) => {
    const row = e.target.closest(".line");
    if (!row) return;
    const i = +row.dataset.i;
    const act = e.target.dataset.act;
    if (act !== "text" && act !== "start" && act !== "end") select(i, false);
    else if (sel !== i) select(i, false);
    const l = lines[i];
    const step = e.shiftKey ? 0.01 : 0.05;
    if (act === "lang") { l.lang = nextLang(l.lang); e.target.className = `chip ${l.lang}`; e.target.textContent = l.lang; regionOf.get(i)?.setOptions({ color: color(l.lang, true) }); markText(); }
    else if (act === "s-") setTimes(i, l.start - step, l.end);
    else if (act === "s+") setTimes(i, l.start + step, l.end);
    else if (act === "e-") setTimes(i, l.start, l.end - step);
    else if (act === "e+") setTimes(i, l.start, l.end + step);
    else if (act === "anchor") setAnchor(i, !l.anchor);
    else if (act === "play") playLine(i);
    else if (act === "add") {
      const next = lines[i + 1];
      const s = l.end + 0.05;
      lines.splice(i + 1, 0, { id: null, text: "", lang: l.lang, start: s, end: next ? Math.max(s + 0.5, next.start - 0.05) : s + 2 });
      drawRegions(); renderLines(); select(i + 1); markText();
      $("lines").querySelector(`[data-i="${i + 1}"] input.t`)?.focus();
    } else if (act === "del") {
      if (!confirm(`${i + 1}. satır silinsin mi?`)) return;
      lines.splice(i, 1);
      sel = Math.min(sel, lines.length - 1);
      drawRegions(); renderLines(); select(sel, false); markText();
    }
  });
  $("lines").addEventListener("change", (e) => {
    const row = e.target.closest(".line");
    if (!row) return;
    const i = +row.dataset.i;
    const act = e.target.dataset.act;
    if (act === "text") {
      lines[i].text = e.target.value;
      refreshRow(i);
      markText();
    } else if (act === "start" || act === "end") {
      const v = parseTime(e.target.value);
      if (isNaN(v)) return refreshRow(i);
      act === "start" ? moveStart(i, v) : setTimes(i, lines[i].start, v);
    }
  });

  // klavye
  const onKey = (e) => {
    if (e.target.matches?.("input, textarea, select")) {
      if (e.key === "Enter") e.target.blur();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const l = lines[sel];
    const step = e.shiftKey ? 0.01 : 0.05;
    const k = e.key.toLowerCase();
    const t = ws.getCurrentTime();
    let handled = true;
    if (e.key === " ") { stopAt = null; ws.playPause(); }
    else if (e.key === "Enter") playLine(sel);
    else if (e.key === "ArrowDown") select(sel + 1);
    else if (e.key === "ArrowUp") select(sel - 1);
    else if (k === "n") jumpSuspect(e.shiftKey ? -1 : 1);
    else if (!l) handled = false;
    else if (k === "a") setAnchor(sel, !l.anchor);
    else if (k === "q") moveStart(sel, t);
    else if (k === "w") setTimes(sel, Math.min(l.start, t - 0.2), t);
    else if (k === "z") setTimes(sel, l.start - step, l.end);
    else if (k === "x") setTimes(sel, l.start + step, l.end);
    else if (k === "c") setTimes(sel, l.start, l.end - step);
    else if (k === "v") setTimes(sel, l.start, l.end + step);
    else handled = false;
    if (handled) e.preventDefault();
  };
  document.addEventListener("keydown", onKey);
  const onLeave = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
  window.addEventListener("beforeunload", onLeave);
  cleanup = () => {
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("beforeunload", onLeave);
    ws.destroy();
  };

  // kontroller
  $("play").addEventListener("click", () => { stopAt = null; ws.playPause(); });
  $("zoom").addEventListener("input", (e) => ws.zoom(+e.target.value));
  $("rate").addEventListener("change", (e) => ws.setPlaybackRate(+e.target.value));
  $("suspects").addEventListener("click", () => jumpSuspect(1));
  $("src").addEventListener("click", async (e) => {
    const s = e.target.dataset.s;
    if (!s || s === source) return;
    source = s;
    $("src").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.s === s));
    const t = ws.getCurrentTime();
    const playing = ws.isPlaying();
    await ws.load(`/api/projects/${p.id}/audio/${s}`);
    ws.setTime(t);
    if (playing) ws.play();
  });

  const linesPayload = () => lines.map(({ id, text, lang, start, end, anchor }) => ({ id, text, lang, start, end, anchor: !!anchor }));

  async function save() {
    if (textDirty && !confirm("Söz metni değişti. Zamanları kaydetmek için devam edilsin mi? (Yeniden hizalamak istersen İptal'e bas ve ↻ Yeniden hizala'yı kullan.)")) return false;
    const r = await api(`/api/projects/${p.id}/lines`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lines: linesPayload() }) });
    dirty = false;
    $("save").textContent = "Kaydet";
    const h = r.history?.at(-1);
    toast(h ? `Kaydedildi · bu şarkıda ortalama düzeltme: başlangıç ${h.mae_start_ms} ms, bitiş ${h.mae_end_ms} ms` : "Kaydedildi", 4000);
    return true;
  }

  async function realign(separation) {
    try {
      await api(`/api/projects/${p.id}/realign`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lines: linesPayload(), separation }),
      });
    } catch (err) {
      toast("Hata: " + err.message, 6000);
      return;
    }
    dirty = false;
    route();
  }

  $("save").addEventListener("click", save);
  $("download").addEventListener("click", async () => {
    if (!(await save())) return;
    location.href = `/api/projects/${p.id}/export/${$("fmt").value}`;
  });
  $("repropose").addEventListener("click", async () => {
    if (!confirm("Tüm satırlar ham hizalama + güncel öğrenilmiş düzeltmelerle yeniden önerilecek. Senin elle yaptığın değişiklikler silinir. Devam?")) return;
    const np = await api(`/api/projects/${p.id}/repropose`, { method: "POST" });
    lines = np.lines.map((l) => ({ ...l }));
    dirty = false;
    drawRegions(); renderLines(); select(0);
    toast("Yeniden önerildi");
  });
  $("realign").addEventListener("click", () => {
    const a = lines.filter((l) => l.anchor).length;
    const msg = a
      ? `${a} çapalı satır yerinde kalacak; diğer satırlar çapaların arasına yeniden hizalanacak (onlardaki elle düzeltmeler sıfırlanır). Devam?`
      : "Satırlar güncel metne göre yeniden hizalanacak, zaman düzeltmeleri sıfırlanır. İpucu: doğru yerdeki satırları ⚓ ile çapalarsan onlar korunur. Devam?";
    if (confirm(msg)) realign(null);
  });
  $("hq").addEventListener("click", () => {
    if (confirm("Vokal yüksek kalite modelle (htdemucs_ft) yeniden ayrılacak ve satırlar yeniden hizalanacak. Çapalı satırlar korunur. Yaklaşık 4 kat uzun sürer; ilk kullanımda ~320 MB model iner. Devam?")) realign("htdemucs_ft");
  });
}

// ---------------------------------------------------------------- öğrenme

async function learningPage() {
  view.innerHTML = `<h1>Öğrenme</h1><div id="lp">Yükleniyor…</div>`;
  const d = await api("/api/learning");
  const s = d.state;
  const hist = d.history;
  const level = !s ? "Henüz veri yok" : s.use_model ? "Seviye B · Sınır modeli aktif" : "Seviye A · Dil başına sapma";
  const nextB = s && !s.use_model
    ? s.n_samples < d.min_samples_model || s.n_songs < d.min_songs_model
      ? `Seviye B için en az ${d.min_songs_model} şarkı ve ${d.min_samples_model} satır gerekiyor (şu an ${s.n_songs} şarkı, ${s.n_samples} satır).`
      : `Seviye B modeli denendi ama henüz Seviye A'dan daha iyi değil; veri arttıkça tekrar denenir.`
    : "";
  const biasRows = s ? LANGS.map((l) => {
    const b = s.bias[l];
    const f = (v) => `${v >= 0 ? "+" : ""}${Math.round(v * 1000)} ms`;
    return `<tr><td><span class="chip ${l}">${l}</span> ${LANG_NAMES[l]}</td><td>${b.n}</td><td>${b.n ? f(b.start) : "–"}</td><td>${b.n ? f(b.end) : "–"}</td></tr>`;
  }).join("") : "";

  document.getElementById("lp").innerHTML = `
  <div class="card stack">
    <b>Nasıl çalışıyor?</b>
    <div class="muted">Her "Kaydet" dediğinde, sistemin ilk önerdiği zamanlar ile senin son hâlin arasındaki fark bir ders olarak saklanır ve model hemen yeniden eğitilir.
    <b>Seviye A:</b> dil başına ortalama kayma (ör. "Almanca satırların bitişini hep 200 ms uzatıyorsun"). Birkaç şarkıdan sonra devreye girer.
    <b>Seviye B:</b> sınırın etrafındaki ses enerjisine, nefes aralarına, uzatılan son heceye bakarak satır satır düzeltme tahmin eden bir model. Yeterli veri olunca eğitilir ve sadece gerçekten daha iyiyse kullanılır.
    3 saniyeden büyük düzeltmeler "satır tamamen yanlış yerdeydi" sayılır ve öğrenmeyi bozmasın diye dışarıda bırakılır.</div>
  </div>
  <h2>Durum</h2>
  <div class="stats">
    <div class="stat"><b>${s ? s.n_songs : 0}</b><span>kaydedilmiş şarkı</span></div>
    <div class="stat"><b>${s ? s.n_samples : 0}</b><span>öğrenme örneği (satır)</span></div>
    <div class="stat"><b>${s ? s.n_outliers : 0}</b><span>dışarıda bırakılan büyük düzeltme</span></div>
    <div class="stat"><b style="font-size:15px">${level}</b><span>${s ? "son eğitim: " + esc(s.trained_at) : ""}</span></div>
  </div>
  ${nextB ? `<p class="muted">${nextB}</p>` : ""}
  ${s?.cv ? `<h2>Doğrulama (görülmemiş şarkılarda ortalama hata)</h2>
    <div class="stats"><div class="stat"><b>${s.cv.raw} ms</b><span>öğrenme olmadan</span></div>
    <div class="stat"><b>${s.cv.bias} ms</b><span>Seviye A</span></div><div class="stat"><b>${s.cv.model} ms</b><span>Seviye B</span></div></div>` : ""}
  <h2>Dil başına öğrenilen kayma</h2>
  <div class="card"><table class="list"><tr><th>Dil</th><th>Örnek</th><th>Başlangıç</th><th>Bitiş</th></tr>${biasRows || `<tr><td colspan="4" class="muted">Henüz kaydedilmiş şarkı yok.</td></tr>`}</table></div>
  <h2>Gelişim: şarkı başına yapman gereken ortalama düzeltme</h2>
  <div class="card">${hist.length ? chart(hist) : `<span class="muted">Şarkı kaydettikçe burada düzeltme miktarının azalmasını göreceksin.</span>`}</div>
  <p><button id="retrain">Şimdi yeniden eğit</button></p>`;
  document.getElementById("retrain").addEventListener("click", async () => {
    await api("/api/learning/retrain", { method: "POST" });
    toast("Yeniden eğitildi");
    learningPage();
  });
}

function chart(hist) {
  const W = 800, H = 180, pad = 30;
  const vals = hist.map((h) => (h.mae_start_ms + h.mae_end_ms) / 2);
  const max = Math.max(...vals, 100);
  const bw = Math.min(40, (W - pad * 2) / vals.length - 4);
  const bars = vals.map((v, i) => {
    const x = pad + i * ((W - pad * 2) / vals.length);
    const h = (v / max) * (H - pad * 2);
    return `<rect class="bar" x="${x}" y="${H - pad - h}" width="${bw}" height="${h}" rx="2"><title>${esc(hist[i].title)}: ${Math.round(v)} ms</title></rect>
      <text x="${x + bw / 2}" y="${H - pad - h - 4}" text-anchor="middle">${Math.round(v)}</text>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}"/>${bars}
    <text x="${pad}" y="${H - 8}">ilk şarkı</text><text x="${W - pad}" y="${H - 8}" text-anchor="end">son şarkı (ms)</text></svg>`;
}
