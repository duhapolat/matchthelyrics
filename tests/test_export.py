import pytest

from app import export


def line(text, start, end, words=None, aligned_text=None):
    l = {"text": text, "start": start, "end": end, "words": words or []}
    if aligned_text is not None:
        l["aligned_text"] = aligned_text
    return l


W = [{"i": 0, "start": 10.0, "end": 10.5}, {"i": 1, "start": 10.6, "end": 11.0}, {"i": 2, "start": 11.2, "end": 12.0}]


def test_word_times_unchanged_line_keeps_alignment():
    out = export.word_times(line("bir iki üç", 10.0, 12.0, W))
    assert out == [("bir", 10.0, 10.5), ("iki", 10.6, 11.0), ("üç", 11.2, 12.0)]


def test_word_times_follow_moved_and_stretched_line():
    # kullanıcı satırı 2 sn ileri aldı ve iki kat uzattı
    out = export.word_times(line("bir iki üç", 12.0, 16.0, W))
    assert out == [("bir", 12.0, 13.0), ("iki", 13.2, 14.0), ("üç", 14.4, 16.0)]


def test_word_times_fill_unaligned_words():
    words = [{"i": 0, "start": 1.0, "end": 1.5}, {"i": 2, "start": 2.5, "end": 3.0}]
    out = export.word_times(line("eins — drei", 1.0, 3.0, words))
    assert out[1][0] == "—" and out[1][1] == pytest.approx(1.5) and out[1][2] == pytest.approx(2.5)


def test_word_times_even_split_when_text_edited():
    out = export.word_times(line("aa bbbb", 0.0, 3.0, W, aligned_text="bir iki üç"))
    assert out == [("aa", 0.0, 1.0), ("bbbb", 1.0, 3.0)]


def test_word_times_no_alignment_and_empty():
    assert [w for w, *_ in export.word_times(line("x y", 0, 1))] == ["x", "y"]
    assert export.word_times(line("   ", 0, 1)) == []


def test_word_times_monotonic_and_inside_line():
    out = export.word_times(line("a b c d", 5.0, 9.0, [{"i": 1, "start": 6.0, "end": 6.5}]))
    times = [t for _, s, e in out for t in (s, e)]
    assert times == sorted(times) and times[0] >= 5.0 and times[-1] <= 9.0 + 1e-9


def test_lrc_line_level():
    out = export.lrc([line("ikinci", 65.5, 67.0), line("birinci", 1.234, 3.0)], title="Şarkı")
    assert out.splitlines() == [
        "[ti:Şarkı]",
        "[00:01.23]birinci",
        "[00:03.00]",          # uzun boşluk: ekranı temizle
        "[01:05.50]ikinci",
        "[01:07.00]",
    ]


def test_lrc_no_clear_line_for_tight_gap():
    out = export.lrc([line("a", 1, 2), line("b", 2.2, 3)])
    assert "[00:02.00]\n" not in out


def test_lrc_word_level():
    out = export.lrc([line("bir iki üç", 10.0, 12.0, W)], words=True)
    assert "[00:10.00]<00:10.00>bir <00:10.60>iki <00:11.20>üç <00:12.00>" in out


def test_ass_karaoke():
    out = export.ass([line("bir iki üç", 10.0, 12.0, W)], title="T")
    assert "[V4+ Styles]" in out and "Title: T" in out
    dlg = [l for l in out.splitlines() if l.startswith("Dialogue:")]
    assert dlg == ["Dialogue: 0,0:00:10.00,0:00:12.00,Karaoke,,0,0,0,karaoke,"
                   "{\\k50}bir {\\k10}{\\k40}iki {\\k20}{\\k80}üç"]


def test_ass_escapes_override_braces():
    out = export.ass([line("a{b}c", 0, 1)])
    assert "{b}" not in out.split("[Events]")[1].split("Dialogue:")[1]
