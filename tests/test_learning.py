import numpy as np
import pytest

from app import learning

N_META = 9 + len(learning.LANGS)
N_ENV = len(learning.OFFSETS)


def _feats(rng, lang, last_char):
    meta = [2.0, 30, 6, 1.0, 1.0, 0.8, 0.3, 0.4, last_char] + [1.0 if lang == l else 0.0 for l in learning.LANGS]
    return {"meta": meta, "start": list(rng.uniform(-1, 0, N_ENV)), "end": list(rng.uniform(-1, 0, N_ENV))}


def make_project(storage, pid, rows, saved=True):
    """rows: [(lang, raw_start, raw_end, final_start, final_end, feats)]"""
    lines = []
    for i, (lang, rs, re_, fs, fe, feats) in enumerate(rows):
        lines.append({"id": f"l{i}", "text": "x", "lang": lang, "raw": {"start": rs, "end": re_},
                      "feats": feats, "start": fs, "end": fe})
    storage.save({"id": pid, "title": pid, "created": pid, "status": "ready", "lines": lines,
                  "saved": saved, "history": []})


# ---------------------------------------------------------------- özellikler

def test_energy_envelope_shape_and_range():
    sr = 16000
    wav = np.zeros(sr * 2, np.float32)
    wav[sr:] = 0.5 * np.sin(np.arange(sr) / 5)
    env = learning.energy_envelope(wav)
    assert abs(len(env) - 200) <= 2  # 10 ms adım
    assert env.min() >= -2.0 and env.max() <= 0.5
    assert env[150] > env[50]  # sesli bölüm sessizden yüksek


def test_energy_envelope_tiny_input():
    assert len(learning.energy_envelope(np.zeros(10, np.float32))) == 1


def test_line_features_lengths():
    env = np.zeros(1000, np.float32)
    results = [
        {"start": 1.0, "end": 2.0, "score": 0.9, "words": [{"start": 1.0, "end": 1.4, "last_char": 0.1}, {"start": 1.5, "end": 2.0, "last_char": 0.3}]},
        {"start": 3.0, "end": 4.0, "score": 0.0, "words": []},
    ]
    for li in range(2):
        f = learning.line_features(env, results, li, {"text": "abc", "lang": "tr"})
        assert len(f["meta"]) == N_META and len(f["start"]) == N_ENV and len(f["end"]) == N_ENV
    f0 = learning.line_features(env, results, 0, {"text": "abc", "lang": "tr"})
    assert f0["meta"][4] == pytest.approx(1.0)  # bir sonraki satıra boşluk
    assert f0["meta"][-2] == 1.0  # tr one-hot
    assert len(learning._vec(f0, "start")) == N_META + N_ENV + N_ENV - 1


# ---------------------------------------------------------------- öğrenme

def test_retrain_without_data(clean_data):
    st = learning.retrain()
    assert st["n_samples"] == 0 and st["use_model"] is False
    assert all(b["n"] == 0 for b in st["bias"].values())


def test_unsaved_projects_ignored(clean_data):
    rng = np.random.default_rng(0)
    make_project(clean_data, "p1", [("de", 1, 2, 1.5, 2.5, _feats(rng, "de", 0.1))], saved=False)
    assert learning.retrain()["n_samples"] == 0


def test_bias_learned_with_shrinkage_and_outliers(clean_data):
    rng = np.random.default_rng(0)
    rows = [("de", t, t + 2, t + 0.1, t + 2 + 0.3, _feats(rng, "de", 0.1)) for t in range(0, 80, 4)]  # 20 satır
    rows.append(("de", 90, 92, 99, 101, _feats(rng, "de", 0.1)))  # 9 sn: aykırı
    make_project(clean_data, "p1", rows)
    st = learning.retrain()
    b = st["bias"]["de"]
    assert st["n_outliers"] == 1 and b["n"] == 20
    k = 20 / (20 + learning.SHRINK)
    assert b["start"] == pytest.approx(0.1 * k, abs=1e-6)
    assert b["end"] == pytest.approx(0.3 * k, abs=1e-6)
    assert st["bias"]["tr"]["n"] == 0 and st["use_model"] is False


