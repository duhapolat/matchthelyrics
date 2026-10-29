"""Sözleri vokal kaydına hizalama (Meta MMS forced aligner, torchaudio)."""
import math
import re
import threading
import unicodedata

import numpy as np
import torch

from .audio import DEVICE

SR = 16000
CHUNK_SEC = 30
CONTEXT_SEC = 1.5
MIN_WINDOW_SEC = 0.1

# Hizalayıcının kendinden emin olmadığı satırlar: kullanıcının gerçek düzeltmelerinde >1 sn kayan satırların
# puanı 0.03–0.05, doğru satırlarınki 0.18–0.24 civarındaydı.
SUSPECT_ABS = 0.08
SUSPECT_REL = 0.4

_bundle = None
_model = None
_dict = None
_lock = threading.Lock()

# Dile özel harf dönüşümleri. MMS hizalayıcı yalnızca a-z ve ' tanır;
# bu harfleri en yakın okunuşlarına çeviriyoruz.
_LANG_MAP = {
    "de": {"ä": "e", "ö": "o", "ü": "u", "ß": "s"},
    "tr": {"ç": "c", "ş": "s", "ğ": "g", "ı": "i", "ö": "o", "ü": "u", "â": "a", "î": "i", "û": "u"},
    "en": {},
}

_NUMBERS = {
    "de": ["null", "eins", "zwei", "drei", "vier", "fuenf", "sechs", "sieben", "acht", "neun"],
    "tr": ["sifir", "bir", "iki", "uc", "dort", "bes", "alti", "yedi", "sekiz", "dokuz"],
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
}


def _load():
    global _bundle, _model, _dict
    if _model is None:
        import torchaudio
        _bundle = torchaudio.pipelines.MMS_FA
        _model = _bundle.get_model(with_star=True).to(DEVICE).eval()
        _dict = _bundle.get_dict(star="*")


def _lower(text, lang):
    if lang == "tr":
        text = text.replace("I", "ı").replace("İ", "i")
    return text.lower()


def normalize_word(word, lang):
    """Bir kelimeyi hizalayıcının anladığı harflere çevirir. Boş dönebilir."""
    w = _lower(word, lang)
    for src, dst in _LANG_MAP.get(lang, {}).items():
        w = w.replace(src, dst)
    w = re.sub(r"\d", lambda m: " " + _NUMBERS.get(lang, _NUMBERS["en"])[int(m.group())] + " ", w)
    w = unicodedata.normalize("NFKD", w)
    w = "".join(c for c in w if not unicodedata.combining(c))
    w = w.replace("’", "'").replace("`", "'")
    return re.sub(r"[^a-z' ]", "", w).strip(" '")


def split_words(text):
    return [w for w in re.split(r"\s+", text.strip()) if w]


def line_score(line):
    words = line.get("words") or []
    return float(np.mean([w["score"] for w in words])) if words else 0.0


def flag_suspects(lines):
    """Her satıra 'suspect' ekler: puanı hem mutlak hem şarkı içi göreli olarak düşük olanlar."""
    scored = [line_score(l) for l in lines]
    with_words = [s for l, s in zip(lines, scored) if l.get("words")]
    median = float(np.median(with_words)) if with_words else 0.0
    limit = max(SUSPECT_ABS, SUSPECT_REL * median)
    for l, s in zip(lines, scored):
        l["score"] = round(s, 4)
        l["suspect"] = bool(l.get("raw")) and not l.get("anchor") and s < limit
    return lines


def _emissions(wav16):
    """Uzun ses için emisyonları parça parça hesaplar (GPU belleği için)."""
    chunk = CHUNK_SEC * SR
    ctx = int(CONTEXT_SEC * SR)
    hop = 320  # wav2vec2: 20 ms / kare
    parts = []
    with torch.inference_mode():
        for start in range(0, len(wav16), chunk):
            seg_start = max(0, start - ctx)
            seg_end = min(len(wav16), start + chunk + ctx)
            seg = torch.from_numpy(wav16[seg_start:seg_end]).to(DEVICE)[None]
            em, _ = _model(seg)
            em = em[0].float().cpu()
            left = (start - seg_start) // hop
            n = (min(start + chunk, len(wav16)) - start) // hop
            parts.append(em[left:left + n])
    return torch.cat(parts)


