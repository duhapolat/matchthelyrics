"""Karaoke çıktıları: LRC, kelime zamanlı LRC ve ASS (\\k etiketli)."""
from .align import split_words


def word_times(line):
    """
    Satırın her kelimesi için (kelime, başlangıç, bitiş). Hizalayıcının kelime zamanları, kullanıcının son
    satır sınırlarına orantılı olarak taşınır. Metin hizalamadan sonra değiştiyse kelimeler harf
    sayısına göre eşit dağıtılır.
    """
    texts = split_words(line["text"])
    if not texts:
        return []
    start, end = line["start"], max(line["end"], line["start"] + 0.01)
    words = line.get("words") or []
    same_text = line.get("aligned_text", line["text"]) == line["text"]
    usable = same_text and words and all(w["i"] < len(texts) for w in words)

    times = [None] * len(texts)
    if usable:
        a0, a1 = words[0]["start"], max(words[-1]["end"], words[0]["start"] + 0.01)
        scale = (end - start) / (a1 - a0)
        for w in words:
            times[w["i"]] = (start + (w["start"] - a0) * scale, start + (w["end"] - a0) * scale)

    # Zamanı olmayan kelimeleri (noktalama, hizalanamayanlar) bilinen komşuların arasına harf sayısına göre yay.
    i = 0
    while i < len(texts):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(texts) and times[j] is None:
            j += 1
        g0 = times[i - 1][1] if i > 0 else start
        g1 = times[j][0] if j < len(texts) else end
        g1 = max(g1, g0)  # yer yoksa (ör. satır başındaki "—") sıfır süreli olur, sıra bozulmaz
        weights = [max(len(t), 1) for t in texts[i:j]]
        total = sum(weights)
        t = g0
        for k, wgt in zip(range(i, j), weights):
            d = (g1 - g0) * wgt / total
            times[k] = (t, t + d)
            t += d
        i = j
    return [(txt, round(s, 3), round(e, 3)) for txt, (s, e) in zip(texts, times)]


def _lrc_ts(sec):
    cs = int(round(max(sec, 0) * 100))
    m, cs = divmod(cs, 6000)
    return f"{m:02}:{cs // 100:02}.{cs % 100:02}"


def lrc(lines, title="", words=False):
    """Satır zamanlı LRC; words=True ile kelime zamanlı (enhanced) LRC."""
    lines = sorted(lines, key=lambda l: l["start"])
    out = [f"[ti:{title}]"] if title else []
    for i, line in enumerate(lines):
        if words:
            body = " ".join(f"<{_lrc_ts(s)}>{w}" for w, s, _ in word_times(line)) + f" <{_lrc_ts(line['end'])}>"
        else:
            body = line["text"]
        out.append(f"[{_lrc_ts(line['start'])}]{body}")
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else None
        if nxt is None or nxt - line["end"] > 0.5:
            out.append(f"[{_lrc_ts(line['end'])}]")  # satır bitişi: ekranı temizle
    return "\n".join(out) + "\n"


def _ass_ts(sec):
    cs = int(round(max(sec, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    return f"{h}:{m:02}:{cs // 100:02}.{cs % 100:02}"


_ASS_HEADER = """[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,64,&H0000D7FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_escape(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def ass(lines, title=""):
    """Kelime kelime renklenen karaoke altyazısı (Aegisub, VLC, mpv, ffmpeg ile çalışır)."""
    out = [_ASS_HEADER.format(title=_ass_escape(title) or "Match The Lyrics")]
    for line in sorted(lines, key=lambda l: l["start"]):
        parts = []
        cursor = line["start"]
        for w, s, e in word_times(line):
            gap = int(round((s - cursor) * 100))
            if gap > 0:
                parts.append(f"{{\\k{gap}}}")
            parts.append(f"{{\\k{max(1, int(round((e - s) * 100)))}}}{_ass_escape(w)} ")
            cursor = max(cursor, e)
        text = "".join(parts).rstrip()
        out.append(f"Dialogue: 0,{_ass_ts(line['start'])},{_ass_ts(line['end'])},Karaoke,,0,0,0,karaoke,{text}")
    return "\n".join(out) + "\n"
