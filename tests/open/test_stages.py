import os
import tempfile
import unittest

import helpers as H
import readers
import kanji as K
import components as C
import vocab as V
from levels import word_levels
from sentences import select_sentences
from audio import match_audio
from common import BuildError


def kd_fixture():
    with tempfile.TemporaryDirectory() as d:
        kd, _ = readers.read_kanjidic2(H.gz(os.path.join(d, "k.gz"), H.KANJIDIC2))
    return kd


class KanjiTests(unittest.TestCase):
    def setUp(self):
        self.kd = kd_fixture()

    def test_inventory_is_joyo(self):
        self.assertEqual(K.inventory(self.kd), ["一", "上", "手", "箇"])      # 卜 is grade 9

    def test_clean_meaning(self):
        self.assertEqual(K.clean_meaning("ice radical (no. 15)"), "ice")
        self.assertEqual(K.clean_meaning("radical (no. 5)"), "")
        self.assertEqual(K.clean_meaning("counter for articles"), "")
        self.assertEqual(K.clean_meaning("up (high)"), "up")

    def test_meanings_keyword_and_fallback(self):
        self.assertEqual(K.meanings_of(self.kd, "一"), ["one"])
        self.assertEqual(K.meanings_of(self.kd, "箇"), ["counter for articles"])
        self.assertEqual(K.keyword_clashes({"a": ["one"], "b": ["one"], "c": ["two"]}), {"one": ["a", "b"]})

    def test_readings(self):
        r = K.readings_of(self.kd, "上")
        self.assertEqual(r["on"], ["じょう", "しょう"])
        self.assertEqual(r["kun"], [{"stem": "うえ", "okurigana": ""}, {"stem": "あ", "okurigana": "げる"}])
        self.assertEqual(K.flat_readings(r), ["じょう", "しょう", "うえ", "あ", "あげ"])

    def test_order_and_levels(self):
        order = K.order(["上", "一"], self.kd, {"上": 2, "一": 0})
        self.assertEqual(order, ["一", "上"])
        self.assertEqual(K.slice_levels(list("abcd"), 2), {"a": 1, "b": 1, "c": 2, "d": 2})

    def test_teach_reading(self):
        r = K.readings_of(self.kd, "上")
        words = [("上", "うえ"), ("上着", "うわぎ"), ("上手", "じょうず"), ("上げる", "あげる")]
        self.assertEqual(K.teach_reading("上", r, words)["reading"], "じょう")   # tie 1-1 favours on
        self.assertEqual(K.teach_reading("上", r, words + [("川上", "かわかみ"), ("上", "うえ")])["reading"], "うえ")
        self.assertEqual(K.teach_reading("上", r, [])["reading"], "じょう")
        self.assertEqual(K.teach_reading("上", r, words, ("kun", "あ"))["reading"], "あ")
        with self.assertRaises(BuildError):
            K.teach_reading("上", r, words, ("on", "うえ"))


class ComponentTests(unittest.TestCase):
    def test_collapse_rules(self):
        parts = {"一": [], "上": [("卜", "top"), ("一", "bottom")], "三": [("一", ""), ("二", "")],
                 "丁": [("一", ""), ("亅", "")], "二": [("一", "")]}
        level = {"一": 1, "上": 1, "二": 1, "丁": 2, "三": 3}
        comps, refs = C.collapse(parts, level, set(parts))
        self.assertEqual(sorted(comps), ["一"])
        self.assertEqual(comps["一"]["level"], 1)
        self.assertEqual([r["ref"] for r in refs["上"]], [None, "radical/一"])     # 卜 single-use -> inline
        self.assertEqual([r["ref"] for r in refs["三"]], ["kanji/一", "kanji/二"])  # both taught two levels earlier
        self.assertEqual([r["ref"] for r in refs["丁"]], ["radical/一", None])     # only one level earlier
        self.assertEqual(refs["一"], [{"elem": "一", "pos": "", "ref": "radical/一"}])  # atomic kanji needs its own radical
        self.assertEqual(comps["一"]["users"], ["一", "上", "二", "丁"])          # 三 references kanji/一 instead
        self.assertEqual(C.comp_id("CDP-8BC4"), "radical/cdp-8bc4")

    def test_collapse_counts_kanji_not_repeats(self):
        parts = {"林": [("木", "left"), ("木", "right")], "上": [("卜", "top"), ("一", "bottom")], "一": []}
        comps, refs = C.collapse(parts, {"林": 1, "上": 1, "一": 1}, {"林", "上", "一"})
        self.assertNotIn("木", comps)                                            # one kanji uses it: inline
        self.assertEqual([(r["elem"], r["ref"]) for r in refs["林"]], [("木", None), ("木", None)])
        parts["森"] = [("木", "")] * 3
        comps, refs = C.collapse(parts, {"林": 1, "上": 1, "一": 1, "森": 1}, set(parts))
        self.assertEqual(comps["木"]["users"], ["林", "森"])
        self.assertEqual([r["ref"] for r in refs["森"]], ["radical/木"] * 3)

    def test_naming(self):
        self.assertTrue(C.plain_noun("Buddhist temple"))
        self.assertFalse(C.plain_noun("to carve wood"))
        self.assertFalse(C.plain_noun("road with walls on both sides"))
        self.assertEqual(C.unicode_name("⻌"), "walk")
        self.assertEqual(C.unicode_name("⺌"), "small")
        kd = {"口": {"meanings": ["mouth"]}, "乂": {"meanings": ["to mow", "cut grass"]}, "x": {"meanings": ["to go"]}}
        comps = {"口": {}, "乂": {}, "⻌": {}, "x": {}, "y": {}}
        names, unnamed = C.name_components(comps, kd, [{"glyph": "y", "name": "hook", "status": "proposed"}], [])
        self.assertEqual(unnamed, ["x"])
        self.assertEqual({e: n["status"] for e, n in names.items()},
                         {"口": "dictionary", "乂": "dictionary-alt", "⻌": "unicode", "y": "proposed"})
        self.assertEqual(names["乂"]["name"], "cut grass")
        with self.assertRaises(BuildError):
            C.name_components({"口": {}}, kd, [], [{"glyph": "口", "name": "mouth"}])
        with self.assertRaises(BuildError):
            C.name_components({"y": {}}, kd, [{"glyph": "y", "name": "hook", "status": "proposed"}], [{"glyph": "z", "name": "hook"}])
        with self.assertRaises(BuildError):          # case, spaces and a plural do not slip past
            C.name_components({"y": {}}, kd, [{"glyph": "y", "name": "Hooks ", "status": "proposed"}], [{"glyph": "z", "name": "hook"}])
        with self.assertRaises(BuildError):
            C.name_components({"口": {}}, kd, [], [{"glyph": "口", "name": " Mouth"}])
        self.assertEqual(C.duplicate_names({"a": {"name": "n"}, "b": {"name": "n"}}), {"n": ["a", "b"]})


class VocabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.entries, _ = readers.read_jmdict(H.gz(os.path.join(d, "j.gz"), H.JMDICT), lambda e: True)
        self.tanos = readers.read_tanos({(5, "vocab"): H.text(os.path.join(d, "v.html"), H.TANOS_VOCAB),
                                         (5, "kanji"): H.text(os.path.join(d, "k.html"), H.TANOS_KANJI)})
        self.kset = {"上", "一", "手"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_form_ok_and_word_type(self):
        self.assertTrue(V.form_ok("上々", self.kset))
        self.assertFalse(V.form_ok("上下", self.kset))
        self.assertFalse(V.form_ok("一一一一一", self.kset))
        self.assertFalse(V.form_ok("うえ", self.kset))
        self.assertEqual(V.word_type(["v5r", "vt", "v2a-s"]), "godan verb, transitive verb")
        self.assertEqual(V.word_type(["v2a-s"]), "")

    def test_candidates(self):
        words, kana = V.candidates(self.entries, self.kset, self.tanos)
        forms = {w["form"]: w for w in words}
        self.assertEqual(sorted(forms), ["一つ", "上", "上がる", "上手"])       # 上古 archaic, 上野 proper noun
        self.assertEqual(forms["上"]["readings"], ["うえ", "かみ"])
        self.assertEqual(forms["上"]["glosses"], ["above", "up"])                  # the かみ-only sense does not apply
        self.assertEqual(forms["上"]["word_type"], "noun")
        self.assertEqual((forms["上"]["nf"], forms["上"]["common"], forms["上"]["jlpt"]), (1, True, 5))
        self.assertEqual(forms["一つ"]["jlpt"], 5)                                 # tanos-only word
        self.assertEqual([w["form"] for w in kana], ["ありがとう"])                 # uk entry; は particle dropped
        self.assertEqual(kana[0]["jlpt"], 5)

    def test_select_respects_caps_and_tiers(self):
        words, _ = V.candidates(self.entries, self.kset, self.tanos)
        kd = kd_fixture()
        readings = {g: K.readings_of(kd, g) for g in self.kset}
        teach = {"上": {"group": "on", "reading": "じょう"}}
        old = V.MAX_PER
        try:
            V.MAX_PER = 2
            selected, count, short = V.select(words, ["上", "一"], readings, teach)
        finally:
            V.MAX_PER = old
        self.assertEqual([w["form"] for w in selected], ["上手", "上", "一つ"])      # taught-reading word first
        self.assertEqual(count["上"], 2)
        self.assertEqual(short, ["一"])
        # A partner kanji at its cap must not starve a rare kanji of its only word (子 full, 帽子 still taken).
        rd = {g: {"on": [], "kun": []} for g in "子様椅帽"}
        ws = [{"form": f, "kanji": list(dict.fromkeys(f.replace("0", ""))), "reading": "x", "nf": 1, "lemma": 0}
              for f in ("子0", "様子", "椅子", "帽子")]
        old = (V.MIN_PER, V.MAX_PER)
        try:
            V.MIN_PER, V.MAX_PER = 1, 2
            sel, cnt, short2 = V.select(ws, list("子様椅帽"), rd, {})
        finally:
            V.MIN_PER, V.MAX_PER = old
        self.assertEqual({w["form"] for w in sel}, {"子0", "様子", "椅子", "帽子"})
        self.assertEqual(short2, [])
        deduped, dropped = V.dedupe_forms([{"form": "x", "nf": 5, "common": True, "lemma": 0, "seq": 2},
                                            {"form": "x", "nf": None, "common": False, "lemma": 0, "seq": 1}])
        self.assertEqual((deduped[0]["seq"], dropped), (2, [("x", 1, 2)]))
        self.assertEqual(len(V.select_kana([{"form": "a", "jlpt": None, "nf": 1, "lemma": 0}, {"form": "b", "jlpt": 5, "nf": 9, "lemma": 0}], cap=1)), 1)
        self.assertEqual(V.select_kana([{"form": "a", "jlpt": None, "nf": 1, "lemma": 0}, {"form": "b", "jlpt": 5, "nf": 9, "lemma": 0}], cap=1)[0]["form"], "b")


class LevelSentenceAudioTests(unittest.TestCase):
    def test_word_levels_spill(self):
        words = [{"form": "a%d" % i, "kanji": ["x"], "nf": i + 1, "lemma": 0} for i in range(5)] + \
                [{"form": "k", "kanji": [], "nf": None, "lemma": 0}]
        level, cap = word_levels(words, {"x": 1}, 3, factor=1.0)
        self.assertEqual(cap, 2)
        self.assertEqual([level["a%d" % i] for i in range(5)], [1, 1, 2, 2, 3])
        self.assertEqual(level["k"], 3)                 # no nf rank sorts last and spills to the final level

    def test_select_sentences(self):
        words = [{"form": "上", "readings": ["うえ"]}]
        jp = {"1": ("上に行くのは大変だ。", "alice"), "2": ("上。", "bob"), "3": ("机の上に猫がいます。", ""),
              "4": ("上の階は魚屋です。", "carol"), "5": ("上に上に積み上げる。", "")}
        links = {"1": ["11"], "2": ["12"], "3": ["13"], "4": ["14"], "5": ["15"]}
        eng = {"11": ("Going up is hard.", "dave"), "12": ("Up.", "erin"), "13": ("There is a cat on the desk.", ""),
               "14": ("Fish shop upstairs.", "")}
        examples = {"3": {"jp": "机の上に猫がいます。", "en": "A cat is on the desk.", "en_id": "13", "hits": [("上", "うえ", "上に", True)]}}
        kl = {"上": 1, "行": 1, "大": 1, "変": 2, "机": 1, "猫": 1, "階": 1, "魚": 9, "屋": 1, "積": 1}
        out, stats = select_sentences(words, {"上": 1}, kl, jp, links, eng, examples)
        got = out["上"]
        self.assertEqual([s["id"] for s in got], [3, 1])           # 4's only English has no author
        self.assertEqual((got[0]["source"], got[0]["author"], got[0]["licence"]), ("tanaka", "Tanaka Corpus", "CC-BY"))
        self.assertEqual((got[0]["en"], got[0]["en_id"], got[0]["en_author"]), ("A cat is on the desk.", 13, "Tanaka Corpus"))
        self.assertEqual((got[1]["source"], got[1]["licence"]), ("tatoeba", "CC-BY-2.0-FR"))
        self.assertEqual((got[1]["en"], got[1]["en_id"], got[1]["en_author"]), ("Going up is hard.", 11, "dave"))
        self.assertEqual(stats["authors"], 3)                      # Tanaka Corpus, alice, dave
        eng["14"] = ("Fish shop upstairs.", "frank")
        out, stats = select_sentences(words, {"上": 1}, kl, jp, links, eng, examples)
        self.assertEqual([s["id"] for s in out["上"]], [3, 1, 4])  # checked Tanaka first; 魚 (level 9) only as fallback
        self.assertEqual(stats["with_3"], 1)
        out, stats = select_sentences(words, {"上": 1}, {}, {"5": jp["5"]}, links, eng, {})
        self.assertEqual((out["上"], stats["fewer_than_3"]), ([], [["上", 0]]))     # no author, no English

    def test_match_audio(self):
        with tempfile.TemporaryDirectory() as d:
            ka = readers.read_kanjialive(H.text(os.path.join(d, "ka.csv"), H.KA_DATA))
        audio, manifest = match_audio([{"form": "上手", "readings": ["じょうず"]}, {"form": "下", "readings": ["した"]}], ka)
        self.assertEqual(list(audio), ["上手"])
        self.assertEqual(audio["上手"][0]["url"], "audio/kanjialive/jou-ue_06_b.mp3")
        self.assertEqual(manifest[0]["member"], "audio-mp3/jou-ue_06_b.mp3")
        self.assertEqual(manifest[0]["licence"], "CC-BY-4.0")


if __name__ == "__main__":
    unittest.main()
