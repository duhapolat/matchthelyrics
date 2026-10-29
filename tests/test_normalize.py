import pytest

from app.align import normalize_word, split_words


@pytest.mark.parametrize("word, lang, expected", [
    ("Işık", "tr", "isik"),
    ("İstanbul", "tr", "istanbul"),
    ("ÇOĞUL", "tr", "cogul"),
    ("şöyle", "tr", "soyle"),
    ("Straße", "de", "strase"),
    ("Mädchen", "de", "medchen"),
    ("Grüß", "de", "grus"),
    ("don't", "en", "don't"),
    ("don’t", "en", "don't"),
    ("café", "en", "cafe"),
    ("Hello,", "en", "hello"),
    ("'quoted'", "en", "quoted"),
    ("...", "en", ""),
    ("—", "de", ""),
])
def test_normalize(word, lang, expected):
    assert normalize_word(word, lang) == expected


def test_turkish_dotless_i_only_in_turkish():
    # Türkçe dışında büyük I normal i olur.
    assert normalize_word("Ich", "de") == "ich"
    assert normalize_word("Ilık", "tr") == "ilik"


@pytest.mark.parametrize("lang, expected", [("de", "zwei"), ("tr", "iki"), ("en", "two")])
def test_digits_spelled_per_language(lang, expected):
    assert normalize_word("2", lang) == expected


def test_output_only_alignable_chars():
    for w in ["Ärger!", "ğüşıöç", "x² ≠ y", "123abc"]:
        out = normalize_word(w, "tr").replace(" ", "")
        assert set(out) <= set("abcdefghijklmnopqrstuvwxyz'")


def test_split_words():
    assert split_words("  bir  iki\tüç \n") == ["bir", "iki", "üç"]
    assert split_words("   ") == []
