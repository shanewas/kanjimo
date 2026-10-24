"""Vocabulary stage: candidates from JMdict and the tanos lists, then selection.

Candidate: a JMdict entry with a common tag or nf rank <= 30, or on a tanos
list; written with inventory kanji only (plus kana, 々, ー), at most four
kanji; not archaic/obsolete/rare, not a proper noun or particle. Entries whose
first sense is "usually kana" become kana-only candidates.

Selection: per kanji at least MIN_PER and at most MAX_PER words, preferring
words that use the taught reading, then another listed reading, then
frequency (nf rank, then Tatoeba lemma count). Kana words are capped.
"""
import re
from collections import Counter, defaultdict

from common import KANA, hira
from kanji import clean_meaning, reading_hits
from readers import PRI_COMMON, nf_rank

# MAX_PER 9 lands the inventory inside the 6,000-7,000 target (6 gives 4,922 kanji words, 10 gives 6,777).
MIN_PER, MAX_PER, NF_MAX, KANA_CAP, MAX_KANJI = 2, 9, 30, 300, 4
BAD_KEB = {"iK", "oK", "rK", "sK", "io"}
BAD_REB = {"ik", "ok", "rk", "sk"}
BAD_MISC = {"arch", "obs", "rare", "X"}
EXTRA_CHARS = set("ー々")
POS_LABEL = {
    "n": "noun", "n-adv": "adverbial noun", "n-t": "temporal noun",
    "n-pref": "noun prefix", "n-suf": "noun suffix", "vs": "verbal noun",
    "vs-i": "suru verb", "vs-s": "suru verb", "vk": "kuru verb", "vz": "ichidan verb",
    "v1": "ichidan verb", "v1-s": "ichidan verb", "vi": "intransitive verb",
    "vt": "transitive verb", "v-unspec": "verb", "vn": "irregular verb",
    "vr": "irregular verb", "adj-i": "い adjective", "adj-ix": "い adjective",
    "adj-na": "な adjective", "adj-no": "の adjective", "adj-pn": "pre-noun adjectival",
    "adj-t": "taru adjective", "adj-f": "prenominal", "adv": "adverb", "adv-to": "adverb",
    "aux": "auxiliary", "aux-v": "auxiliary verb", "aux-adj": "auxiliary adjective",
    "conj": "conjunction", "cop": "copula", "ctr": "counter", "exp": "expression",
    "int": "interjection", "num": "numeral", "pn": "pronoun", "pref": "prefix",
    "suf": "suffix", "unc": "unclassified"}
WORD_TYPES = set(POS_LABEL.values()) | {"godan verb"}


def word_type(pos):
    labels = []
    for p in pos:
        lab = "godan verb" if p.startswith("v5") else POS_LABEL.get(p)
        if lab and lab not in labels:
            labels.append(lab)
    return ", ".join(labels)


def applies(sense, keb, reb):
    return (not sense["stagk"] or keb in sense["stagk"]) and (not sense["stagr"] or reb in sense["stagr"])


def kanji_in(form, kset):
    return [c for c in form if c in kset]


def form_ok(form, kset):
    ks = kanji_in(form, kset)
    return 1 <= len(ks) <= MAX_KANJI and all(c in kset or c in EXTRA_CHARS or KANA.match(c) for c in form)


def tanos_index(tanos):
    """-> ({form: level}, {kana: level}) ; the first (easiest) list wins."""
    forms, kana = {}, {}
    for lv in (5, 4, 3, 2, 1):
        for form, kn, _ in tanos.get(lv, {}).get("vocab", []):
            for f in form.split("/"):
                if f.strip():
                    forms.setdefault(f.strip(), lv)
            if not form.strip():
                for k in kn.split("/"):
                    if k.strip():
                        kana.setdefault(k.strip(), lv)
    return forms, kana


def keep_entry(ent, t_forms, t_kana):
    pri = {t for k in ent["k"] for t in k["pri"]} | {t for r in ent["r"] for t in r["pri"]}
    nf = nf_rank(pri)
    if pri & PRI_COMMON or (nf and nf <= NF_MAX):
        return True
    if any(k["text"] in t_forms for k in ent["k"]):
        return True
    return not ent["k"] and any(r["text"] in t_kana for r in ent["r"])