def segments(n_lines, anchors, duration):
    """
    Hizalama pencereleri: [(satır indeksleri, t0, t1)].
    Çapalı her satır kendi [başlangıç, bitiş] penceresinde (kelime zamanları için) hizalanır;
    çapasız satır grupları iki çapa arasındaki boşlukta hizalanır.
    """
    out = []
    run = []
    prev_end = 0.0
    for i in range(n_lines):
        if i in anchors:
            a_start, a_end = anchors[i]
            if run:
                out.append((run, prev_end, a_start))
                run = []
            out.append(([i], a_start, a_end))
            prev_end = a_end
        else:
            run.append(i)
    if run:
        out.append((run, prev_end, duration))
    return out


def _align_window(emission, seg_lines, sec_per_frame, offset):
    """Bir pencere içindeki satırları hizalar. Pencere çok darsa her satır için boş liste döner."""
    star = _dict["*"]
    tokens = [[star]]
    owners = [None]
    for li, line in enumerate(seg_lines):
        for wi, word in enumerate(split_words(line["text"])):
            norm = normalize_word(word, line["lang"]).replace(" ", "").replace("'", "")
            if norm:
                tokens.append([_dict[c] for c in norm])
                owners.append((li, wi))
        tokens.append([star])
        owners.append(None)

    words = [[] for _ in seg_lines]
    if len(owners) == len(seg_lines) + 1:  # hizalanacak harf yok
        return words
    try:
        spans = _bundle.get_aligner()(emission, tokens)
    except Exception:  # ör. pencere söylenecek harflerden kısa
        return words
    for owner, span in zip(owners, spans):
        if owner is None:
            continue
        li, wi = owner
        words[li].append({
            "i": wi,
            "start": round(offset + span[0].start * sec_per_frame, 3),
            "end": round(offset + span[-1].end * sec_per_frame, 3),
            "score": float(np.mean([s.score for s in span])),
            "last_char": round((span[-1].end - span[-1].start) * sec_per_frame, 3),
        })
    return words


def align(wav16, lines, anchors=None):
    """
    wav16: 16 kHz mono vokal (numpy).
    lines: [{"text":..., "lang":...}]
    anchors: {satır indeksi: (başlangıç, bitiş)} — kullanıcının kesinleştirdiği satırlar; yerinde kalırlar.
    Dönüş: her satır için {"start","end","words":[...], "score"} (saniye cinsinden).
    """
    anchors = anchors or {}
    duration = len(wav16) / SR
    words_per_line = [[] for _ in lines]
    with _lock:
        _load()
        emission = _emissions(wav16)
        n_frames = emission.shape[0]
        sec_per_frame = duration / n_frames
        for idx, t0, t1 in segments(len(lines), anchors, duration):
            if t1 - t0 < MIN_WINDOW_SEC:
                continue
            f0 = max(0, int(t0 / sec_per_frame))
            f1 = min(n_frames, int(math.ceil(t1 / sec_per_frame)))
            ws = _align_window(emission[f0:f1], [lines[i] for i in idx], sec_per_frame, f0 * sec_per_frame)
            for i, w in zip(idx, ws):
                words_per_line[i] = w
        if DEVICE == "cuda":
            torch.cuda.empty_cache()

    results = []
    for li in range(len(lines)):
        ws = words_per_line[li]
        if li in anchors:
            s, e = anchors[li]
            results.append({"start": s, "end": e, "words": ws, "score": line_score({"words": ws})})
        elif ws:
            results.append({"start": ws[0]["start"], "end": ws[-1]["end"], "words": ws,
                            "score": line_score({"words": ws})})
        else:
            results.append(None)

    # Hizalanamayan (ör. sadece noktalama) satırları komşularının arasına yerleştir.
    for li, r in enumerate(results):
        if r is None:
            prev_end = next((results[j]["end"] for j in range(li - 1, -1, -1) if results[j]), 0.0)
            next_start = next((results[j]["start"] for j in range(li + 1, len(results)) if results[j]), duration)
            results[li] = {"start": prev_end, "end": max(prev_end + 0.5, next_start), "words": [], "score": 0.0}
    return results
