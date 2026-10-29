"""Match The Lyrics — yerel web sunucusu."""
import json
import queue
import threading
import time
import traceback
from urllib.parse import quote

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import export, learning, srt, storage
from .align import flag_suspects
from .audio import DEFAULT_SEPARATION, SEPARATION_MODELS

app = FastAPI(title="Match The Lyrics")


@app.middleware("http")
async def no_cache(request, call_next):
    """Yerel uygulama: tarayıcı önbelleği yalnızca sorun çıkarır (ör. aynı portu kullanmış başka bir uygulamanın
    sayfaları). Koşullu istekleri yok sayıp her yanıtı önbelleğe alınmaz olarak işaretle."""
    scope_headers = [(k, v) for k, v in request.scope["headers"] if k not in (b"if-none-match", b"if-modified-since")]
    request.scope["headers"] = scope_headers
    response = await call_next(request)
    if not request.url.path.startswith("/api/projects/") or "/audio/" not in request.url.path:
        response.headers["Cache-Control"] = "no-store"
    return response

STATIC = storage.ROOT / "static"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"}
EXPORTS = {
    "srt": (".srt", "application/x-subrip", lambda p: srt.write(p["lines"])),
    "lrc": (".lrc", "text/plain; charset=utf-8", lambda p: export.lrc(p["lines"], p["title"])),
    "lrc-words": (".lrc", "text/plain; charset=utf-8", lambda p: export.lrc(p["lines"], p["title"], words=True)),
    "ass": (".ass", "text/x-ssa; charset=utf-8", lambda p: export.ass(p["lines"], p["title"])),
}

# ---------------------------------------------------------------- iş kuyruğu (GPU tek tek)

_jobs = queue.Queue()


def _worker():
    while True:
        pid, separate = _jobs.get()
        try:
            _process(pid, separate)
        except Exception as e:
            traceback.print_exc()
            storage.update(pid, status="error", error=str(e), progress=None)


