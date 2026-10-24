"""Level stage: a word's base level is the highest level among its kanji
(kana-only: 1); words are ranked by nf rank then lemma count, each level takes
at most ceil(words / levels * 1.25), the overflow spills to the next level.
"""
import math
from collections import defaultdict

CAP_FACTOR = 1.25


def word_levels(words, kanji_level, nlevels, factor=CAP_FACTOR):
    pending = defaultdict(list)
    for w in words:
        pending[max([kanji_level[k] for k in w["kanji"]], default=1)].append(w)
    cap = math.ceil(len(words) / nlevels * factor)
    level, carry = {}, []
    for lv in range(1, nlevels + 1):
        pool = sorted(carry + pending.get(lv, []), key=lambda w: (w["nf"] or 99, -w["lemma"], w["form"]))
        take, carry = (pool, []) if lv == nlevels else (pool[:cap], pool[cap:])
        for w in take:
            level[w["form"]] = lv
    return level, cap
