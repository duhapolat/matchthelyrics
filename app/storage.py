"""Proje dosyaları: data/projects/<id>/project.json + ses dosyaları."""
import json
import os
import shutil
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("MTL_DATA_DIR") or ROOT / "data")
PROJECTS = DATA / "projects"
LEARN_DIR = DATA / "learning"
PROJECTS.mkdir(parents=True, exist_ok=True)
LEARN_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.RLock()


def new_id():
    return uuid.uuid4().hex[:10]


def pdir(pid):
    if not pid.isalnum():
        raise ValueError("geçersiz id")
    return PROJECTS / pid


def load(pid):
    with _lock:
        return json.loads((pdir(pid) / "project.json").read_text(encoding="utf-8"))


def save(project):
    with _lock:
        d = pdir(project["id"])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "project.json.tmp"
        tmp.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(d / "project.json")


def update(pid, **fields):
    with _lock:
        p = load(pid)
        p.update(fields)
        save(p)
        return p


def list_projects(full=False):
    out = []
    for d in PROJECTS.iterdir():
        f = d / "project.json"
        if not f.exists():
            continue
        p = json.loads(f.read_text(encoding="utf-8"))
        if not full:
            p = {k: p.get(k) for k in ("id", "title", "created", "status", "saved", "saved_at", "imported", "progress")}
        out.append(p)
    return sorted(out, key=lambda p: p.get("created", ""), reverse=True)


def delete(pid):
    with _lock:
        shutil.rmtree(pdir(pid), ignore_errors=True)
