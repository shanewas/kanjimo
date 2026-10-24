"""One-off delta over the shipped content (2026-10-17): distinct kanji keywords and words for kanji
the old minimum pass starved. Uses the build's own functions; touches only the affected records.

    python delta.py CUR_DIR JMDICT_GZ KEYWORDS_CSV OUT_DIR
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\san\japanese-study\tools\open")
import kanji as K  # noqa: E402
import readers  # noqa: E402
import vocab as V  # noqa: E402
from common import hira, read_csv  # noqa: E402

TYPE_ORDER = {"radical": 0, "kanji": 1, "vocabulary": 2}
cur, jm, kwcsv, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])

levels = {}
for kind in ("items", "cards"):
    for f in sorted((cur / kind).glob("level-*.json")):
        levels[(kind, int(f.stem[-2:]))] = json.loads(f.read_text(encoding="utf-8"))
index = json.loads((cur / "search-index.json").read_text(encoding="utf-8"))
items = {it["id"]: it for (k, _), d in levels.items() if k == "items" for it in d["items"]}
cards = {c["id"]: c for (k, _), d in levels.items() if k == "cards" for c in d["cards"]}
idx = {r["id"]: r for r in index["records"]}
kanji = {it["glyph"]: it for it in items.values() if it["type"] == "kanji"}
touched = {"keyword": [], "vocab_of_keyword": [], "new_vocab": []}

# 1. distinct keywords: new keyword first, every earlier answer still accepted
for r in read_csv(kwcsv):
    g, kw = r["kanji"], r["keyword"]
    rid = "kanji/" + g
    for lst in (items[rid]["meanings"], cards[rid + ":meaning"]["answers"], idx[rid]["meanings"]):
        old = [m for m in lst if m != kw]
        lst[:] = [kw] + old
    touched["keyword"].append(rid)
renamed = set(touched["keyword"])
touched["vocab_of_keyword"] = sorted(rid for rid, it in items.items()
                                     if it["type"] == "vocabulary" and renamed & set(it.get("requires", [])))

# 2. words for kanji below the minimum, with the fixed minimum pass
count = defaultdict(int)
for it in items.values():
    if it["type"] == "vocabulary":
        for p in it.get("requires", []):
            count[p[len("kanji/"):]] += 1
short = [g for g in kanji if count[g] < V.MIN_PER]
kset = set(kanji)
entries, _ = readers.read_jmdict(jm, lambda e: any(set(k["text"]) & set(short) for k in e["k"]))
cand, _ = V.candidates(entries, kset, {})
cand, _ = V.dedupe_forms(cand)
have = {it["glyph"] for it in items.values() if it["type"] == "vocabulary"}
cand = [w for w in cand if w["form"] not in have]
readings = {g: kanji[g]["readings"] for g in kset}
teach = {g: kanji[g].get("teach") for g in kset}


def tier(k, w):
    rd = readings[k]
    hits = K.reading_hits(k, w["form"], hira(w["reading"]), rd.get("on") or [],
                          [x["stem"] for x in rd.get("kun") or [] if isinstance(x, dict)])
    t = teach.get(k)
    return 0 if t and (t["group"], t["reading"]) in hits else (1 if hits else 2)


new = {}
for g in sorted(short, key=lambda g: kanji[g]["level"]):
    pool = sorted((w for w in cand if g in w["kanji"] and w["form"] not in new),
                  key=lambda w: (tier(g, w), w["nf"] or 99, len(w["form"]), w["form"]))
    for w in pool[:V.MIN_PER - count[g]]:
        new[w["form"]] = w
        for k in w["kanji"]:
            count[k] += 1

# Pass 2 (owner, 10-17: "add place words"): a kanji still with no word may take an uncommon entry,
# place names included. _word() only keeps common or JLPT words, so every written form is passed
# as if listed, and the flag is cleared afterwards.
empty = [g for g in short if count[g] == 0]
if empty:
    E = set(empty)
    forms = {k["text"]: 1 for e in entries for k in e["k"]}
    relaxed = []
    for ent in entries:
        keb = next((k for k in ent["k"] if set(k["text"]) & E and not set(k["inf"]) & V.BAD_KEB
                    and V.form_ok(k["text"], kset)), None)
        if not keb:
            continue
        rebs = [r for r in ent["r"] if not r["nokanji"] and not set(r["inf"]) & V.BAD_REB
                and (not r["restr"] or keb["text"] in r["restr"])]
        senses = [s for s in ent["s"] if V.applies(s, keb["text"], rebs[0]["text"] if rebs else "")
                  and not set(s["misc"]) & V.BAD_MISC]
        if not rebs or not senses or senses[0]["pos"] == ["prt"]:
            continue
        w = V._word(ent, keb, rebs[0], rebs, senses, kset, forms, {})
        if w and w["form"] not in have and w["form"] not in new:
            w["jlpt"] = None
            relaxed.append(w)
    for g in sorted(empty, key=lambda g: kanji[g]["level"]):
        pool = sorted((w for w in relaxed if g in w["kanji"] and w["form"] not in new),
                      key=lambda w: (not w["common"], w["nf"] or 99, tier(g, w), len(w["form"]), w["form"]))
        for w in pool[:V.MIN_PER - count[g]]:
            new[w["form"]] = w
            for k in w["kanji"]:
                count[k] += 1

for w in new.values():
    lv = max(kanji[k]["level"] for k in w["kanji"])
    rid = "vocabulary/" + w["form"]
    rec = {"id": rid, "type": "vocabulary", "level": lv, "glyph": w["form"], "meanings": w["glosses"],
           "readings": w["readings"], "requires": ["kanji/" + k for k in w["kanji"]], "word_type": w["word_type"],
           "ent_seq": w["seq"], "nf": w["nf"], "jlpt": None, "sentences": [], "audio": [], "src": {"dict": "jmdict"}}
    levels[("items", lv)]["items"].append(rec)
    for prompt, answers in (("meaning", w["glosses"]), ("reading", w["readings"])):
        levels[("cards", lv)]["cards"].append({
            "id": rid + ":" + prompt, "record": rid, "level": lv, "type": "vocabulary", "prompt": prompt,
            "glyph": w["form"], "glyph_alt": "", "images": [], "answers": answers, "audio": [],
            "word_type": w["word_type"]})
    index["records"].append({"id": rid, "level": lv, "type": "vocabulary", "glyph": w["form"],
                             "meanings": w["glosses"], "readings": w["readings"], "requires": rec["requires"]})
    touched["new_vocab"].append(rid)
pos = {r["id"]: i for i, r in enumerate(index["records"])}
index["records"].sort(key=lambda r: (r["level"], TYPE_ORDER[r["type"]], pos[r["id"]]))

for (kind, lv), d in levels.items():
    p = out / kind / f"level-{lv:02d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
(out / "search-index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")),
                                       encoding="utf-8", newline="\n")
(out / "touched.json").write_text(json.dumps(touched, ensure_ascii=False, indent=1), encoding="utf-8")
still = [g for g in short if count[g] < V.MIN_PER]
print(f"keywords {len(touched['keyword'])}, vocabulary using them {len(touched['vocab_of_keyword'])}, "
      f"new words {len(new)} for {len(short)} short kanji, still short {len(still)}: {''.join(still)}")
for w in list(new.values())[:40]:
    print(" ", w["form"], w["reading"], w["glosses"][:2], w["nf"])
