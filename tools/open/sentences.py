"""Sentence stage: up to three Tatoeba/Tanaka pairs per word.

Candidates: surface hits (the written form inside a Japanese sentence that has
an English translation) plus B-line hits from the Tanaka index (dictionary
form, reading-checked). Hard filters: 8-30 Japanese characters, an English
translation of two or more words, a known author for both sides (Tatoeba
usernames, or the Tanaka Corpus for a Tanaka pair). Soft score: kanji at or below the word's level beat kanji one
level above; anything higher is used only when nothing else exists; checked
examples, shorter sentences and sentences without long katakana runs rank
first.
"""
from collections import defaultdict

from common import CJK, KATAKANA_RUN, hira

MIN_LEN, MAX_LEN, MAX_N = 8, 30, 3
LIC_TATOEBA, LIC_TANAKA = "CC-BY-2.0-FR", "CC-BY"


def length_ok(text):
    return MIN_LEN <= len(text) <= MAX_LEN


def surface_index(jp, patterns):
    maxlen = max((len(p) for p in patterns), default=0)
    surf = defaultdict(set)
    for sid, (text, _) in jp.items():
        if not length_ok(text):
            continue
        seen = set()
        n = len(text)
        for i in range(n):
            for l in range(1, min(maxlen, n - i) + 1):
                s = text[i:i + l]
                if s in patterns and s not in seen:
                    seen.add(s)
                    surf[s].add(sid)
    return surf


def bline_index(examples, word_readings):
    """form -> {sid: checked}; a B-line reading must match one of the word's readings."""
    idx = defaultdict(dict)
    for sid, ex in examples.items():
        for head, reading, _, checked in ex["hits"]:
            rs = word_readings.get(head)
            if rs is None or (reading and hira(reading) not in rs):
                continue
            idx[head][sid] = idx[head].get(sid, False) or checked
    return idx


def english_for(sid, user, examples, links, eng):
    """-> (text, en_id, en_author); ("", None, "") when none qualifies.

    A Tatoeba sentence takes a Tatoeba translation with a named author, since
    CC BY 2.0 FR requires citing the author of each sentence. A Tanaka pair keeps
    the examples.utf English: that file names no per-sentence author, so the
    English is credited to the Tanaka Corpus under that file's CC BY terms.
    """
    ex = examples.get(sid)
    if not user:
        if ex and ex["en"]:
            en_id = ex.get("en_id") or ""
            return ex["en"], int(en_id) if en_id.isdigit() else None, "Tanaka Corpus"
        return "", None, ""
    first = [ex["en_id"]] if ex and ex.get("en_id") else []
    for en_id in first + links.get(sid, []):
        text, author = eng.get(en_id, ("", ""))
        if text and author:
            return text, int(en_id), author
    return "", None, ""


def level_penalty(text, kanji_level, wl):
    worst = 0
    for c in CJK.findall(text):
        lv = kanji_level.get(c)
        if lv is None or lv > wl + 1:
            return None
        if lv > wl:
            worst = 1
    return worst


def select_sentences(words, word_level, kanji_level, jp, links, eng, examples):
    """words: [{form, readings}] -> ({form: [sentence dicts]}, stats dict)."""
    patterns = {w["form"] for w in words}
    word_readings = {w["form"]: {hira(r) for r in w["readings"]} for w in words}
    surf = surface_index(jp, patterns)
    bline = bline_index(examples, word_readings)
    out, n1, n3, authors, short = {}, 0, 0, set(), []
    for w in words:
        form = w["form"]
        wl = word_level[form]
        ids = set(surf.get(form, ())) | set(bline.get(form, {}))
        good, fallback = [], []
        for sid in ids:
            if sid not in jp:            # Tanaka pair whose sentence has no English link any more
                continue
            text, user = jp[sid]
            if not length_ok(text):
                continue
            author = user or ("Tanaka Corpus" if sid in examples else "")
            en, en_id, en_author = english_for(sid, user, examples, links, eng)
            if not author or len(en.split()) < 2:
                continue
            pen = level_penalty(text, kanji_level, wl)
            checked = bline.get(form, {}).get(sid, False)
            katakana = bool(KATAKANA_RUN.search(text.replace(form, "")))
            key = (pen or 0, not checked, katakana, len(text), int(sid))
            rec = {"ja": text, "en": en, "id": int(sid), "author": author,
                   "en_id": en_id, "en_author": en_author,
                   "source": "tatoeba" if user else "tanaka",
                   "licence": LIC_TATOEBA if user else LIC_TANAKA}
            (good if pen is not None else fallback).append((key, rec))
        chosen, texts = [], set()
        for key, rec in sorted(good) + sorted(fallback):
            if rec["ja"] in texts:
                continue
            texts.add(rec["ja"])
            chosen.append(rec)
            if len(chosen) >= MAX_N:
                break
        out[form] = chosen
        n1 += bool(chosen)
        n3 += len(chosen) >= MAX_N
        if len(chosen) < MAX_N:
            short.append([form, len(chosen)])
        authors.update(a for r in chosen for a in (r["author"], r["en_author"]))
    stats = {"words": len(words), "with_1": n1, "with_3": n3, "authors": len(authors),
             "sentences": sum(len(v) for v in out.values()), "fewer_than_3": short}
    return out, stats
