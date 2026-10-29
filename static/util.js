// Arayüzün DOM'dan bağımsız yardımcıları (Node ile test edilir: tests/js).

export const LANGS = ["de", "tr", "en"];

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const nextLang = (l) => LANGS[(LANGS.indexOf(l) + 1) % LANGS.length];

export function fmt(t) {
  if (!isFinite(t)) return "0:00.000";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(3).padStart(6, "0")}`;
}

export function parseTime(str) {
  str = String(str).trim().replace(",", ".");
  if (str.includes(":")) {
    const [m, s] = str.split(":");
    return parseInt(m, 10) * 60 + parseFloat(s);
  }
  return parseFloat(str);
}

/** Satır başındaki [tr] / tr: etiketlerini okur. */
export function parseLyrics(text, defLang) {
  let lang = defLang;
  const out = [];
  for (let raw of text.split(/\r?\n/)) {
    raw = raw.trim();
    if (!raw) continue;
    const tag = raw.match(/^\[(de|tr|en)\]\s*(.*)$/i) || raw.match(/^(de|tr|en):\s*(.*)$/i);
    let l = defLang;
    if (tag) { l = tag[1].toLowerCase(); raw = tag[2].trim(); }
    if (!raw) { lang = l; continue; }   // tek başına [tr] → sonraki satırlar için
    out.push({ text: raw, lang: tag ? l : lang });
  }
  return out;
}
