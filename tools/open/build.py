#!/usr/bin/env python3
"""Build the open study content from the vendored sources (stdlib only).

Usage:
  py -3.11 -I tools/open/build.py --vendor DIR --out DIR [--levels 1-3] [--overrides DIR]

Stages: kanji -> components -> vocabulary -> levels -> sentences -> audio -> pack.
Prints counts per stage; exits 1 on any inconsistency. Output is deterministic:
no timestamps, sorted keys, `generated` = sha256 of sources.json.
"""
import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (LEVELS, OVERRIDES, BuildError, assert_outside_repo_data, fmt,  # noqa: E402
                    hira, parse_levels, read_blocklist, read_csv, read_json, setup, sha256_file)
import readers  # noqa: E402
import kanji as K  # noqa: E402
import components as C  # noqa: E402
import vocab as V  # noqa: E402
from levels import word_levels  # noqa: E402
from sentences import select_sentences  # noqa: E402
from audio import match_audio  # noqa: E402
import pack as P  # noqa: E402

TYPE_ORDER = {"radical": 0, "kanji": 1, "vocabulary": 2}


class Timer:
    def __init__(self):
        self.t = time.time()

    def lap(self):
        now = time.time()
        d, self.t = now - self.t, now
        return "%.1fs" % d


def source_paths(vendor):
    srcs = read_json(os.path.join(vendor, "sources.json"))
    paths = {s["name"]: os.path.join(vendor, *s["file"].split("/")) for s in srcs["sources"]}
    # the vendor tree can change after fetch.py verified it; `generated` names
    # these hashes, so the files read must still be the files pinned
    for s in srcs["sources"]:
        p = paths[s["name"]]
        if not os.path.exists(p):
            raise BuildError("vendored file missing: " + p)
        got = sha256_file(p)
        if got != s["sha256"]:
            raise BuildError("sha256 mismatch for %s: sources.json has %s, file is %s" % (s["file"], s["sha256"], got))
    versions = {s["name"]: s["version"] for s in srcs["sources"] if s.get("version")}
    with open(os.path.join(vendor, "sources.json"), encoding="utf-8", newline="") as f:
        text = f.read()
    return paths, versions, text, srcs["fetched"]


