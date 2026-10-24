#!/usr/bin/env python3
"""Validate a built output directory; exit 1 on any failure.

Usage: py -3.11 -I tools/open/validate.py <dir>

Gates (content report section 5.4 minus the mnemonic gates): counts in range
on a full build, every kanji/component/word complete, sentence and audio
rules (both authors on a Tatoeba sentence), component names off
overrides/blocked-names.csv (which must exist), every `src` resolving in
LICENSES.json, an acyclic dependency graph
with prerequisites at or below the item's level, level sizes in bounds, the
JSON formatting contract, and no mention of the scraped course anywhere.
"""
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (FORBIDDEN, LEVELS, LICENSE_OPEN, OVERRIDES, BuildError, dumps, name_key,  # noqa: E402
                    read_blocklist, read_json, setup, sha256_file)
from vocab import WORD_TYPES  # noqa: E402

KANJI_RANGE, COMP_RANGE, VOCAB_RANGE = (2100, 2140), (380, 520), (6000, 7000)
SIZE_BAND = (0.4, 1.4)         # of the mean items per level; at 60 levels the rare-kanji tail runs 68-209 around 153
TYPE_PREFIX = {"radical": "radical/", "kanji": "kanji/", "vocabulary": "vocabulary/"}


class Check:
    def __init__(self):
        self.errors = []

    def __call__(self, ok, msg):
        if not ok:
            self.errors.append(msg)
        return ok


def walk(root):
    for base, _, files in os.walk(root):
        for f in files:
            yield os.path.join(base, f)