def _word(ent, keb, reb, rebs, senses, kset, t_forms, t_kana):
    pri = set(keb["pri"] if keb else []) | set(reb["pri"])
    common = bool(pri & PRI_COMMON)
    nf = nf_rank(pri)
    form = keb["text"] if keb else reb["text"]
    jlpt = t_forms.get(form) if keb else t_kana.get(form)
    if not (common or (nf and nf <= NF_MAX) or jlpt):
        return None
    glosses = []
    for s in senses:
        for g in s["gloss"]:
            c = clean_meaning(g)
            if c and c not in glosses:
                glosses.append(c)
    wt = word_type(senses[0]["pos"])
    if not glosses or not wt:
        return None
    return {"form": form, "reading": reb["text"], "readings": [r["text"] for r in rebs],
            "keyword": glosses[0], "glosses": glosses, "word_type": wt,
            "pos": senses[0]["pos"], "seq": ent["seq"], "nf": nf, "common": common,
            "jlpt": jlpt, "kanji": list(dict.fromkeys(kanji_in(form, kset))), "lemma": 0}


def candidates(entries, kset, tanos):
    """-> (kanji words, kana words) as dicts; one candidate per entry."""
    t_forms, t_kana = tanos_index(tanos)
    words, kana = [], []
    for ent in entries:
        keb = next((k for k in ent["k"] if not set(k["inf"]) & BAD_KEB and form_ok(k["text"], kset)), None)
        if keb:
            rebs = [r for r in ent["r"] if not r["nokanji"] and not set(r["inf"]) & BAD_REB
                    and (not r["restr"] or keb["text"] in r["restr"])]
        else:
            rebs = [r for r in ent["r"] if not set(r["inf"]) & BAD_REB and KANA.match(r["text"])]
        if not rebs:
            continue
        reb = rebs[0]
        senses = [s for s in ent["s"] if applies(s, keb["text"] if keb else None, reb["text"])
                  and not set(s["misc"]) & BAD_MISC]
        if not senses:
            continue
        pos = senses[0]["pos"]
        if "n-pr" in pos or pos == ["prt"]:
            continue
        kana_only = (not keb) or "uk" in senses[0]["misc"]
        if kana_only:
            if keb:                      # usually written in kana: teach the kana form
                keb = None
            w = _word(ent, None, reb, [reb], senses, kset, t_forms, t_kana)
            if w and len(w["form"]) >= 2:
                kana.append(w)
            continue
        w = _word(ent, keb, reb, rebs, senses, kset, t_forms, t_kana)
        if w:
            words.append(w)
    return words, kana


def dedupe_forms(words):
    """One candidate per written form: the most common entry wins."""
    out, dropped = {}, []
    for w in sorted(words, key=lambda w: (w["nf"] or 99, not w["common"], -w["lemma"], w["seq"])):
        if w["form"] in out:
            dropped.append((w["form"], w["seq"], out[w["form"]]["seq"]))
        else:
            out[w["form"]] = w
    return list(out.values()), dropped


def select(words, kanji_order, readings, teach):
    """Per-kanji selection; words are deduped candidates. -> selected list in candidate order."""
    by_kanji = defaultdict(list)
    for w in words:
        for k in w["kanji"]:
            by_kanji[k].append(w)

    def tier(k, w):
        on, kun = readings[k]["on"], [x["stem"] for x in readings[k]["kun"]]
        hits = reading_hits(k, w["form"], hira(w["reading"]), on, kun)
        t = teach.get(k)
        if t and (t["group"], t["reading"]) in hits:
            return 0
        return 1 if hits else 2

    ranked = {k: sorted(ws, key=lambda w: (tier(k, w), w["nf"] or 99, -w["lemma"], w["form"]))
              for k, ws in by_kanji.items()}
    selected, count = {}, Counter()
    for target in (MIN_PER, MAX_PER):
        for k in kanji_order:
            for w in ranked.get(k, []):
                if count[k] >= target:
                    break
                # The minimum pass ignores the other kanji's cap: otherwise 帽 never gets 帽子
                # because 子 filled up first, and 66 kanji ended with no word at all.
                if w["form"] in selected or (target == MAX_PER and any(count[x] >= MAX_PER for x in w["kanji"])):
                    continue
                selected[w["form"]] = w
                for x in w["kanji"]:
                    count[x] += 1
    short = sorted(k for k in kanji_order if count[k] < MIN_PER)
    return list(selected.values()), count, short


def select_kana(kana, cap=KANA_CAP):
    ranked = sorted(kana, key=lambda w: (w["jlpt"] not in (5, 4), -(w["jlpt"] or 0),
                                         w["nf"] or 99, -w["lemma"], w["form"]))
    seen, out = set(), []
    for w in ranked:
        if w["form"] in seen:
            continue
        seen.add(w["form"])
        out.append(w)
        if len(out) >= cap:
            break
    return out
