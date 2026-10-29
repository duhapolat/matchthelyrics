import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Testler gerçek data/ klasörüne asla dokunmasın: app içe aktarılmadan önce ayarlanmalı.
_TMP = Path(tempfile.mkdtemp(prefix="mtl-test-"))
os.environ["MTL_DATA_DIR"] = str(_TMP)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"

# Sentetik test şarkısındaki cümleler (tests/fixtures/synthetic_song.mp3), sırasıyla.
SYNTHETIC_LINES = [
    {"text": "The morning train was late again today", "lang": "en"},
    {"text": "I counted every window on the street", "lang": "en"},
    {"text": "Somebody left a light on in the kitchen", "lang": "en"},
    {"text": "Guten Morgen, wie geht es dir heute", "lang": "de"},
    {"text": "We walked along the river after dinner", "lang": "en"},
    {"text": "Bugün hava çok güzel", "lang": "tr"},
]


@pytest.fixture
def clean_data():
    from app import learning, storage

    for d in (storage.PROJECTS, storage.LEARN_DIR):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    learning._state = None
    yield storage
    learning._state = None


@pytest.fixture
def truth():
    return json.loads((FIXTURES / "synthetic_song_truth.json").read_text())


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
