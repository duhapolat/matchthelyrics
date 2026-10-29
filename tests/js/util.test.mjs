// node --test tests/js/util.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { esc, fmt, nextLang, parseLyrics, parseTime } from "../../static/util.js";

test("fmt", () => {
  assert.equal(fmt(0), "0:00.000");
  assert.equal(fmt(5.5), "0:05.500");
  assert.equal(fmt(65.25), "1:05.250");
  assert.equal(fmt(NaN), "0:00.000");
});

test("parseTime", () => {
  assert.equal(parseTime("1:05.250"), 65.25);
  assert.equal(parseTime("0:05,5"), 5.5);
  assert.equal(parseTime(" 12.3 "), 12.3);
  assert.ok(Number.isNaN(parseTime("abc")));
  for (const t of [0, 3.141, 59.999, 125.5]) assert.equal(parseTime(fmt(t)), t);
});

test("nextLang cycles", () => {
  assert.equal(nextLang("de"), "tr");
  assert.equal(nextLang("tr"), "en");
  assert.equal(nextLang("en"), "de");
});

test("esc", () => {
  assert.equal(esc(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  assert.equal(esc(null), "");
});

test("parseLyrics default language and inline tags", () => {
  const out = parseLyrics("eins\n[tr] iki\n\n en: three \nvier", "de");
  assert.deepEqual(out, [
    { text: "eins", lang: "de" },
    { text: "iki", lang: "tr" },
    { text: "three", lang: "en" },
    { text: "vier", lang: "de" },
  ]);
});

test("parseLyrics block tag switches following lines", () => {
  const out = parseLyrics("eins\r\n[TR]\r\niki\r\nüç\r\n[de]\r\nvier", "de");
  assert.deepEqual(out.map((l) => l.lang), ["de", "tr", "tr", "de"]);
});
