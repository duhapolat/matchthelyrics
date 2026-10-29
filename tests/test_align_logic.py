"""Model gerektirmeyen hizalama mantığı: çapa pencereleri ve şüpheli satır işaretleme."""
from app.align import flag_suspects, segments


def test_segments_without_anchors():
    assert segments(3, {}, 60.0) == [([0, 1, 2], 0.0, 60.0)]


def test_segments_with_anchors():
    out = segments(6, {2: (20.0, 24.0), 3: (25.0, 27.0)}, 60.0)
    assert out == [
        ([0, 1], 0.0, 20.0),
        ([2], 20.0, 24.0),
        ([3], 25.0, 27.0),
        ([4, 5], 27.0, 60.0),
    ]


def test_segments_anchor_first_and_last():
    assert segments(3, {0: (1.0, 2.0), 2: (50.0, 55.0)}, 60.0) == [
        ([0], 1.0, 2.0), ([1], 2.0, 50.0), ([2], 50.0, 55.0)]


def _line(score, **kw):
    return {"raw": {"start": 0, "end": 1}, "words": [{"score": score}], **kw}


def test_flag_suspects_relative_and_absolute():
    lines = [_line(0.22), _line(0.20), _line(0.24), _line(0.04), _line(0.09)]
    flags = [l["suspect"] for l in flag_suspects(lines)]
    # medyan 0.20 → eşik max(0.08, 0.08) = 0.08
    assert flags == [False, False, False, True, False]


def test_flag_suspects_relative_threshold_in_confident_song():
    lines = [_line(0.6), _line(0.6), _line(0.6), _line(0.2)]
    assert [l["suspect"] for l in flag_suspects(lines)] == [False, False, False, True]


def test_flag_suspects_skips_anchors_and_unaligned():
    lines = [_line(0.2), _line(0.01, anchor=True), {"words": []}, _line(0.0)]
    out = flag_suspects(lines)
    assert [l["suspect"] for l in out] == [False, False, False, True]
    assert out[0]["score"] == 0.2
