"""Builds mnemonic generation requests from a content tree (items/ + cards/).

    py -3.11 -I tools/mnemonics/prepare.py --content BUILD/open --out BUILD/mnemonics

Writes requests.jsonl (one Message Batches request per chunk of items) and fixed.json (vocabulary
reading lines that follow from the kanji, written here without a model). Reads open data only;
nothing under the repo's data/ directory. Stdlib only.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHUNK = 12
MODEL = "claude-opus-5-5"
VOICED = dict(zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
HANDAKU = dict(zip("はひふへほ", "ぱぴぷぺぽ"))
GEMINATE = set("つくちき")

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "meaning": {"type": "string"}, "reading": {"type": "string"}},
        "required": ["id", "meaning", "reading"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def variants(r: str, first: bool, last: bool) -> set[str]:
    out = {r}
    if not first and r[0] in VOICED:
        out.add(VOICED[r[0]] + r[1:])
    if not first and r[0] in HANDAKU:
        out.add(HANDAKU[r[0]] + r[1:])
    if not last and len(r) > 1 and r[-1] in GEMINATE:
        out |= {v[:-1] + "っ" for v in list(out)}
    return out


def kanji_readings(rec: dict) -> set[str]:
    rd = rec.get("readings") or {}
    out = set(rd.get("on") or [])
    for k in rd.get("kun") or []:
        if isinstance(k, dict):
            out.add(k["stem"])
            out.add(k["stem"] + k.get("okurigana", ""))
        elif k:
            out.add(k.replace(".", ""))
    return {kata_to_hira(r) for r in out if r}


def segment(glyph: str, reading: str, kanji: dict) -> list[tuple[str, str]] | None:
    """Splits the reading over the word's characters using known readings; None when it doesn't fit."""
    chars = list(glyph)
    reading = kata_to_hira(reading)

    def go(i: int, j: int):
        if i == len(chars):
            return [] if j == len(reading) else None
        c = chars[i]
        if c in kanji:
            cands = set()
            for r in kanji_readings(kanji[c]):
                cands |= variants(r, i == 0, i == len(chars) - 1)
        elif c == "々" and i > 0:
            prev = chars[i - 1]
            cands = set()
            for r in kanji_readings(kanji.get(prev, {})):
                cands |= variants(r, False, i == len(chars) - 1)
        else:
            cands = {kata_to_hira(c)}
        for r in sorted(cands, key=len, reverse=True):
            if reading.startswith(r, j):
                rest = go(i + 1, j + len(r))
                if rest is not None:
                    return [(c, r)] + rest
        return None

    return go(0, 0)


def taught_ok(c: str, r: str, kanji: dict, chars: str) -> bool:
    """True for kana, and for a kanji read with (a sound-changed form of) the reading its lesson taught."""
    if c not in kanji and c != "々":
        return True
    if c == "々":
        return True
    t = kata_to_hira(((kanji[c].get("teach") or {}).get("reading")) or "")
    if not t:
        return False
    i = chars.index(c)
    return r in variants(t, i == 0, i == len(chars) - 1)


def fixed_reading(parts: list[tuple[str, str]], kanji: dict) -> str:
    bits = []
    for c, r in parts:
        if c in kanji or c == "々":
            bits.append(f"{c} {r}")
    return "Read it with the readings you learned for each kanji: " + " + ".join(bits) + "."


def load(content: Path):
    items, cards = {}, {}
    for f in sorted((content / "items").glob("level-*.json")):
        for it in json.loads(f.read_text(encoding="utf-8"))["items"]:
            items[it["id"]] = it
    for f in sorted((content / "cards").glob("level-*.json")):
        for c in json.loads(f.read_text(encoding="utf-8"))["cards"]:
            cards[c["id"]] = c
    return items, cards


def answers(cards: dict, rid: str, part: str) -> list[str]:
    c = cards.get(f"{rid}:{part}")
    return list(c["answers"]) if c else []


def name_of(items: dict, cards: dict, rid: str) -> str:
    a = answers(cards, rid, "meaning")
    return a[0] if a else ((items.get(rid) or {}).get("meanings") or [""])[0]


def build(content: Path, out: Path, only: set | None = None) -> None:
    items, cards = load(content)
    onyomi = {r["reading"]: r["keyword"] for r in csv.DictReader(open(HERE / "onyomi.csv", encoding="utf-8"))}
    style = (HERE / "STYLE.md").read_text(encoding="utf-8")
    kanji = {it["glyph"]: it for it in items.values() if it["type"] == "kanji"}
    facts, fixed = {}, {}
    for rid, it in items.items():
        if only is not None and rid not in only:
            continue
        t = it["type"]
        f = {"id": rid, "type": t, "level": it["level"], "glyph": it.get("glyph") or "(drawn shape, no character)",
             "meaning": name_of(items, cards, rid)}
        if t == "radical":
            f["used_in_kanji"] = [name_of(items, cards, k) for k in it.get("used_by", [])[:4]]
        elif t == "kanji":
            f["also_accepted"] = answers(cards, rid, "meaning")[1:4]
            f["parts"] = [{"glyph": (items.get(p) or {}).get("glyph", ""), "name": name_of(items, cards, p)}
                          for p in it.get("parts") or it.get("requires") or []]
            teach = it.get("teach") or {}
            f["taught_reading"] = teach.get("reading", "")
            if teach.get("group") == "on":
                f["reading_kind"] = "on'yomi"
                f["reading_keyword"] = onyomi[teach["reading"]]
            else:
                f["reading_kind"] = "kun'yomi"
            f["want_reading"] = True
        else:
            f["also_accepted"] = answers(cards, rid, "meaning")[1:4]
            f["kanji"] = [{"glyph": (items.get(k) or {}).get("glyph", ""), "meaning": name_of(items, cards, k)}
                          for k in it.get("requires", [])]
            reading = (it.get("readings") or [""])[0]
            f["reading"] = reading
            if it.get("word_type"):
                f["word_type"] = it["word_type"]
            parts = segment(it["glyph"], reading, kanji) if reading else None
            if parts and all(taught_ok(c, r, kanji, chars=it["glyph"]) for c, r in parts):
                fixed[rid] = fixed_reading(parts, kanji)
                f["want_reading"] = False
            else:
                f["want_reading"] = True
                if parts:
                    f["reading_split"] = [{"glyph": c, "reads": r,
                                           "taught_reading": ((kanji.get(c) or {}).get("teach") or {}).get("reading", ""),
                                           **({"keyword": onyomi[r]} if r in onyomi else {})}
                                          for c, r in parts if c in kanji]
        facts[rid] = f

    order = sorted(facts.values(), key=lambda f: (f["level"], ["radical", "kanji", "vocabulary"].index(f["type"]), f["id"]))
    out.mkdir(parents=True, exist_ok=True)
    groups: dict[tuple, list] = {}
    for f in order:
        groups.setdefault((f["level"], f["type"]), []).append(f)
    n = 0
    with open(out / "requests.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for (level, t), fs in groups.items():
            for k in range(0, len(fs), CHUNK):
                chunk = fs[k:k + CHUNK]
                user = ("Write mnemonics for these items. Follow the style sheet. Return one entry per item, same ids. "
                        "Set reading to an empty string when want_reading is false or the item is a radical.\n\n"
                        + json.dumps(chunk, ensure_ascii=False, indent=1))
                req = {"custom_id": f"L{level:02d}-{t[0]}-{k // CHUNK:03d}", "params": {
                    "model": MODEL, "max_tokens": 16000,
                    "thinking": {"type": "adaptive"},
                    "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
                    "system": [{"type": "text", "text": style, "cache_control": {"type": "ephemeral"}}],
                    "messages": [{"role": "user", "content": user}]}}
                fh.write(json.dumps(req, ensure_ascii=False) + "\n")
                n += 1
    (out / "facts.json").write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    (out / "fixed.json").write_text(json.dumps(fixed, ensure_ascii=False, indent=0), encoding="utf-8")
    vocab = sum(1 for f in facts.values() if f["type"] == "vocabulary")
    print(f"{len(facts)} items, {n} requests, {len(fixed)}/{vocab} vocabulary readings fixed without a model")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--content", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--only", type=Path, help="file of item ids, one per line: regenerate just those")
    a = p.parse_args()
    if a.content.resolve().is_relative_to(HERE.parents[1] / "data"):
        print("refusing the repo's data/ directory", file=sys.stderr)
        return 1
    only = set(a.only.read_text(encoding="utf-8").split()) if a.only else None
    build(a.content, a.out, only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
