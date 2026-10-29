"""HTTP API testleri. Ağır modeller (Demucs, MMS) sahte sürümlerle değiştirilir."""
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import align, audio, server, srt

DURATION = 30.0
CALLS = {"separate": [], "align": []}


def fake_separate(path, model_name="htdemucs"):
    CALLS["separate"].append(model_name)
    return np.zeros((1, int(44100 * DURATION)), np.float32), 44100


def fake_align(wav16, lines, anchors=None):
    anchors = anchors or {}
    CALLS["align"].append(dict(anchors))
    out = []
    for i, line in enumerate(lines):
        s, e = anchors.get(i, (1.0 + i * 3, 3.0 + i * 3))
        score = 0.02 if "şüpheli" in line["text"] else 0.3
        out.append({"start": s, "end": e, "score": score,
                    "words": [{"i": 0, "start": s, "end": e, "score": score, "last_char": 0.2}]})
    return out


@pytest.fixture
def client(clean_data, monkeypatch):
    monkeypatch.setattr(audio, "separate_vocals", fake_separate)
    monkeypatch.setattr(align, "align", fake_align)
    CALLS["separate"].clear()
    CALLS["align"].clear()
    with TestClient(server.app) as c:
        yield c


def wait_ready(client, pid, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        p = client.get(f"/api/projects/{pid}").json()
        if p["status"] in ("ready", "error"):
            return p
        time.sleep(0.1)
    raise TimeoutError(p)


def create(client, lines=None, name="song.mp3"):
    lines = lines or [{"text": "Erste Zeile", "lang": "de"}, {"text": "İkinci satır", "lang": "tr"}, {"text": "  ", "lang": "en"}]
    r = client.post("/api/projects", data={"title": "Şarkı Ä", "lines": json.dumps(lines)},
                    files={"audio": (name, b"fake-audio", "audio/mpeg")})
    return r


def test_static_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "Match The Lyrics" in r.text
    assert client.get("/util.js").status_code == 200


def test_static_ignores_stale_browser_cache(client):
    # Aynı portu kullanmış başka bir uygulamanın önbelleği 304 ile geri dönmemeli.
    r = client.get("/", headers={"If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT", "If-None-Match": '"x"'})
    assert r.status_code == 200 and "Match The Lyrics" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_create_process_and_get(client):
    r = create(client)
    assert r.status_code == 200
    pid = r.json()["id"]
    p = wait_ready(client, pid)
    assert p["status"] == "ready", p.get("error")
    assert p["title"] == "Şarkı Ä"
    assert [l["text"] for l in p["lines"]] == ["Erste Zeile", "İkinci satır"]  # boş satır atıldı
    assert p["duration"] == pytest.approx(DURATION, abs=0.01)
    for l in p["lines"]:
        assert "feats" not in l  # iç özellikler istemciye gönderilmez
        assert l["raw"] and l["proposed"] and l["start"] == l["proposed"]["start"]
    assert client.get(f"/api/projects/{pid}/audio/original").content == b"fake-audio"
    assert client.get(f"/api/projects/{pid}/audio/vocals").status_code == 200
    assert pid in [x["id"] for x in client.get("/api/projects").json()]


def test_bad_uploads(client):
    assert create(client, name="song.exe").status_code == 400
    assert create(client, lines=[{"text": "   ", "lang": "de"}]).status_code == 400


def test_unknown_lang_defaults_to_de(client):
    pid = create(client, lines=[{"text": "a", "lang": "xx"}]).json()["id"]
    assert wait_ready(client, pid)["lines"][0]["lang"] == "de"


@pytest.mark.parametrize("pid", ["nope", "..", "a.b", "..%2F..%2Fapp"])
def test_missing_or_invalid_ids(client, pid):
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert client.get(f"/api/projects/{pid}/srt").status_code == 404


def test_save_history_srt_and_learning(client):
    pid = create(client).json()["id"]
    p = wait_ready(client, pid)
    edited = [{"id": l["id"], "text": l["text"], "lang": l["lang"], "start": l["start"] + 0.1, "end": l["end"] + 0.3}
              for l in p["lines"]]
    edited.append({"id": None, "text": "Yeni satır", "lang": "tr", "start": 20, "end": 21})
    r = client.put(f"/api/projects/{pid}/lines", json={"lines": edited})
    assert r.status_code == 200
    h = r.json()["history"]
    assert len(h) == 1 and h[0]["n"] == 2 and h[0]["mae_start_ms"] == 100 and h[0]["mae_end_ms"] == 300

    # ikinci kayıt geçmişi büyütmez, son girdiyi günceller
    assert len(client.put(f"/api/projects/{pid}/lines", json={"lines": edited}).json()["history"]) == 1

    p = client.get(f"/api/projects/{pid}").json()
    assert p["saved"] and len(p["lines"]) == 3 and p["lines"][2]["id"].startswith("n")

    r = client.get(f"/api/projects/{pid}/srt")
    assert r.headers["content-type"].startswith("application/x-subrip")
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and "filename*=UTF-8''%C5%9Eark%C4%B1%20%C3%84.srt" in cd
    parsed = srt.parse(r.text)
    assert [x["text"] for x in parsed] == ["Erste Zeile", "İkinci satır", "Yeni satır"]

    time.sleep(0.5)  # arka plan yeniden eğitimi
    lr = client.post("/api/learning/retrain").json()
    assert lr["n_samples"] == 2 and lr["n_songs"] == 1
    d = client.get("/api/learning").json()
    assert len(d["history"]) == 1 and d["state"]["bias"]["de"]["n"] == 1


def test_repropose_resets_edits(client):
    pid = create(client).json()["id"]
    p = wait_ready(client, pid)
    edited = [{**{k: l[k] for k in ("id", "text", "lang")}, "start": 0.0, "end": 0.5} for l in p["lines"]]
    client.put(f"/api/projects/{pid}/lines", json={"lines": edited})
    p2 = client.post(f"/api/projects/{pid}/repropose").json()
    assert p2["saved"] is False and p2["history"] == []
    assert [l["start"] for l in p2["lines"]] == [l["proposed"]["start"] for l in p2["lines"]]


def test_realign_with_new_text(client):
    pid = create(client).json()["id"]
    wait_ready(client, pid)
    r = client.post(f"/api/projects/{pid}/realign", json={"lines": [
        {"text": "Tek satır", "lang": "tr", "start": 0, "end": 1},
        {"text": "", "lang": "tr", "start": 0, "end": 1},
    ]})
    assert r.status_code == 200
    p = wait_ready(client, pid)
    assert [l["text"] for l in p["lines"]] == ["Tek satır"] and p["lines"][0]["raw"]


def test_import_srt_becomes_training_data(client):
    body = srt.write([{"text": "Eins", "start": 1.2, "end": 2.9}, {"text": "Zwei", "start": 4.1, "end": 6.3}])
    r = client.post("/api/import", data={"lang": "de"},
                    files={"audio": ("a.mp3", b"x", "audio/mpeg"), "srt_file": ("lied.srt", body.encode(), "text/plain")})
    assert r.status_code == 200
    p = wait_ready(client, r.json()["id"])
    assert p["imported"] and p["saved"] and p["title"] == "lied.srt"
    assert [(l["start"], l["end"]) for l in p["lines"]] == [(1.2, 2.9), (4.1, 6.3)]
    st = client.get("/api/learning").json()["state"]
    assert st["n_samples"] == 2


def test_delete(client):
    pid = create(client).json()["id"]
    wait_ready(client, pid)
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404


def _payload(lines, overrides=None):
    overrides = overrides or {}
    return [{**{k: l[k] for k in ("id", "text", "lang", "start", "end")}, "anchor": bool(l.get("anchor")),
             **overrides.get(i, {})} for i, l in enumerate(lines)]


def test_suspect_lines_flagged(client):
    lines = [{"text": "iyi satır", "lang": "tr"}, {"text": "şüpheli satır", "lang": "tr"}, {"text": "yine iyi", "lang": "tr"}]
    p = wait_ready(client, create(client, lines=lines).json()["id"])
    assert [l["suspect"] for l in p["lines"]] == [False, True, False]
    assert p["lines"][1]["score"] == pytest.approx(0.02)


def test_realign_with_anchors(client):
    lines = [{"text": f"satır {i}", "lang": "tr"} for i in range(4)]
    pid = create(client, lines=lines).json()["id"]
    p = wait_ready(client, pid)
    body = _payload(p["lines"], {2: {"start": 7.5, "end": 9.5, "anchor": True}})
    assert client.post(f"/api/projects/{pid}/realign", json={"lines": body}).status_code == 200
    p = wait_ready(client, pid)
    assert CALLS["align"][-1] == {2: (7.5, 9.5)}
    a = p["lines"][2]
    assert a["anchor"] and (a["start"], a["end"]) == (7.5, 9.5) and not a["suspect"]
    assert not p["lines"][0].get("anchor")
    assert CALLS["separate"] == ["htdemucs"]  # vokal tekrar ayrılmadı

    # çapa kaydedilince korunur; öğrenmeye katılmaz
    client.put(f"/api/projects/{pid}/lines", json={"lines": _payload(p["lines"])})
    assert client.get(f"/api/projects/{pid}").json()["lines"][2]["anchor"] is True
    assert client.post("/api/learning/retrain").json()["n_samples"] == 3


@pytest.mark.parametrize("bad", [
    {1: {"start": 5, "end": 4, "anchor": True}},                                                # ters
    {0: {"start": 10, "end": 12, "anchor": True}, 1: {"start": 11, "end": 13, "anchor": True}},  # çakışık
])
def test_realign_rejects_bad_anchors(client, bad):
    pid = create(client).json()["id"]
    p = wait_ready(client, pid)
    r = client.post(f"/api/projects/{pid}/realign", json={"lines": _payload(p["lines"], bad)})
    assert r.status_code == 400


def test_separation_model_choice(client):
    r = client.post("/api/projects", data={"lines": json.dumps([{"text": "a", "lang": "de"}]), "separation": "htdemucs_ft"},
                    files={"audio": ("a.mp3", b"x", "audio/mpeg")})
    p = wait_ready(client, r.json()["id"])
    assert p["separation"] == "htdemucs_ft" and CALLS["separate"] == ["htdemucs_ft"]
    bad = client.post("/api/projects", data={"lines": json.dumps([{"text": "a"}]), "separation": "yok"},
                      files={"audio": ("a.mp3", b"x", "audio/mpeg")})
    assert bad.status_code == 400
    assert client.get("/api/config").json()["separation_models"].keys() >= {"htdemucs", "htdemucs_ft"}


def test_switch_to_hq_vocals_reseparates(client):
    pid = create(client).json()["id"]
    p = wait_ready(client, pid)
    client.post(f"/api/projects/{pid}/realign", json={"lines": _payload(p["lines"]), "separation": "htdemucs_ft"})
    p = wait_ready(client, pid)
    assert CALLS["separate"] == ["htdemucs", "htdemucs_ft"] and p["separation"] == "htdemucs_ft"
    # aynı modelle tekrar istemek yeniden ayırmaz
    client.post(f"/api/projects/{pid}/realign", json={"lines": _payload(p["lines"]), "separation": "htdemucs_ft"})
    wait_ready(client, pid)
    assert len(CALLS["separate"]) == 2


@pytest.mark.parametrize("fmt, ext, marker", [
    ("srt", ".srt", "-->"),
    ("lrc", ".lrc", "[ti:"),
    ("lrc-words", ".lrc", "<00:"),
    ("ass", ".ass", "Dialogue:"),
])
def test_exports(client, fmt, ext, marker):
    pid = create(client).json()["id"]
    wait_ready(client, pid)
    r = client.get(f"/api/projects/{pid}/export/{fmt}")
    assert r.status_code == 200 and marker in r.text
    assert f"{ext}\"" in r.headers["content-disposition"]
    assert client.get(f"/api/projects/{pid}/export/docx").status_code == 404


def test_processing_error_is_reported(client, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("bozuk dosya")
    monkeypatch.setattr(audio, "separate_vocals", boom)
    pid = create(client).json()["id"]
    p = wait_ready(client, pid)
    assert p["status"] == "error" and "bozuk dosya" in p["error"]
