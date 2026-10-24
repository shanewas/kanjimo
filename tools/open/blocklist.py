#!/usr/bin/env python3
"""Build overrides/blocked-names.csv: component names the product must never use.

Usage:
  py -3.11 -I tools/open/blocklist.py <app search-index.json> <kanjidic2.xml.gz> [out csv]

The app's current data is read only to list the radical names it uses that
are not a dictionary meaning of the same glyph (the course's own inventions),
the way track-b-measure/radical_name_overlap.py measures them. Nothing else
from that file is kept. The build refuses those names for its components.
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OVERRIDES, read_json, setup  # noqa: E402
from kanji import clean_meaning  # noqa: E402
from readers import read_kanjidic2  # noqa: E402


def main(argv):
    setup()
    index, kd_path = argv[0], argv[1]
    out = argv[2] if len(argv) > 2 else os.path.join(OVERRIDES, "blocked-names.csv")
    kd, _ = read_kanjidic2(kd_path)
    rows, generic = [], 0
    for r in read_json(index)["records"]:
        if r["type"] != "radical" or not r["meanings"]:
            continue
        name = r["meanings"][0].strip().lower()
        glyph = r.get("glyph") or ""
        raw = [m.lower() for m in kd.get(glyph, {}).get("meanings", [])]
        dict_names = {clean_meaning(m) for m in raw} | set(raw)
        if name in dict_names or any(re.search(r"\b%s\b" % re.escape(name), m) for m in raw):
            generic += 1
            continue
        rows.append((glyph, name))
    rows.sort()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["glyph", "name"])
        w.writerows(rows)
    print("radical names read: %d, dictionary meanings (allowed): %d, blocked: %d -> %s"
          % (len(rows) + generic, generic, len(rows), out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
