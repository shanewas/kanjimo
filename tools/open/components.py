"""Component stage: collapse the KanjiVG part inventory and name what is left.

Collapse rules (per kanji k, part p):
  1. p is an inventory kanji taught two or more levels before k -> k requires kanji/p.
  2. otherwise, if p is used by two or more kanji -> k requires the component
     item radical/p, taught at the level of its first such user.
  3. otherwise the shape is shown inline in k's lesson, not taught.
An atomic kanji nobody else uses has no parts.

Naming rule, in order: an override row; the first KANJIDIC2 meaning when it
is a plain noun of one or two words; another listed meaning that is; a
shortened Unicode radical name; otherwise the shape must have a proposed name
in overrides/components.csv. Names from the blocklist are refused.
"""
import re
import unicodedata
from collections import Counter

from common import BuildError, name_key
from kanji import clean_meaning

PLAIN = re.compile(r"^[a-z][a-z'\- ]*[a-z]$")
UNICODE_DROP = {"SIMPLIFIED", "C-SIMPLIFIED", "J-SIMPLIFIED", "ONE", "TWO", "THREE"}


def comp_id(elem):
    if elem.startswith("CDP-"):
        return "radical/cdp-" + elem[4:].lower()
    return "radical/" + elem


def collapse(parts, kanji_level, kset):
    """-> (comps {elem: {level, users}}, refs {g: [{elem, pos, ref}]}); ref None = inline."""
    uses = Counter()
    for g, ps in parts.items():
        for e in {e for e, _ in (ps or [(g, "")])}:      # kanji using the shape, not occurrences (林 has two 木)
            uses[e] += 1
    comps, refs = {}, {}
    for g in sorted(parts, key=lambda x: (kanji_level[x], ord(x))):
        lv = kanji_level[g]
        out = []
        for e, pos in (parts[g] or [(g, "")]):
            if e in kset and e != g and kanji_level[e] <= lv - 2:
                out.append({"elem": e, "pos": pos, "ref": "kanji/" + e})
            elif uses[e] >= 2:
                c = comps.setdefault(e, {"level": lv, "users": []})
                c["level"] = min(c["level"], lv)
                if g not in c["users"]:
                    c["users"].append(g)
                out.append({"elem": e, "pos": pos, "ref": comp_id(e)})
            elif e != g:
                out.append({"elem": e, "pos": pos, "ref": None})
        refs[g] = out
    return comps, refs


def plain_noun(m):
    m = (m or "").lower()
    return bool(m) and 1 <= len(m.split()) <= 2 and bool(PLAIN.match(m)) and not m.startswith("to ")


def unicode_name(elem):
    if len(elem) != 1:
        return ""
    name = unicodedata.name(elem, "")
    if "RADICAL" not in name:
        return ""
    words = name.split("RADICAL", 1)[1].split()
    words = [w for w in words if w not in UNICODE_DROP]
    return " ".join(words).lower()


def name_components(comps, kd, overrides, blocklist):
    """-> ({elem: {name, status, alts}}, unnamed list). overrides: rows glyph,name,status."""
    by_glyph = {r["glyph"]: r for r in overrides if r.get("glyph")}
    pairs = {(b["glyph"], name_key(b["name"])) for b in blocklist}
    blocked_names = {name_key(b["name"]) for b in blocklist}
    names, unnamed = {}, []
    for e in sorted(comps):
        dict_meanings = [clean_meaning(m).lower() for m in kd.get(e, {}).get("meanings", [])]
        dict_meanings = list(dict.fromkeys(m for m in dict_meanings if m))
        name, status = "", ""
        row = by_glyph.get(e)
        if row and row.get("name"):
            name, status = row["name"], row.get("status") or "override"
        elif dict_meanings and plain_noun(dict_meanings[0]):
            name, status = dict_meanings[0], "dictionary"
        elif any(plain_noun(m) for m in dict_meanings):
            name, status = next(m for m in dict_meanings if plain_noun(m)), "dictionary-alt"
        elif unicode_name(e):
            name, status = unicode_name(e), "unicode"
        if not name:
            unnamed.append(e)
            continue
        if (e, name_key(name)) in pairs:
            raise BuildError("component %s: name %r is on the blocklist for this glyph" % (e, name))
        if status not in ("dictionary", "dictionary-alt") and name_key(name) in blocked_names:
            raise BuildError("component %s: name %r is on the blocklist" % (e, name))
        names[e] = {"name": name, "status": status,
                    "alts": [m for m in dict_meanings if m != name]}
    return names, unnamed


def duplicate_names(names):
    by = {}
    for e, n in names.items():
        by.setdefault(n["name"], []).append(e)
    return {k: v for k, v in sorted(by.items()) if len(v) > 1}
