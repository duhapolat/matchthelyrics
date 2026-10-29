"""
Düzeltmelerden öğrenme.

Her kaydedilen şarkıda, hizalayıcının ham önerisi (raw) ile kullanıcının son hali
(start/end) arasındaki fark bir eğitim örneğidir. İki seviye var:

  A) Dil başına sistematik sapma: "başlangıçları hep X ms kaydırıyorsun".
  B) Sınır düzeltme modeli: sınırın etrafındaki vokal enerjisine, satırın
     uzunluğuna, son hecenin uzatılmasına vb. bakarak düzeltmeyi tahmin eder.

B, yeterli veri birikince eğitilir ve yalnızca şarkı bazlı çapraz doğrulamada
A'dan daha iyiyse kullanılır.
"""
import json
import threading
import time

import joblib
import numpy as np

from . import storage

LANGS = ["de", "tr", "en"]
OFFSETS = np.round(np.arange(-0.6, 0.61, 0.1), 2)
MAX_DELTA = 3.0  # bundan büyük düzeltmeler "satır tamamen yanlış yerde" sayılır, öğrenmeye katılmaz
MIN_SAMPLES_MODEL = 150
MIN_SONGS_MODEL = 3
SHRINK = 10  # az veride sapmayı sıfıra doğru çek

_lock = threading.Lock()
_state = None


# ---------------------------------------------------------------- özellikler

def energy_envelope(wav16, sr=16000):
    """10 ms adımlı, şarkıya göre normalize edilmiş dB zarfı."""
    win, hop = int(0.02 * sr), int(0.01 * sr)
    n = max(1, 1 + (len(wav16) - win) // hop)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    idx = np.clip(idx, 0, len(wav16) - 1)
    rms = np.sqrt(np.mean(wav16[idx] ** 2, axis=1) + 1e-10)
    db = 20 * np.log10(rms)
    ref = np.percentile(db, 95)
    return np.clip((db - ref) / 30.0, -2.0, 0.5).astype(np.float32)


def _env_at(env, t):
    i = int(round(t / 0.01))
    return float(env[min(max(i, 0), len(env) - 1)])


def line_features(env, results, li, line):
    """Bir satırın başlangıç ve bitiş sınırları için özellik vektörleri."""
    r = results[li]
    prev_end = results[li - 1]["end"] if li > 0 else 0.0
    next_start = results[li + 1]["start"] if li + 1 < len(results) else r["end"] + 10
    words = r.get("words") or []
    meta = [
        r["end"] - r["start"],
        len(line["text"]),
        len(words),
        min(r["start"] - prev_end, 10.0),
        min(next_start - r["end"], 10.0),
        r.get("score", 0.0),
        (words[0]["end"] - words[0]["start"]) if words else 0.0,
        (words[-1]["end"] - words[-1]["start"]) if words else 0.0,
        words[-1]["last_char"] if words else 0.0,
    ] + [1.0 if line["lang"] == l else 0.0 for l in LANGS]
    start_env = [_env_at(env, r["start"] + o) for o in OFFSETS]
    end_env = [_env_at(env, r["end"] + o) for o in OFFSETS]
    return {"meta": [round(float(x), 4) for x in meta],
            "start": [round(x, 4) for x in start_env],
            "end": [round(x, 4) for x in end_env]}


def _vec(feats, which):
    env = feats[which]
    slope = list(np.diff(env))
    return feats["meta"] + env + slope


# ---------------------------------------------------------------- veri

def collect_samples():
    rows = []
    for p in storage.list_projects(full=True):
        if not p.get("saved"):
            continue
        for line in p["lines"]:
            if not line.get("raw") or not line.get("feats") or line.get("anchor"):
                continue  # çapalı satırın "ham" zamanını kullanıcı koydu: öğretecek bir şeyi yok
            ds = line["start"] - line["raw"]["start"]
            de = line["end"] - line["raw"]["end"]
            rows.append({
                "project": p["id"], "lang": line["lang"], "feats": line["feats"],
                "ds": ds, "de": de, "outlier": abs(ds) > MAX_DELTA or abs(de) > MAX_DELTA,
            })
    return rows


def _bias(rows):
    out = {}
    for lang in LANGS:
        sel = [r for r in rows if r["lang"] == lang and not r["outlier"]]
        n = len(sel)
        if n == 0:
            out[lang] = {"n": 0, "start": 0.0, "end": 0.0}
            continue
        k = n / (n + SHRINK)
        out[lang] = {
            "n": n,
            "start": float(np.median([r["ds"] for r in sel]) * k),
            "end": float(np.median([r["de"] for r in sel]) * k),
        }
    return out


def _fit_models(rows):
    from sklearn.ensemble import GradientBoostingRegressor

    def make():
        return GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05,
                                         subsample=0.8, loss="huber", random_state=0)

    Xs = np.array([_vec(r["feats"], "start") for r in rows])
    Xe = np.array([_vec(r["feats"], "end") for r in rows])
    ys = np.array([r["ds"] for r in rows])
    ye = np.array([r["de"] for r in rows])
    return make().fit(Xs, ys), make().fit(Xe, ye)