def test_propose_applies_bias_and_keeps_order(clean_data):
    rng = np.random.default_rng(0)
    make_project(clean_data, "p1", [("en", t, t + 1, t + 0.5, t + 1.5, _feats(rng, "en", 0.1)) for t in range(0, 400, 4)])
    learning.retrain()
    lines = [
        {"lang": "en", "raw": {"start": 1.0, "end": 2.0}},
        {"lang": "en", "raw": {"start": 1.5, "end": 1.6}},   # öncekiyle çakışıyor ve çok kısa
        {"lang": "tr", "raw": {"start": 9.0, "end": 12.0}},  # tr için veri yok → kaydırma yok, süreyle kırpılır
    ]
    version = learning.propose(lines, duration=10.0)
    assert version > 0
    p = [l["proposed"] for l in lines]
    assert p[0]["start"] > 1.0  # +0.5 civarı kaydırma öğrenildi
    assert p[1]["start"] >= p[0]["end"]
    assert p[1]["end"] - p[1]["start"] >= 0.2 - 1e-9
    assert p[2]["start"] == pytest.approx(9.0) and p[2]["end"] == 10.0


def test_propose_keeps_anchors_fixed(clean_data):
    rng = np.random.default_rng(0)
    make_project(clean_data, "p1", [("en", t, t + 1, t + 0.5, t + 1.5, _feats(rng, "en", 0.1)) for t in range(0, 400, 4)])
    learning.retrain()  # en için ~+0.45 sn kaydırma öğrenildi
    lines = [
        {"lang": "en", "raw": {"start": 8.0, "end": 9.9}},               # kaydırılınca çapaya taşar
        {"lang": "en", "raw": {"start": 10.0, "end": 12.0}, "anchor": True},
        {"lang": "en", "raw": {"start": 12.0, "end": 13.0}},
    ]
    learning.propose(lines, duration=60)
    p = [l["proposed"] for l in lines]
    assert p[1] == {"start": 10.0, "end": 12.0}
    assert p[0]["end"] <= 10.0 and p[0]["start"] > 8.0
    assert p[2]["start"] >= 12.0


def test_anchored_lines_not_used_for_training(clean_data):
    rng = np.random.default_rng(0)
    make_project(clean_data, "p1", [("de", 1, 2, 1.2, 2.2, _feats(rng, "de", 0.1)),
                                    ("de", 5, 6, 5, 6, _feats(rng, "de", 0.1))])
    p = clean_data.load("p1")
    p["lines"][1]["anchor"] = True
    clean_data.save(p)
    assert learning.retrain()["n_samples"] == 1


def test_propose_without_any_training(clean_data):
    lines = [{"lang": "de", "raw": {"start": 1.0, "end": 2.0}}]
    assert learning.propose(lines, 10) == 0
    assert lines[0]["proposed"] == {"start": 1.0, "end": 2.0}


def test_model_b_activates_when_it_beats_bias(clean_data):
    """Bitiş düzeltmesi son harfin uzunluğuna bağlı: sabit sapma bunu öğrenemez, model öğrenebilir."""
    rng = np.random.default_rng(1)
    for s in range(4):
        rows = []
        for i in range(50):
            lc = float(rng.choice([0.05, 0.6]))
            t = i * 4.0
            de = 0.8 if lc > 0.3 else -0.1
            rows.append(("de", t, t + 2, t, t + 2 + de, _feats(rng, "de", lc)))
        make_project(clean_data, f"s{s}", rows)
    st = learning.retrain()
    assert st["n_songs"] == 4 and st["n_samples"] == 200
    assert st["cv"]["model"] < st["cv"]["bias"]
    assert st["use_model"] is True

    long_note = [{"lang": "de", "raw": {"start": 0, "end": 2}, "feats": _feats(rng, "de", 0.6)}]
    short_note = [{"lang": "de", "raw": {"start": 0, "end": 2}, "feats": _feats(rng, "de", 0.05)}]
    learning.propose(long_note, 100)
    learning.propose(short_note, 100)
    assert long_note[0]["proposed"]["end"] == pytest.approx(2.8, abs=0.15)
    assert short_note[0]["proposed"]["end"] == pytest.approx(1.9, abs=0.15)


def test_state_persists_to_disk(clean_data):
    rng = np.random.default_rng(0)
    make_project(clean_data, "p1", [("tr", 1, 2, 1.2, 2.2, _feats(rng, "tr", 0.1))])
    st = learning.retrain()
    learning._state = None  # sunucu yeniden başlamış gibi
    assert learning.status()["version"] == st["version"]
    assert (clean_data.LEARN_DIR / "state.json").exists()
