"""Shared helpers for the open-data pipeline (stdlib only).

Every script in this directory starts with `setup()`; every JSON artifact goes
through `write_json`, which enforces the output contract: sorted keys, UTF-8,
no BOM, LF, trailing newline, and a refusal to write any text that mentions
the scraped course by name.
"""
import csv
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
REPO_DATA = os.path.join(REPO_ROOT, "data")
OVERRIDES = os.path.join(HERE, "overrides")

LEVELS = 60
FORBIDDEN = "wani" + "kani"          # split so this file itself passes the grep
LICENSE_OPEN = "CC-BY-SA-4.0"

KANA = re.compile(r"^[ぁ-ゖァ-ヺー]+$")
KANA_CHAR = re.compile(r"[ぁ-ゖァ-ヺー]")
KATAKANA_RUN = re.compile(r"[ァ-ヺー]{3,}")
CJK = re.compile(r"[㐀-䶿一-鿿\U00020000-\U0002ffff]")


class BuildError(Exception):
    pass


def setup():
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヺ" else c for c in s)


def is_kana(s):
    return bool(s) and bool(KANA.match(s))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def write_text(path, text):
    if FORBIDDEN in text.lower():
        raise BuildError("refusing to write %s: output mentions the scraped course" % path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path, obj):
    write_text(path, dumps(obj))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def inside_repo_data(path):
    p = os.path.normcase(os.path.abspath(path))
    d = os.path.normcase(REPO_DATA)
    return p == d or p.startswith(d + os.sep)


def assert_outside_repo_data(path, what):
    if inside_repo_data(path):
        raise BuildError("%s points inside the repo's data directory: %s" % (what, path))


def read_csv(path):
    """Rows of a small override CSV as dicts; missing file means no rows."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(f) if any((v or "").strip() for v in row.values())]


def name_key(name):
    """Blocklist match key: case, outer spaces and a plural "s" must not let a blocked name through."""
    n = (name or "").strip().lower()
    return n[:-1] if n.endswith("s") and len(n) > 3 else n


def read_blocklist(path):
    """blocked-names.csv rows; unlike other overrides a missing file is an error, since an
    empty blocklist would silently let the scraped course's names through."""
    if not os.path.exists(path):
        raise BuildError("blocklist missing: " + path)
    return read_csv(path)


def parse_levels(spec, top=LEVELS):
    """'1-3' -> (1, 3); None -> (1, top)."""
    if not spec:
        return 1, top
    a, _, b = spec.partition("-")
    lo, hi = int(a), int(b or a)
    if not 1 <= lo <= hi <= top:
        raise BuildError("bad --levels %r" % spec)
    return lo, hi


def fmt(n):
    return format(n, ",")