def _evaluate(rows):
    """Şarkı bazlı çapraz doğrulama: ham / sapma / model ortalama hataları (ms)."""
    from sklearn.model_selection import GroupKFold

    groups = np.array([r["project"] for r in rows])
    n_groups = len(set(groups))
    folds = min(5, n_groups)
    err = {"raw": [], "bias": [], "model": []}
    for tr, te in GroupKFold(n_splits=folds).split(rows, groups=groups):
        train = [rows[i] for i in tr]
        test = [rows[i] for i in te]
        bias = _bias(train)
        ms, me = _fit_models(train)
        for r in test:
            b = bias[r["lang"]]
            ps = ms.predict([_vec(r["feats"], "start")])[0]
            pe = me.predict([_vec(r["feats"], "end")])[0]
            err["raw"].append((abs(r["ds"]) + abs(r["de"])) / 2)
            err["bias"].append((abs(r["ds"] - b["start"]) + abs(r["de"] - b["end"])) / 2)
            err["model"].append((abs(r["ds"] - ps) + abs(r["de"] - pe)) / 2)
    return {k: round(float(np.mean(v)) * 1000) for k, v in err.items()}


def retrain():
    """Tüm kaydedilmiş şarkılardan yeniden öğrenir. Küçük veriyle birkaç saniye sürer."""
    global _state
    with _lock:
        rows = collect_samples()
        clean = [r for r in rows if not r["outlier"]]
        songs = len({r["project"] for r in clean})
        state = {
            "version": int(time.time()),
            "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_samples": len(clean),
            "n_outliers": len(rows) - len(clean),
            "n_songs": songs,
            "bias": _bias(clean),
            "cv": None,
            "use_model": False,
        }
        models = None
        if len(clean) >= MIN_SAMPLES_MODEL and songs >= MIN_SONGS_MODEL:
            state["cv"] = _evaluate(clean)
            if state["cv"]["model"] < state["cv"]["bias"]:
                state["use_model"] = True
                models = _fit_models(clean)
        joblib.dump({"state": state, "models": models}, storage.LEARN_DIR / "model.joblib")
        (storage.LEARN_DIR / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        _state = {"state": state, "models": models}
        return state


def _get():
    global _state
    if _state is None:
        path = storage.LEARN_DIR / "model.joblib"
        _state = joblib.load(path) if path.exists() else {"state": None, "models": None}
    return _state


def status():
    return _get()["state"]


def propose(lines, duration):
    """Ham hizalamaya öğrenilmiş düzeltmeleri uygular; satırlarda 'proposed' alanını doldurur."""
    st = _get()
    state, models = st["state"], st["models"]
    for line in lines:
        s, e = line["raw"]["start"], line["raw"]["end"]
        if line.get("anchor"):
            line["proposed"] = {"start": s, "end": e}
            continue
        if state:
            if state["use_model"] and models and line.get("feats"):
                s += float(models[0].predict([_vec(line["feats"], "start")])[0])
                e += float(models[1].predict([_vec(line["feats"], "end")])[0])
            else:
                b = state["bias"].get(line["lang"], {"start": 0.0, "end": 0.0})
                s += b["start"]
                e += b["end"]
        line["proposed"] = {"start": s, "end": e}

    # Mantıklı sınırlar: sıralı, çakışmasız, en az 0.2 sn. Çapalar hiç kıpırdamaz; önlerindeki satır çapaya taşmaz.
    prev_end = 0.0
    for i, line in enumerate(lines):
        p = line["proposed"]
        if line.get("anchor"):
            prev_end = p["end"]
            continue
        nxt = next((l for l in lines[i + 1:] if l.get("anchor")), None)
        limit = nxt["proposed"]["start"] if nxt else duration
        p["start"] = round(min(max(p["start"], prev_end, 0.0), max(limit - 0.2, prev_end)), 3)
        p["end"] = round(min(max(p["end"], p["start"] + 0.2), max(limit, p["start"] + 0.2), duration), 3)
        prev_end = p["end"]
    return state["version"] if state else 0