def _process(pid, separate):
    from . import align, audio

    d = storage.pdir(pid)
    p = storage.load(pid)
    if separate or not (d / "vocals16.npy").exists():
        model = p.get("separation", DEFAULT_SEPARATION)
        storage.update(pid, status="processing", progress=f"Vokal ayrılıyor (Demucs · {SEPARATION_MODELS[model]})…")
        vocals, sr = audio.separate_vocals(d / p["audio_file"], model)
        audio.encode_mp3(vocals, sr, d / "vocals.mp3")
        wav16 = audio.resample_mono(vocals[0], sr, align.SR)
        np.save(d / "vocals16.npy", wav16)
    wav16 = np.load(d / "vocals16.npy")
    duration = len(wav16) / align.SR

    p = storage.load(pid)
    lines = p["lines"]
    anchors = {i: (l["start"], l["end"]) for i, l in enumerate(lines) if l.get("anchor")}
    storage.update(pid, status="processing",
                   progress=f"Sözler hizalanıyor (MMS{f' · {len(anchors)} çapa' if anchors else ''})…")
    results = align.align(wav16, lines, anchors)
    env = learning.energy_envelope(wav16)
    for li, (line, r) in enumerate(zip(lines, results)):
        line["raw"] = {"start": r["start"], "end": r["end"]}
        line["words"] = r["words"]
        line["aligned_text"] = line["text"]
        line["feats"] = learning.line_features(env, results, li, line)
    version = learning.propose(lines, duration)
    for line in lines:
        if "import" in line:  # içe aktarılmış SRT: doğru zamanlar zaten belli
            line["start"], line["end"] = line["import"]["start"], line["import"]["end"]
        else:
            line["start"], line["end"] = line["proposed"]["start"], line["proposed"]["end"]

    p.update(lines=lines, duration=duration, status="ready", progress=None, error=None,
             learning_version=version)
    if p.get("imported"):
        p["saved"] = True
        p["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    storage.save(p)
    if p.get("imported"):
        learning.retrain()


threading.Thread(target=_worker, daemon=True).start()

# ---------------------------------------------------------------- yardımcılar


def _check_separation(name):
    if name not in SEPARATION_MODELS:
        raise HTTPException(400, f"Bilinmeyen ayırma modeli: {name}")
    return name


def _new_project(title, upload: UploadFile, lines, imported=False, separation=DEFAULT_SEPARATION):
    ext = "." + (upload.filename or "a.mp3").rsplit(".", 1)[-1].lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(400, f"Desteklenmeyen ses türü: {ext}")
    if not lines:
        raise HTTPException(400, "Söz satırı yok.")
    _check_separation(separation)
    pid = storage.new_id()
    d = storage.pdir(pid)
    d.mkdir(parents=True)
    with open(d / f"original{ext}", "wb") as f:
        while chunk := upload.file.read(1 << 20):
            f.write(chunk)
    for i, line in enumerate(lines):
        line["id"] = f"l{i}"
        if line.get("lang") not in learning.LANGS:
            line["lang"] = "de"
    project = {
        "id": pid, "title": title or upload.filename, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "audio_file": f"original{ext}", "status": "queued", "progress": "Sırada…",
        "lines": lines, "saved": False, "imported": imported, "history": [], "separation": separation,
    }
    storage.save(project)
    _jobs.put((pid, True))
    return project


def _get(pid):
    try:
        return storage.load(pid)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Proje bulunamadı")


def _public(p):
    p = dict(p)
    lines = flag_suspects([dict(l) for l in p["lines"]])
    p["lines"] = [{k: v for k, v in l.items() if k != "feats"} for l in lines]
    p.setdefault("separation", DEFAULT_SEPARATION)
    return p

# ---------------------------------------------------------------- API


@app.get("/api/config")
def config():
    return {"separation_models": SEPARATION_MODELS, "default_separation": DEFAULT_SEPARATION,
            "exports": list(EXPORTS)}


@app.get("/api/projects")
def list_projects():
    return storage.list_projects()


@app.post("/api/projects")
def create_project(audio: UploadFile = File(...), title: str = Form(""), lines: str = Form(...),
                   separation: str = Form(DEFAULT_SEPARATION)):
    data = json.loads(lines)
    data = [{"text": l["text"].strip(), "lang": l.get("lang", "de")} for l in data if l.get("text", "").strip()]
    return _public(_new_project(title, audio, data, separation=separation))


@app.post("/api/import")
def import_srt(audio: UploadFile = File(...), srt_file: UploadFile = File(...),
               lang: str = Form("de"), title: str = Form(""), separation: str = Form(DEFAULT_SEPARATION)):
    entries = srt.parse(srt_file.file.read().decode("utf-8", errors="replace"))
    lines = [{"text": e["text"], "lang": lang, "import": {"start": e["start"], "end": e["end"]}} for e in entries]
    return _public(_new_project(title or srt_file.filename, audio, lines, imported=True, separation=separation))


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _public(_get(pid))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    _get(pid)
    storage.delete(pid)
    threading.Thread(target=learning.retrain, daemon=True).start()
    return {"ok": True}


@app.get("/api/projects/{pid}/audio/{kind}")
def get_audio(pid: str, kind: str):
    p = _get(pid)
    d = storage.pdir(pid)
    path = d / ("vocals.mp3" if kind == "vocals" else p["audio_file"])
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


class LineIn(BaseModel):
    id: str | None = None
    text: str
    lang: str = "de"
    start: float
    end: float
    anchor: bool = False


class SaveIn(BaseModel):
    lines: list[LineIn]


@app.put("/api/projects/{pid}/lines")
def save_lines(pid: str, body: SaveIn):
    p = _get(pid)
    old = {l["id"]: l for l in p["lines"]}
    new_lines, errs_s, errs_e = [], [], []
    for i, l in enumerate(body.lines):
        base = dict(old.get(l.id, {})) if l.id else {}
        base.update(id=l.id or f"n{int(time.time() * 1000)}_{i}", text=l.text.strip(), lang=l.lang,
                    start=round(l.start, 3), end=round(l.end, 3), anchor=l.anchor)
        if base.get("proposed") and not (l.anchor and base.get("raw") == base["proposed"]):
            errs_s.append(abs(base["start"] - base["proposed"]["start"]))
            errs_e.append(abs(base["end"] - base["proposed"]["end"]))
        new_lines.append(base)
    p["lines"] = new_lines
    first_save = not p.get("saved")
    p["saved"] = True
    p["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if errs_s:
        entry = {"saved_at": p["saved_at"], "n": len(errs_s),
                 "mae_start_ms": round(float(np.mean(errs_s)) * 1000),
                 "mae_end_ms": round(float(np.mean(errs_e)) * 1000),
                 "learning_version": p.get("learning_version", 0)}
        if first_save or not p["history"]:
            p["history"].append(entry)
        else:
            p["history"][-1] = entry
    storage.save(p)
    threading.Thread(target=learning.retrain, daemon=True).start()
    return {"ok": True, "history": p["history"]}


@app.post("/api/projects/{pid}/repropose")
def repropose(pid: str):
    """Ham hizalamaya güncel öğrenmeyi yeniden uygular (kullanıcı düzeltmeleri silinir)."""
    p = _get(pid)
    lines = [l for l in p["lines"] if l.get("raw")]
    version = learning.propose(lines, p.get("duration") or 1e9)
    for l in lines:
        l["start"], l["end"] = l["proposed"]["start"], l["proposed"]["end"]
    p["learning_version"] = version
    p["history"] = []
    p["saved"] = False
    storage.save(p)
    return _public(p)


class RealignIn(BaseModel):
    lines: list[LineIn]
    separation: str | None = None


@app.post("/api/projects/{pid}/realign")
def realign(pid: str, body: RealignIn):
    """
    Güncel metin ve çapalarla yeniden hizalar. Çapalı satırlar yerinde kalır, aradaki satırlar çapaların
    arasındaki boşluğa hizalanır. 'separation' verilirse vokal o modelle yeniden ayrılır.
    """
    p = _get(pid)
    separate = False
    if body.separation is not None:
        _check_separation(body.separation)
        separate = body.separation != p.get("separation", DEFAULT_SEPARATION)
        p["separation"] = body.separation
    lines = []
    for l in body.lines:
        if not l.text.strip():
            continue
        line = {"id": f"l{len(lines)}", "text": l.text.strip(), "lang": l.lang}
        if l.anchor:
            if l.end <= l.start:
                raise HTTPException(400, f"Çapalı satırın bitişi başlangıcından sonra olmalı: {l.text!r}")
            line.update(anchor=True, start=round(l.start, 3), end=round(l.end, 3))
        lines.append(line)
    anchored = [l for l in lines if l.get("anchor")]
    for a, b in zip(anchored, anchored[1:]):
        if b["start"] < a["end"] - 1e-3:
            raise HTTPException(400, f"Çapalar sırasız veya çakışıyor: {a['text']!r} ve {b['text']!r}")
    p["lines"] = lines
    p.update(status="queued", progress="Sırada…", saved=False, history=[])
    storage.save(p)
    _jobs.put((pid, separate))
    return _public(p)


def _download(p, fmt):
    if fmt not in EXPORTS:
        raise HTTPException(404, "Bilinmeyen biçim")
    ext, media, render = EXPORTS[fmt]
    name = "".join(c for c in p["title"] if c.isalnum() or c in " -_").strip() or "lyrics"
    if fmt == "lrc-words":
        name += " (karaoke)"
    ascii_name = name.encode("ascii", "ignore").decode().strip() or "lyrics"
    disposition = f'attachment; filename="{ascii_name}{ext}"; filename*=UTF-8\'\'{quote(name)}{ext}'
    return Response(render(p), media_type=media, headers={"Content-Disposition": disposition})


@app.get("/api/projects/{pid}/srt")
def download_srt(pid: str):
    return _download(_get(pid), "srt")


@app.get("/api/projects/{pid}/export/{fmt}")
def download_export(pid: str, fmt: str):
    return _download(_get(pid), fmt)


@app.get("/api/learning")
def learning_status():
    projects = storage.list_projects(full=True)
    history = []
    for p in projects:
        for h in p.get("history", []):
            history.append({"title": p["title"], "id": p["id"], **h})
    history.sort(key=lambda h: h["saved_at"])
    return {
        "state": learning.status(),
        "history": history,
        "min_samples_model": learning.MIN_SAMPLES_MODEL,
        "min_songs_model": learning.MIN_SONGS_MODEL,
    }


@app.post("/api/learning/retrain")
def learning_retrain():
    return learning.retrain()


# Yarıda kalmış işleri yeniden sıraya al.
for _p in storage.list_projects():
    if _p["status"] in ("queued", "processing"):
        _jobs.put((_p["id"], False))

app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
