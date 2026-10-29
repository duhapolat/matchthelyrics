"""Gerçek modellerle uçtan uca test (Demucs + MMS). GPU ve ffmpeg gerektirir; ilk çalıştırmada ~1.3 GB model iner.

Çalıştırmak için:  pytest -m gpu
"""
import shutil

import pytest

from conftest import FIXTURES, SYNTHETIC_LINES

torch = pytest.importorskip("torch")
pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA yok"),
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg yok"),
]

MAX_ERR = 0.30  # saniye, satır sınırı başına


@pytest.fixture(scope="module")
def pipeline_result():
    from app import align, audio

    vocals, sr = audio.separate_vocals(FIXTURES / "synthetic_song.mp3")
    wav16 = audio.resample_mono(vocals[0], sr, align.SR)
    return wav16, align.align(wav16, SYNTHETIC_LINES)


def test_vocals_extracted(pipeline_result):
    wav16, _ = pipeline_result
    assert 30 < len(wav16) / 16000 < 40
    assert abs(wav16).max() > 0.05


def test_alignment_close_to_truth(pipeline_result, truth):
    _, results = pipeline_result
    assert len(results) == len(truth)
    for r, g in zip(results, truth):
        assert abs(r["start"] - g["start"]) < MAX_ERR, (r, g)
        assert abs(r["end"] - g["end"]) < MAX_ERR, (r, g)
        assert r["words"] and 0 <= r["score"] <= 1


def test_alignment_monotonic(pipeline_result):
    _, results = pipeline_result
    for a, b in zip(results, results[1:]):
        assert a["start"] < a["end"] <= b["start"] + 0.05


def test_anchor_fixes_a_misplaced_line(pipeline_result, truth):
    """Satır 3 elle doğru yere çapalanır; çevresindeki satırlar çapanın iki yanına doğru yerleşir."""
    from app import align

    wav16, _ = pipeline_result
    anchors = {3: (truth[3]["start"], truth[3]["end"])}
    res = align.align(wav16, SYNTHETIC_LINES, anchors)
    assert (res[3]["start"], res[3]["end"]) == anchors[3]
    assert res[3]["words"], "çapalı satırın kelime zamanları da hizalanmalı"
    for i, (r, g) in enumerate(zip(res, truth)):
        assert abs(r["start"] - g["start"]) < MAX_ERR and abs(r["end"] - g["end"]) < MAX_ERR, (i, r, g)
    assert res[2]["end"] <= anchors[3][0] + 1e-6 and res[4]["start"] >= anchors[3][1] - 1e-6


def test_wrong_anchor_constrains_neighbours(pipeline_result):
    """Çapa yanlış yere konsa bile komşu satırlar çapayla çakışmaz (çapa her zaman kazanır)."""
    from app import align

    wav16, _ = pipeline_result
    res = align.align(wav16, SYNTHETIC_LINES, {1: (5.0, 6.0)})
    assert res[0]["end"] <= 5.0 + 1e-6
    assert all(r["start"] >= 6.0 - 1e-6 for r in res[2:])


def test_punctuation_only_line_is_interpolated(pipeline_result):
    from app import align

    wav16, _ = pipeline_result
    lines = SYNTHETIC_LINES[:2] + [{"text": "— … —", "lang": "en"}] + SYNTHETIC_LINES[2:]
    res = align.align(wav16, lines)
    assert res[2]["words"] == []
    assert res[1]["end"] <= res[2]["start"] + 1e-6 and res[2]["end"] >= res[2]["start"] + 0.5
