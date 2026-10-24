"""Kanji stage: inventory, keywords, readings, parts, ordering, taught reading.

Inventory rule: every KANJIDIC2 character with grade 1-6 or 8 (the joyo set).
Keyword rule: first KANJIDIC2 meaning after a mechanical clean-up; clashes are
reported, never hand-fixed here. Ordering: newspaper rank + grade tier +
shape weight (strokes, parts beyond two), cut into equal slices.
"""
import re
from collections import Counter, defaultdict

from common import KANA, hira, BuildError

JOYO_GRADES = {1, 2, 3, 4, 5, 6, 8}
TIER = {1: 0, 2: 0, 3: 1, 4: 1, 5: 2, 6: 2, 8: 3}
UNRANKED = 2600
PAREN = re.compile(r"\s*\([^)]*\)")
SKIP_MEANING = re.compile(r"^(radical\b|counter for\b)", re.I)
RADICAL_TAG = re.compile(r"\s+radical$", re.I)


def inventory(kd):
    return sorted(g for g, d in kd.items() if d["grade"] in JOYO_GRADES)


def clean_meaning(m):
    """'ice radical (no. 15)' -> 'ice'; 'radical (no. 5)' and 'counter for ...' -> ''."""
    if SKIP_MEANING.match(m or ""):
        return ""
    return RADICAL_TAG.sub("", " ".join(PAREN.sub("", m).split()).strip(" ,;"))


def meanings_of(kd, g):
    """Cleaned meanings, keyword first; a kanji whose only meanings are skipped
    phrases (箇: "counter for articles") keeps them with the parentheses removed."""
    out = []
    for skip in (True, False):
        for m in kd[g]["meanings"]:
            c = clean_meaning(m) if skip else " ".join(PAREN.sub("", m).split()).strip(" ,;")
            if c and c not in out:
                out.append(c)
        if out:
            break
    return out


def keyword_clashes(meanings):
    """{keyword: [glyphs]} for keywords shared by two or more kanji."""
    by = defaultdict(list)
    for g, ms in meanings.items():
        if ms:
            by[ms[0]].append(g)
    return {k: v for k, v in sorted(by.items()) if len(v) > 1}


def readings_of(kd, g):
    on, kun, seen = [], [], set()
    for r in kd[g]["on"]:
        h = hira(r)
        if h not in on:
            on.append(h)
    for r in kd[g]["kun"]:
        stem, _, oku = r.strip("-").partition(".")
        if (stem, oku) not in seen and stem:
            seen.add((stem, oku))
            kun.append({"stem": stem, "okurigana": oku})
    return {"on": on, "kun": kun, "nanori": list(dict.fromkeys(kd[g]["nanori"]))}


def flat_readings(r):
    out = []
    for x in r["on"] + [k["stem"] for k in r["kun"]] + r["nanori"]:
        if x not in out:
            out.append(x)
    return out


def parts_of(g, kvg):
    """[(element, position)] from KanjiVG; a kanji with one named part plus
    loose strokes keeps that one part (its lesson says "plus a stroke").

    KRADFILE is not a fallback: its lines index every visible element
    (未 -> 木 丨 二 ハ 亠), which is not a decomposition.
    """
    v = kvg.get(g)
    return [(p["element"], p["position"]) for p in v["parts"]] if v else []


def score(g, kd, nparts):
    d = kd[g]
    freq = d["freq"] or UNRANKED
    tier = TIER.get(d["grade"], 4)
    return freq + 150 * tier + 20 * d["strokes"] + 60 * max(0, nparts - 2)


def order(glyphs, kd, nparts):
    return sorted(glyphs, key=lambda g: (score(g, kd, nparts[g]), kd[g]["strokes"], ord(g)))


def slice_levels(ordered, nlevels):
    per = len(ordered) / nlevels
    return {g: min(nlevels, int(i / per) + 1) for i, g in enumerate(ordered)}


def reading_hits(k, form, reading, on, kun_stems):
    """Which of kanji k's readings the word (form, reading) exhibits."""
    hits = set()
    rest = form.replace(k, "")
    rest_kana = KANA.match(rest) is not None
    for r in on:
        if r and r in reading and not (len(r) == 1 and len(form) > 1 and rest and not rest_kana):
            hits.add(("on", r))
    for s in kun_stems:
        if not s:
            continue
        if form.startswith(k) and rest_kana:
            if reading.startswith(s):
                hits.add(("kun", s))
        elif s in reading and len(s) >= 2:
            hits.add(("kun", s))
    return hits


def teach_reading(k, readings, words, override=None):
    """{group, reading} by vocabulary usage; ties favour on'yomi; else first listed."""
    on, kun = readings["on"], [x["stem"] for x in readings["kun"]]
    if override:
        grp, rd = override
        pool = on if grp == "on" else kun
        if rd not in pool:
            raise BuildError("reading override %s %s %s is not a listed reading" % (k, grp, rd))
        return {"group": grp, "reading": rd, "count": -1}
    count = Counter()
    for form, reading in words:
        for hit in reading_hits(k, form, reading, on, kun):
            count[hit] += 1
    cands = [("on", r) for r in on] + [("kun", r) for r in kun]
    if not cands:
        return None
    best = sorted(cands, key=lambda c: (-count[c], c[0] != "on", cands.index(c)))[0]
    return {"group": best[0], "reading": best[1], "count": count[best]}
