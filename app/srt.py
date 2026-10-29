"""SRT okuma / yazma."""
import re


def _ts(sec):
    ms = int(round(max(sec, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write(lines):
    blocks = []
    for i, line in enumerate(sorted(lines, key=lambda l: l["start"]), 1):
        blocks.append(f"{i}\n{_ts(line['start'])} --> {_ts(line['end'])}\n{line['text']}\n")
    return "\n".join(blocks)


_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def parse(text):
    """SRT metninden [{text, start, end}] döndürür. Çok satırlı altyazılar tek satıra birleşir."""
    text = text.replace("﻿", "").replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = [r for r in block.split("\n") if r.strip()]
        for i, row in enumerate(rows):
            m = _TIME.search(row)
            if m:
                g = m.groups()
                body = " ".join(rows[i + 1:]).strip()
                if body:
                    out.append({"text": body, "start": _sec(*g[:4]), "end": _sec(*g[4:])})
                break
    return out
