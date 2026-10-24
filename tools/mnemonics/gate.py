"""Near-copy gate for generated mnemonics (plan item 14).

    py -3.11 -I tools/mnemonics/gate.py RESULTS.jsonl [--fail-out FAILED_IDS]

A text fails when its word 3-gram Jaccard similarity against the reference text for the same card
reaches 0.10, or when it shares a run of 8 or more words with anything in the reference corpus.
The reference corpus is the personal copy under data/own; this script prints ids and scores only,
never reference text. Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORD = re.compile(r"[a-z']+")
JACCARD = 0.10
RUN = 8
FIELDS = {"meaning": ("mnemonic_meaning", "hint"), "reading": ("mnemonic_reading", "hint")}


def words(s: str) -> list[str]:
    return WORD.findall(s.lower())


def grams(ws: list[str], n: int) -> set[tuple]:
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


def load_reference():
    per_card, runs = {}, set()
    for f in sorted((REPO / "data" / "own").glob("level-*.json")):
        for cid, v in json.loads(f.read_text(encoding="utf-8"))["cards"].items():
            for part, keys in FIELDS.items():
                ws = []
                for k in keys:
                    ws += words(v.get(k) or "")
                per_card.setdefault(f"{cid.split(':')[0]}:{part}", set()).update(grams(ws, 3))
            for k in ("mnemonic_meaning", "mnemonic_reading", "hint"):
                runs |= grams(words(v.get(k) or ""), RUN)
    return per_card, runs


def check(text: str, ref3: set, runs: set) -> tuple[float, bool]:
    ws = words(text)
    g3 = grams(ws, 3)
    j = len(g3 & ref3) / len(g3 | ref3) if g3 and ref3 else 0.0
    return j, bool(grams(ws, RUN) & runs)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ids hold kanji; Windows defaults to cp1252/cp932
    p = argparse.ArgumentParser()
    p.add_argument("results", type=Path)
    p.add_argument("--fail-out", type=Path)
    a = p.parse_args()
    per_card, runs = load_reference()
    checked = failed = 0
    worst = 0.0
    bad_chunks, lines = set(), []
    latest = {}  # a regenerated chunk is appended; only its last result counts, as in pack.py
    for rec in map(json.loads, open(a.results, encoding="utf-8")):
        if rec.get("ok"):
            latest[rec["custom_id"]] = rec
    for rec in latest.values():
        for it in rec["items"]:
            for part in ("meaning", "reading"):
                text = it.get(part) or ""
                if not text:
                    continue
                checked += 1
                j, run = check(text, per_card.get(f"{it['id']}:{part}", set()), runs)
                worst = max(worst, j)
                if j >= JACCARD or run:
                    failed += 1
                    bad_chunks.add(rec["custom_id"])
                    lines.append(f"FAIL {it['id']}:{part} jaccard={j:.3f} run8={run}")
    for line in lines:
        print(line)
    print(f"checked {checked} texts, {failed} failed, worst jaccard {worst:.3f}")
    if a.fail_out:
        a.fail_out.write_text("\n".join(sorted(bad_chunks)) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