def validate(root, blocklist_path=os.path.join(OVERRIDES, "blocked-names.csv")):
    c = Check()
    try:
        blocklist = read_blocklist(blocklist_path)
    except BuildError as e:
        c(False, str(e))
        blocklist = []
    blocked_pairs = {(b["glyph"], name_key(b["name"])) for b in blocklist}
    blocked_names = {name_key(b["name"]) for b in blocklist}
    for req in ("search-index.json", "LICENSES.json", "ATTRIBUTION.json", "attribution.md",
                "sources.json", "media-manifest.json", "report.json"):
        c(os.path.exists(os.path.join(root, req)), "missing " + req)
    if c.errors:
        return c, {}
    report = read_json(os.path.join(root, "report.json"))
    lo, hi = (int(x) for x in report["levels_built"].split("-"))
    full = (lo, hi) == (1, LEVELS)

    for path in walk(root):
        with open(path, "rb") as f:
            raw = f.read()
        c(not raw.startswith(b"\xef\xbb\xbf"), "BOM in " + path)
        c(FORBIDDEN not in raw.decode("utf-8", "replace").lower(), "forbidden string in " + path)
        if path.endswith(".json"):
            c(b"\r" not in raw, "CR in " + path)
            c(raw.decode("utf-8") == dumps(read_json(path)), "not in canonical form (sorted keys, indent 1, LF): " + path)

    lic = read_json(os.path.join(root, "LICENSES.json"))
    licenses, sources = lic["licenses"], lic["sources"]
    for name, s in sources.items():
        c(s["license"] in licenses, "source %s has unknown licence %s" % (name, s["license"]))

    index = read_json(os.path.join(root, "search-index.json"))
    c(index.get("version") == 2 and index.get("license") == LICENSE_OPEN and index.get("attribution"),
      "search-index header")
    c(index.get("generated") == sha256_file(os.path.join(root, "sources.json")),
      "search-index.generated is not the sha256 of sources.json")
    records = {}
    for r in index["records"]:
        c(r["id"] not in records, "duplicate index id " + r["id"])
        c(r["id"].startswith(TYPE_PREFIX.get(r["type"], "?")), "id/type mismatch " + r["id"])
        c(lo <= r["level"] <= hi, "level out of range " + r["id"])
        records[r["id"]] = r

    items, cards = {}, {}
    for lv in range(lo, hi + 1):
        ip, cp = (os.path.join(root, d, "level-%02d.json" % lv) for d in ("items", "cards"))
        if not c(os.path.exists(ip) and os.path.exists(cp), "missing level files for %d" % lv):
            continue
        for rec in read_json(ip)["items"]:
            c(rec["level"] == lv, "item %s in wrong level file" % rec["id"])
            c(rec["id"] not in items, "duplicate item " + rec["id"])
            items[rec["id"]] = rec
        for card in read_json(cp)["cards"]:
            c(card["level"] == lv, "card %s in wrong level file" % card["id"])
            c(card["id"] not in cards, "duplicate card " + card["id"])
            cards[card["id"]] = card
    c(set(items) == set(records), "items and index differ: %d only in items, %d only in index"
      % (len(set(items) - set(records)), len(set(records) - set(items))))

    users = defaultdict(list)
    for rec in items.values():
        for dep in rec["requires"]:
            users[dep].append(rec["id"])
    for rid, rec in items.items():
        for k, v in rec["src"].items():
            c(v in sources, "%s src.%s=%s not in LICENSES.json" % (rid, k, v))
        for dep in rec["requires"]:
            if c(dep in items, "%s requires missing %s" % (rid, dep)):
                c(items[dep]["level"] <= rec["level"], "%s (level %d) requires %s (level %d)"
                  % (rid, rec["level"], dep, items[dep]["level"]))
        for img in rec.get("images", []) + [p["image"] for p in rec.get("inline_parts", []) if p["image"]]:
            c(os.path.exists(os.path.join(root, *img.split("/"))), "%s image missing %s" % (rid, img))
        t = rec["type"]
        if t == "kanji":
            rd = rec["readings"]
            c(bool(rec["meanings"]), rid + " has no meaning")
            c(bool(rd["on"] or rd["kun"]), rid + " has no on or kun reading")
            c(bool(rec["parts"]) or rec["atomic"] or rec["inline_parts"], rid + " has no parts and is not atomic")
            pool = rd["on"] if rec["teach"]["group"] == "on" else [k["stem"] for k in rd["kun"]]
            c(rec["teach"]["reading"] in pool, rid + " teach reading not in its list")
            c(all(d.startswith("radical/") or d.startswith("kanji/") for d in rec["requires"]), rid + " bad requires")
        elif t == "radical":
            c(bool(rec["meanings"] and rec["meanings"][0]), rid + " has no name")
            c(bool(rec["glyph"]) or bool(rec["images"]), rid + " has neither glyph nor image")
            key = name_key(rec["meanings"][0] if rec["meanings"] else "")
            c((rec["glyph"], key) not in blocked_pairs, rid + " name is on the blocklist for this glyph")
            c(rec["src"].get("name") == "kanjidic2" or key not in blocked_names, rid + " name is on the blocklist")
            if c(bool(users.get(rid)), rid + " has no user"):
                c(rec["level"] <= min(items[u]["level"] for u in users[rid]), rid + " taught after a user")
        else:
            c(bool(rec["readings"]), rid + " has no reading")
            c(bool(rec["meanings"]), rid + " has no keyword")
            c(all(d.startswith("kanji/") for d in rec["requires"]), rid + " requires non-kanji")
            c(all(lab in WORD_TYPES for lab in rec["word_type"].split(", ")), rid + " word_type " + rec["word_type"])
            c(isinstance(rec.get("ent_seq"), int) or rec["src"].get("dict") == "own", rid + " has no ent_seq")
        ids = set()
        for s in rec["sentences"]:
            c(8 <= len(s["ja"]) <= 30, "%s sentence %s length" % (rid, s["id"]))
            c(bool(s["en"].strip()) and bool(s["author"].strip()), "%s sentence %s english/author" % (rid, s["id"]))
            c(s["licence"] in licenses and s["source"] in sources, "%s sentence %s licence" % (rid, s["id"]))
            if s["source"] == "tatoeba":
                c(isinstance(s.get("en_id"), int) and bool((s.get("en_author") or "").strip()),
                  "%s sentence %s english id/author" % (rid, s["id"]))
            c(s["id"] not in ids, "%s duplicate sentence %s" % (rid, s["id"]))
            ids.add(s["id"])
        c(len(rec["sentences"]) <= 3, rid + " more than three sentences")
        c(len(rec["audio"]) <= 2, rid + " more than two audio entries")
        for a in rec["audio"]:
            c(a.get("source") in sources and a.get("licence") in licenses and a.get("url") and a.get("content_type"),
              rid + " audio entry incomplete")

    per_record = Counter(card["record"] for card in cards.values())
    for rid, rec in items.items():
        want = 1 if rec["type"] == "radical" else 2
        c(per_record[rid] == want, "%s has %d cards, expected %d" % (rid, per_record[rid], want))
    for cid, card in cards.items():
        c(card["record"] in items and bool(card["answers"]), "card %s record/answers" % cid)

    state = {}

    def dfs(rid):
        state[rid] = 1
        for dep in items[rid]["requires"]:
            if dep in items and (state.get(dep) == 1 or (state.get(dep) is None and dfs(dep))):
                return True
        state[rid] = 2
        return False
    sys.setrecursionlimit(10000)
    c(not any(dfs(rid) for rid in items if rid not in state), "dependency cycle")

    manifest = read_json(os.path.join(root, "media-manifest.json"))["files"]
    audio_urls = {a["url"] for rec in items.values() for a in rec["audio"]}
    c({m["url"] for m in manifest} == audio_urls, "media-manifest and audio entries differ")

    n = Counter(rec["type"] for rec in items.values())
    sizes = Counter(rec["level"] for rec in items.values())
    kanji_levels = Counter(rec["level"] for rec in items.values() if rec["type"] == "kanji")
    if full:
        c(KANJI_RANGE[0] <= n["kanji"] <= KANJI_RANGE[1], "kanji count %d outside %s" % (n["kanji"], KANJI_RANGE))
        c(COMP_RANGE[0] <= n["radical"] <= COMP_RANGE[1], "component count %d outside %s" % (n["radical"], COMP_RANGE))
        c(VOCAB_RANGE[0] <= n["vocabulary"] <= VOCAB_RANGE[1], "vocabulary count %d outside %s" % (n["vocabulary"], VOCAB_RANGE))
        mean = len(items) / LEVELS
        for lv in range(1, LEVELS + 1):
            c(SIZE_BAND[0] * mean <= sizes[lv] <= SIZE_BAND[1] * mean, "level %d has %d items (band %d-%d)"
              % (lv, sizes[lv], SIZE_BAND[0] * mean, SIZE_BAND[1] * mean))
            c(kanji_levels[lv] > 0, "level %d has no kanji" % lv)

    words = [rec for rec in items.values() if rec["type"] == "vocabulary"]
    stats = {"kanji": n["kanji"], "components": n["radical"], "words": n["vocabulary"], "levels": hi - lo + 1,
             "cards": len(cards), "sentences_1": sum(1 for w in words if w["sentences"]),
             "sentences_3": sum(1 for w in words if len(w["sentences"]) >= 3),
             "native_audio": sum(1 for w in words if w["audio"])}
    return c, stats


def main(argv=None):
    setup()
    root = (argv or sys.argv[1:])[0]
    c, s = validate(root)
    if s:
        nw = max(s["words"], 1)
        print("kanji %d, components %d, words %d, levels %d, cards %d" % (s["kanji"], s["components"], s["words"], s["levels"], s["cards"]))
        print("sentences: >=1 %d (%.1f%%), >=3 %d (%.1f%%); native audio %d (%.1f%%)" % (
            s["sentences_1"], 100.0 * s["sentences_1"] / nw, s["sentences_3"], 100.0 * s["sentences_3"] / nw,
            s["native_audio"], 100.0 * s["native_audio"] / nw))
    for e in c.errors[:40]:
        print("ERROR: " + e)
    if len(c.errors) > 40:
        print("... %d more" % (len(c.errors) - 40))
    print("%d errors" % len(c.errors))
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())