def build(vendor, out, lo, hi, overrides):
    timer = Timer()
    for p in (vendor, out, overrides):
        assert_outside_repo_data(p, "input/output path")
    paths, versions, sources_text, fetched = source_paths(vendor)
    versions["tatoeba"] = versions["tanaka"] = versions["kanjialive"] = versions["tanos"] = "export fetched " + fetched
    generated = P.generated_of(sources_text)
    report = {"generated": generated, "levels": LEVELS, "levels_built": "%d-%d" % (lo, hi)}

    # ---- kanji ----
    kd, _ = readers.read_kanjidic2(paths["kanjidic2"])
    glyphs = K.inventory(kd)
    kset = set(glyphs)
    kvg = readers.read_kanjivg(paths["kanjivg"], glyphs)
    parts = {g: K.parts_of(g, kvg) for g in glyphs}
    missing_kvg = [g for g in glyphs if g not in kvg]
    meanings = {g: K.meanings_of(kd, g) for g in glyphs}
    for r in read_csv(os.path.join(overrides, "keywords.csv")):  # distinct keywords where KANJIDIC2 repeats one
        if r["kanji"] in meanings:
            meanings[r["kanji"]] = [r["keyword"]] + [m for m in meanings[r["kanji"]] if m != r["keyword"]]
    readings = {g: K.readings_of(kd, g) for g in glyphs}
    bad = [g for g in glyphs if not meanings[g] or not (readings[g]["on"] or readings[g]["kun"])]
    order = K.order(glyphs, kd, {g: len(parts[g]) for g in glyphs})
    kanji_level = K.slice_levels(order, LEVELS)
    clashes = K.keyword_clashes(meanings)
    print("kanji: %s joyo characters from kanjidic2, %d without KanjiVG, %d single-part, %d atomic, "
          "%d unparseable (%s)" % (
              fmt(len(glyphs)), len(missing_kvg), sum(1 for g in glyphs if len(parts[g]) == 1),
              sum(1 for g in glyphs if not parts[g]), len(bad), timer.lap()))
    if bad:
        raise BuildError("kanji without meaning or reading: %s" % " ".join(bad))

    # ---- components ----
    comps, refs = C.collapse(parts, kanji_level, kset)
    names, unnamed = C.name_components(comps, kd, read_csv(os.path.join(overrides, "components.csv")),
                                       read_blocklist(os.path.join(overrides, "blocked-names.csv")))
    if unnamed:
        raise BuildError("components without a name (add them to overrides/components.csv): %s" % " ".join(unnamed))
    inline = {g: [r for r in refs[g] if r["ref"] is None] for g in glyphs}
    n_inline = sum(len(v) for v in inline.values())
    atomic = [g for g in glyphs if not refs[g]]
    print("components: %d taught (%d dictionary, %d dictionary-alt, %d unicode, %d proposed/override), "
          "%d inline single-use shapes, %d atomic kanji (%s)" % (
              len(comps), *(sum(1 for n in names.values() if n["status"] == s)
                            for s in ("dictionary", "dictionary-alt", "unicode")),
              sum(1 for n in names.values() if n["status"] not in ("dictionary", "dictionary-alt", "unicode")),
              n_inline, len(atomic), timer.lap()))

    # ---- vocabulary ----
    tanos = readers.read_tanos({(lv, kind): paths["tanos-n%d-%s" % (lv, kind)]
                                for lv in (5, 4, 3, 2, 1) for kind in ("vocab", "kanji")})
    t_forms, t_kana = V.tanos_index(tanos)
    entries, n_entries = readers.read_jmdict(paths["jmdict"], lambda e: V.keep_entry(e, t_forms, t_kana))
    cand_k, cand_kana = V.candidates(entries, kset, tanos)
    print("jmdict: %s entries read, %s kept, %s kanji candidates, %s kana candidates (%s)" % (
        fmt(n_entries), fmt(len(entries)), fmt(len(cand_k)), fmt(len(cand_kana)), timer.lap()))
    forms = {w["form"] for w in cand_k} | {w["form"] for w in cand_kana}
    examples, lemma = readers.read_examples(paths["examples"], forms)
    for w in cand_k + cand_kana:
        w["lemma"] = lemma.get(w["form"], 0)
    cand_k, dropped = V.dedupe_forms(cand_k)
    cand_kana, dropped_kana = V.dedupe_forms(cand_kana)
    provisional = {g: K.teach_reading(g, readings[g], [(w["form"], hira(w["reading"])) for w in cand_k if g in w["kanji"]])
                   for g in glyphs}
    selected, per_kanji, short = V.select(cand_k, order, readings, provisional)
    kana_words = V.select_kana(cand_kana)
    words = selected + kana_words
    print("vocabulary: %s words (%s with kanji, %s kana-only), %d kanji with fewer than %d words, "
          "%d homograph candidates dropped (%s)" % (fmt(len(words)), fmt(len(selected)), fmt(len(kana_words)),
                                                   len(short), V.MIN_PER, len(dropped) + len(dropped_kana), timer.lap()))

    # ---- levels and taught readings ----
    wlevel, cap = word_levels(words, kanji_level, LEVELS)
    by_kanji_words = {g: [] for g in glyphs}
    for w in words:
        for g in w["kanji"]:
            by_kanji_words[g].append((w["form"], hira(w["reading"])))
    over = {r["kanji"]: (r["group"], r["reading"]) for r in read_csv(os.path.join(overrides, "readings.csv"))}
    teach = {g: K.teach_reading(g, readings[g], by_kanji_words[g], over.get(g)) for g in glyphs}
    comp_level = {e: c["level"] for e, c in comps.items()}
    sizes = Counter()
    for g in glyphs:
        sizes[kanji_level[g]] += 1
    for lv in comp_level.values():
        sizes[lv] += 1
    for lv in wlevel.values():
        sizes[lv] += 1
    print("levels: %d, kanji per level %d-%d, vocabulary cap %d, items per level %d-%d, "
          "taught readings on/kun %d/%d (%s)" % (
              LEVELS, min(Counter(kanji_level.values()).values()), max(Counter(kanji_level.values()).values()),
              cap, min(sizes.values()), max(sizes.values()),
              sum(1 for t in teach.values() if t["group"] == "on"),
              sum(1 for t in teach.values() if t["group"] == "kun"), timer.lap()))

    # ---- sentences ----
    links = readers.read_links(paths["tatoeba-links"])
    jp = readers.read_jpn(paths["tatoeba-jpn"], set(links))
    en_ids = {e for sid in jp for e in links[sid]} | {ex["en_id"] for ex in examples.values()}
    eng = readers.read_eng(paths["tatoeba-eng"], en_ids)
    sents, sstats = select_sentences(words, wlevel, kanji_level, jp, links, eng, examples)
    print("sentences: %s Japanese sentences with English, %s words with >=1 (%.1f%%), %s with >=3 (%.1f%%), "
          "%s sentences, %s authors (%s)" % (
              fmt(len(jp)), fmt(sstats["with_1"]), 100.0 * sstats["with_1"] / len(words),
              fmt(sstats["with_3"]), 100.0 * sstats["with_3"] / len(words),
              fmt(sstats["sentences"]), fmt(sstats["authors"]), timer.lap()))

    # ---- audio ----
    ka = readers.read_kanjialive(paths["kanjialive"])
    audio, manifest = match_audio(words, ka)
    print("audio: %s Kanji alive example words, %s words with a native recording (%.1f%%) (%s)" % (
        fmt(len(ka)), fmt(len(audio)), 100.0 * len(audio) / len(words), timer.lap()))

    # ---- records ----
    kanji_jlpt = {}
    for lv in (5, 4, 3, 2, 1):
        for g in tanos.get(lv, {}).get("kanji", set()):
            kanji_jlpt.setdefault(g, lv)
    images = {}
    items, cards, index = [], [], []

    def add(rec, card_answers):
        items.append(rec)
        index.append({"id": rec["id"], "level": rec["level"], "type": rec["type"], "glyph": rec["glyph"],
                      "meanings": rec["meanings"], "readings": rec["index_readings"], "requires": rec["requires"]})
        del rec["index_readings"]
        for prompt, answers in card_answers:
            cards.append({"id": rec["id"] + ":" + prompt, "record": rec["id"], "level": rec["level"],
                          "type": rec["type"], "prompt": prompt, "glyph": rec["glyph"], "glyph_alt": "",
                          "images": rec.get("images", []), "answers": answers,
                          "audio": rec.get("audio", []), "word_type": rec.get("word_type", "")})

    comp_order = sorted(comps, key=lambda e: (comps[e]["level"], order.index(comps[e]["users"][0]), e))
    for e in comp_order:
        c, n = comps[e], names[e]
        glyph = "" if e.startswith("CDP-") else e
        imgs = []
        if not glyph or ord(glyph) > 0xFFFF:
            first = c["users"][0]
            # one copy of the shape, not every repeat of it in the first user (林 has two 木)
            nodes = next((p["nodes"] for p in kvg[first]["parts"] if p["element"] == e), []) if first in kvg else []
            if nodes:
                images[P.image_name(e)] = nodes
                imgs = [P.image_name(e)]
        rec = {"id": C.comp_id(e), "type": "radical", "level": c["level"], "glyph": glyph,
               "meanings": [n["name"]], "index_readings": [], "requires": [], "images": imgs,
               "name_status": n["status"], "name_alternatives": n["alts"],
               "used_by": ["kanji/" + g for g in c["users"]],
               "sentences": [], "audio": [], "word_type": "",
               "src": {"parts": "kanjivg", "name": {"dictionary": "kanjidic2", "dictionary-alt": "kanjidic2",
                                                     "unicode": "unicode"}.get(n["status"], "own")}}
        add(rec, [("meaning", [n["name"]])])
    for g in order:
        rd = readings[g]
        inline_recs = []
        for r in inline[g]:
            e = r["elem"]
            nodes = next((p["nodes"] for p in kvg[g]["parts"] if p["element"] == e), []) if g in kvg else []
            img = ""
            if nodes:
                images[P.image_name(e)] = nodes
                img = P.image_name(e)
            inline_recs.append({"glyph": "" if e.startswith("CDP-") else e, "image": img, "position": r["pos"]})
        req = [r["ref"] for r in refs[g] if r["ref"]]
        src = {"dict": "kanjidic2", "parts": "kanjivg"}
        if g in kanji_jlpt:
            src["jlpt"] = "tanos"
        rec = {"id": "kanji/" + g, "type": "kanji", "level": kanji_level[g], "glyph": g,
               "meanings": meanings[g], "readings": rd, "index_readings": K.flat_readings(rd),
               "teach": {"group": teach[g]["group"], "reading": teach[g]["reading"]},
               "parts": req, "part_positions": [r["pos"] for r in refs[g] if r["ref"]],
               "inline_parts": inline_recs, "atomic": not refs[g], "requires": list(dict.fromkeys(req)),
               "strokes": kd[g]["strokes"], "grade": kd[g]["grade"], "freq": kd[g]["freq"],
               "jlpt": kanji_jlpt.get(g), "sentences": [], "audio": [], "word_type": "", "src": src}
        add(rec, [("meaning", meanings[g]), ("reading", K.flat_readings(rd))])
    for w in sorted(words, key=lambda w: (wlevel[w["form"]], w["nf"] or 99, -w["lemma"], w["form"])):
        src = {"dict": "jmdict"}
        if sents.get(w["form"]):
            src["sentences"] = "tatoeba"
        if audio.get(w["form"]):
            src["audio"] = "kanjialive"
        if w["jlpt"]:
            src["jlpt"] = "tanos"
        rec = {"id": "vocabulary/" + w["form"], "type": "vocabulary", "level": wlevel[w["form"]],
               "glyph": w["form"], "meanings": w["glosses"], "readings": w["readings"],
               "index_readings": w["readings"], "requires": ["kanji/" + k for k in w["kanji"]],
               "word_type": w["word_type"], "ent_seq": w["seq"], "nf": w["nf"], "jlpt": w["jlpt"],
               "sentences": sents.get(w["form"], []), "audio": audio.get(w["form"], []), "src": src}
        add(rec, [("meaning", w["glosses"]), ("reading", w["readings"])])

    # ---- pack ----
    keep = lambda r: lo <= r["level"] <= hi  # noqa: E731
    items_w, cards_w, index_w = [r for r in items if keep(r)], [c for c in cards if keep(c)], [r for r in index if keep(r)]
    index_w.sort(key=lambda r: (r["level"], TYPE_ORDER[r["type"]], index.index(r)))
    kept_ids = {r["id"] for r in items_w}
    manifest_w = [m for m in manifest if "vocabulary/" + m["word"] in kept_ids]
    used_images = {p for r in items_w for p in r.get("images", [])} | \
                  {ip["image"] for r in items_w for ip in r.get("inline_parts", []) if ip["image"]}
    authors = sorted({a for r in items_w for s in r["sentences"] for a in (s["author"], s["en_author"])})
    report.update({
        "counts": {"kanji": len(glyphs), "components": len(comps), "inline_parts": n_inline, "atomic_kanji": len(atomic),
                   "vocabulary": len(words), "vocabulary_kanji": len(selected), "vocabulary_kana": len(kana_words),
                   "items": len(items), "cards": len(cards), "images": len(used_images),
                   "items_written": len(items_w), "cards_written": len(cards_w)},
        "sources": {"jmdict_entries": n_entries, "jmdict_kept": len(entries), "candidates_kanji": len(cand_k),
                    "candidates_kana": len(cand_kana), "tatoeba_jp_with_en": len(jp), "kanjialive_words": len(ka)},
        "sentences": {k: v for k, v in sstats.items() if k != "fewer_than_3"},
        "audio": {"native": len(audio), "native_share": round(len(audio) / len(words), 4)},
        "levels_summary": {"kanji_per_level": {"%02d" % k: v for k, v in sorted(Counter(kanji_level.values()).items())},
                           "items_per_level": {"%02d" % k: v for k, v in sorted(sizes.items())}, "vocabulary_cap": cap},
        "teach": {"on": sum(1 for t in teach.values() if t["group"] == "on"),
                  "kun": sum(1 for t in teach.values() if t["group"] == "kun"),
                  "distinct": len({t["reading"] for t in teach.values()}),
                  "zero_usage": sorted(g for g, t in teach.items() if t["count"] == 0)},
        "keyword_clashes": clashes,
        "component_name_duplicates": C.duplicate_names(names),
        "proposed_component_names": [{"glyph": e, "name": names[e]["name"], "status": names[e]["status"],
                                      "users": comps[e]["users"][:8], "dictionary": names[e]["alts"]}
                                     for e in comp_order if names[e]["status"] not in ("dictionary", "dictionary-alt")],
        "kanji_with_fewer_than_2_words": short,
        "kanji_without_kanjivg": missing_kvg,
        "homographs_dropped": dropped + dropped_kana,
        "words_with_fewer_than_3_sentences": sstats["fewer_than_3"],
    })
    P.write_images(out, {p: n for p, n in images.items() if p in used_images})
    P.write_levels(out, items_w, cards_w, lo, hi)
    P.write_index(out, index_w, generated)
    P.write_rest(out, sources_text, versions, authors, len(audio), manifest_w, report)
    print("pack: %s records, %s cards, %d levels (%d-%d), %d images -> %s (%s)" % (
        fmt(len(index_w)), fmt(len(cards_w)), hi - lo + 1, lo, hi, len(used_images), out, timer.lap()))
    print("coverage: %s/%s records yield cards, 0 unparseable" % (fmt(len(index_w)), fmt(len(index_w))))
    return 0


def main(argv=None):
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--levels", default=None, help="e.g. 1-3; default all")
    ap.add_argument("--overrides", default=OVERRIDES)
    args = ap.parse_args(argv)
    lo, hi = parse_levels(args.levels)
    return build(args.vendor, args.out, lo, hi, args.overrides)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as e:
        print("ERROR: %s" % e)
        sys.exit(1)
