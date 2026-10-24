"""Packs generated mnemonics into the app's own/level-NN.json files.

    py -3.11 -I tools/mnemonics/pack.py --work BUILD/mnemonics --out CONTENT/own

Takes results.jsonl (model texts, last result per chunk wins) and fixed.json (vocabulary readings
written without a model). Meaning texts go on the item's meaning card, reading texts on its reading
card, which is where mergeOwn in app/content.js looks. Refuses output naming the scraped course.
"""
import argparse
import json
import sys
from pathlib import Path

FORBIDDEN = "wanikani"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--merge", action="store_true", help="update existing level files instead of replacing them")
    a = p.parse_args()
    facts = json.loads((a.work / "facts.json").read_text(encoding="utf-8"))
    fixed = json.loads((a.work / "fixed.json").read_text(encoding="utf-8"))
    texts: dict[str, dict] = {}
    for rec in map(json.loads, open(a.work / "results.jsonl", encoding="utf-8")):
        if rec.get("ok"):
            for it in rec["items"]:
                if it["id"] in facts:
                    texts[it["id"]] = it
    levels: dict[int, dict] = {}
    missing = []
    for rid, f in facts.items():
        cards = levels.setdefault(f["level"], {})
        t = texts.get(rid)
        if t and t["meaning"].strip():
            cards[f"{rid}:meaning"] = {"mnemonic_meaning": t["meaning"].strip()}
        else:
            missing.append(f"{rid}:meaning")
        if f["type"] == "radical":
            continue
        reading = (t or {}).get("reading", "").strip() if f.get("want_reading") else fixed.get(rid, "")
        if reading:
            cards[f"{rid}:reading"] = {"mnemonic_reading": reading}
        else:
            missing.append(f"{rid}:reading")
    a.out.mkdir(parents=True, exist_ok=True)
    if a.merge:  # an item that changed level leaves its old entry behind otherwise
        ours = {cid for cards in levels.values() for cid in cards}
        for f in sorted(a.out.glob("level-*.json")):
            old = json.loads(f.read_text(encoding="utf-8"))["cards"]
            mine = levels.setdefault(int(f.stem[-2:]), {})
            for cid, v in old.items():
                if cid not in ours:
                    mine[cid] = v
    for level, cards in sorted(levels.items()):
        body = json.dumps({"version": 1, "level": level, "cards": cards}, ensure_ascii=False, separators=(",", ":"))
        if FORBIDDEN in body.lower():
            print(f"refusing level {level}: it names the scraped course", file=sys.stderr)
            return 1
        (a.out / f"level-{level:02d}.json").write_text(body, encoding="utf-8", newline="\n")
    print(f"{sum(len(c) for c in levels.values())} card texts in {len(levels)} files, {len(missing)} missing")
    if missing:
        (a.work / "missing.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
