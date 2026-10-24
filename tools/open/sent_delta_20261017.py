"""Fill example sentences for shipped words that have none, with the build's own selector."""
import json, glob, sys, os
sys.path.insert(0, "tools/open")
import readers, sentences as S
S.MAX_LEN = 40  # the build used 30; longer sentences beat none for a word with no example
data = sys.argv[1]
items = {}
files = {}
for f in sorted(glob.glob(f"{data}/items/level-*.json")):
    d = json.load(open(f, encoding="utf-8")); files[f] = d
    for it in d["items"]: items[it["id"]] = it
kanji_level = {it["glyph"]: it["level"] for it in items.values() if it["type"] == "kanji"}
need = [it for it in items.values() if it["type"] == "vocabulary" and not it.get("sentences")]
words = [{"form": it["glyph"], "readings": it.get("readings") or []} for it in need]
wl = {it["glyph"]: it["level"] for it in need}
links = readers.read_links("jpn-eng_links.tsv.bz2")
jp = readers.read_jpn("jpn_sentences_detailed.tsv.bz2", set(links))
examples, _ = readers.read_examples("examples.utf.gz", set(wl))
en_ids = {e for sid in jp for e in links[sid]} | {ex["en_id"] for ex in examples.values()}
eng = readers.read_eng("eng_sentences_detailed.tsv.bz2", en_ids)
out, st = S.select_sentences(words, wl, kanji_level, jp, links, eng, examples)
import re
CJK = re.compile(r"[一-鿿々]")
def standalone(form, text):
    # the match must not sit inside a longer kanji run (元首 in 元首相, 低価格 in 最低価格)
    i = text.find(form)
    while i >= 0:
        j = i + len(form)
        if (j >= len(text) or not CJK.match(text[j])) and (i == 0 or not CJK.match(text[i - 1])):
            return True
        i = text.find(form, i + 1)
    return False
out = {f: [r for r in s if standalone(f, r["ja"])] for f, s in out.items()}
filled = {f: s for f, s in out.items() if s}
print(f"words without sentences {len(need)}, now filled {len(filled)}, sentences {sum(map(len, filled.values()))}")
changed = set()
for f, d in files.items():
    for it in d["items"]:
        if it["type"] == "vocabulary" and it["glyph"] in filled and not it.get("sentences"):
            it["sentences"] = filled[it["glyph"]]
            it.setdefault("src", {})["sentences"] = "tatoeba"
            changed.add(f)
os.makedirs("out/items", exist_ok=True)
for f in changed:
    json.dump(files[f], open("out/items/" + os.path.basename(f), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("files changed", len(changed))
for f, s in list(filled.items())[:8]: print(" ", f, "|", s[0]["ja"], "|", s[0]["en"])
