from app import srt


def test_write_format_and_sorting():
    out = srt.write([
        {"text": "ikinci", "start": 5.5, "end": 7.25},
        {"text": "birinci", "start": 1.0, "end": 2.0},
    ])
    assert out == (
        "1\n00:00:01,000 --> 00:00:02,000\nbirinci\n\n"
        "2\n00:00:05,500 --> 00:00:07,250\nikinci\n"
    )


def test_timestamp_hours_and_rounding():
    out = srt.write([{"text": "x", "start": 3723.4567, "end": 3725.0}])
    assert "01:02:03,457 --> 01:02:05,000" in out


def test_negative_time_clamped():
    assert "00:00:00,000" in srt.write([{"text": "x", "start": -0.2, "end": 1}])


def test_roundtrip():
    lines = [{"text": "Satır bir", "start": 1.234, "end": 2.5}, {"text": "Zeile zwei", "start": 3.0, "end": 4.75}]
    parsed = srt.parse(srt.write(lines))
    assert parsed == lines


def test_parse_bom_crlf_dot_multiline():
    text = "﻿1\r\n00:00:01.5 --> 00:00:02,000\r\nilk\r\nikinci parça\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nson\r\n"
    parsed = srt.parse(text)
    assert parsed == [
        {"text": "ilk ikinci parça", "start": 1.5, "end": 2.0},
        {"text": "son", "start": 3.0, "end": 4.0},
    ]


def test_parse_skips_empty_and_garbage_blocks():
    text = "1\n00:00:01,000 --> 00:00:02,000\n\n\nçöp blok\n\n2\n00:00:03,000 --> 00:00:04,000\nmetin\n"
    assert srt.parse(text) == [{"text": "metin", "start": 3.0, "end": 4.0}]
