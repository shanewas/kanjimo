import os
import tempfile
import unittest

import helpers as H  # noqa: F401  (puts tools/open on sys.path)
import common
import pack as P
import validate as VAL


def tiny_build(root):
    """A minimal one-level output tree that satisfies every gate."""
    sources_text = common.dumps({"fetched": "2026-10-09", "sources": []})
    gen = P.generated_of(sources_text)
    radical = {"id": "radical/一", "type": "radical", "level": 1, "glyph": "一", "meanings": ["one"], "requires": [],
               "images": [], "sentences": [], "audio": [], "word_type": "", "src": {"parts": "kanjivg", "name": "kanjidic2"}}
    kanji = {"id": "kanji/上", "type": "kanji", "level": 1, "glyph": "上", "meanings": ["above"],
             "readings": {"on": ["じょう"], "kun": [{"stem": "うえ", "okurigana": ""}], "nanori": []},
             "teach": {"group": "on", "reading": "じょう"}, "parts": ["radical/一"], "part_positions": ["bottom"],
             "inline_parts": [{"glyph": "卜", "image": "images/u535c.svg", "position": "top"}], "atomic": False,
             "requires": ["radical/一"], "sentences": [], "audio": [], "word_type": "", "src": {"dict": "kanjidic2", "parts": "kanjivg"}}
    word = {"id": "vocabulary/上", "type": "vocabulary", "level": 1, "glyph": "上", "meanings": ["above"], "readings": ["うえ"],
            "requires": ["kanji/上"], "word_type": "noun", "ent_seq": 1, "nf": 1, "jlpt": 5,
            "sentences": [{"ja": "机の上に猫がいます。", "en": "A cat is on the desk.", "id": 3, "author": "Tanaka Corpus",
                           "en_id": 13, "en_author": "Tanaka Corpus", "source": "tanaka", "licence": "CC-BY"}],
            "audio": [{"url": "audio/kanjialive/jou-ue_06_a.mp3", "content_type": "audio/mpeg", "source": "kanjialive", "licence": "CC-BY-4.0"}],
            "src": {"dict": "jmdict", "sentences": "tatoeba", "audio": "kanjialive"}}
    items = [radical, kanji, word]
    index = [{"id": r["id"], "level": 1, "type": r["type"], "glyph": r["glyph"], "meanings": r["meanings"],
              "readings": [] if r["type"] == "radical" else (["じょう", "うえ"] if r["type"] == "kanji" else r["readings"]),
              "requires": r["requires"]} for r in items]
    cards = [{"id": "radical/一:meaning", "record": "radical/一", "level": 1, "type": "radical", "prompt": "meaning", "glyph": "一",
              "glyph_alt": "", "images": [], "answers": ["one"], "audio": [], "word_type": ""}]
    for rid, glyph, ans_m, ans_r, audio, wt in (("kanji/上", "上", ["above"], ["じょう", "うえ"], [], ""),
                                                ("vocabulary/上", "上", ["above"], ["うえ"], word["audio"], "noun")):
        for prompt, answers in (("meaning", ans_m), ("reading", ans_r)):
            cards.append({"id": rid + ":" + prompt, "record": rid, "level": 1, "type": rid.split("/")[0], "prompt": prompt,
                          "glyph": glyph, "glyph_alt": "", "images": [], "answers": answers, "audio": audio, "word_type": wt})
    common.write_text(os.path.join(root, "images", "u535c.svg"), "<svg/>\n")
    P.write_levels(root, items, cards, 1, 1)
    P.write_index(root, index, gen)
    manifest = [{"url": word["audio"][0]["url"], "archive": "a", "member": "m", "word": "上", "reading": "うえ",
                 "kanji": "上", "source": "kanjialive", "licence": "CC-BY-4.0"}]
    P.write_rest(root, sources_text, {"jmdict": "x"}, ["Tanaka Corpus"], 1, manifest,
                 {"generated": gen, "levels": 40, "levels_built": "1-1"})
    return items


class WriterTests(unittest.TestCase):
    def test_canonical_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            common.write_json(p, {"b": 1, "a": {"d": [1, 2], "c": "ü"}})
            with open(p, "rb") as f:
                raw = f.read()
        self.assertEqual(raw, '{\n "a": {\n  "c": "ü",\n  "d": [\n   1,\n   2\n  ]\n },\n "b": 1\n}\n'.encode("utf-8"))
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)

    def test_refuses_forbidden_string(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(common.BuildError):
                common.write_json(os.path.join(d, "x.json"), {"note": "from " + "Wani" + "Kani"})
            self.assertFalse(os.path.exists(os.path.join(d, "x.json")))

    def test_refuses_repo_data_paths(self):
        self.assertTrue(common.inside_repo_data(os.path.join(common.REPO_DATA, "levels", "x.json")))
        self.assertFalse(common.inside_repo_data(os.path.join(common.REPO_ROOT, "data2")))
        with self.assertRaises(common.BuildError):
            common.assert_outside_repo_data(common.REPO_DATA, "vendor")

    def test_parse_levels(self):
        self.assertEqual(common.parse_levels("1-3"), (1, 3))
        self.assertEqual(common.parse_levels(None), (1, common.LEVELS))
        with self.assertRaises(common.BuildError):
            common.parse_levels("5-2")


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        tiny_build(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def level_file(self, kind):
        return os.path.join(self.root, kind, "level-01.json")

    def test_tiny_build_passes(self):
        c, stats = VAL.validate(self.root)
        self.assertEqual(c.errors, [])
        self.assertEqual((stats["kanji"], stats["components"], stats["words"], stats["cards"]), (1, 1, 1, 5))
        self.assertEqual(VAL.main([self.root]), 0)

    def test_detects_cycle_and_level_violation(self):
        data = common.read_json(self.level_file("items"))
        for rec in data["items"]:
            if rec["id"] == "radical/一":
                rec["requires"] = ["vocabulary/上"]
        common.write_json(self.level_file("items"), data)
        c, _ = VAL.validate(self.root)
        self.assertIn("dependency cycle", c.errors)

    def test_detects_bad_teach_reading_and_unknown_source(self):
        data = common.read_json(self.level_file("items"))
        for rec in data["items"]:
            if rec["type"] == "kanji":
                rec["teach"]["reading"] = "うえ"            # listed as kun, claimed as on
                rec["src"]["dict"] = "nowhere"
        common.write_json(self.level_file("items"), data)
        c, _ = VAL.validate(self.root)
        self.assertTrue(any("teach reading" in e for e in c.errors))
        self.assertTrue(any("not in LICENSES.json" in e for e in c.errors))

    def test_detects_forbidden_string_and_non_canonical_json(self):
        p = os.path.join(self.root, "attribution.md")
        with open(p, "a", encoding="utf-8") as f:
            f.write("source: wani" + "kani.com\n")
        with open(self.level_file("cards"), "w", encoding="utf-8") as f:
            f.write("{\"cards\": [], \"level\": 1}")
        c, _ = VAL.validate(self.root)
        self.assertTrue(any("forbidden string" in e for e in c.errors))
        self.assertTrue(any("canonical form" in e for e in c.errors))

    def test_detects_generated_mismatch_and_missing_cards(self):
        idx = common.read_json(os.path.join(self.root, "search-index.json"))
        idx["generated"] = "0" * 64
        common.write_json(os.path.join(self.root, "search-index.json"), idx)
        cards = common.read_json(self.level_file("cards"))
        cards["cards"] = [c for c in cards["cards"] if c["prompt"] != "reading"]
        common.write_json(self.level_file("cards"), cards)
        c, _ = VAL.validate(self.root)
        self.assertTrue(any("generated" in e for e in c.errors))
        self.assertTrue(any("has 1 cards, expected 2" in e for e in c.errors))

    def set_radical_name(self, name, src):
        data = common.read_json(self.level_file("items"))
        for rec in data["items"]:
            if rec["type"] == "radical":
                rec["meanings"], rec["src"]["name"] = [name], src
        common.write_json(self.level_file("items"), data)

    def test_blocklist_gate(self):
        d = tempfile.TemporaryDirectory()                  # outside the output tree, which validate walks
        self.addCleanup(d.cleanup)
        bl = H.text(os.path.join(d.name, "blocked-names.csv"), "glyph,name\n,ones\n一,single\n")
        self.assertEqual(VAL.validate(self.root, bl)[0].errors, [])          # kanjidic2 name "one" is allowed
        self.set_radical_name(" One", "own")
        self.assertIn("radical/一 name is on the blocklist", VAL.validate(self.root, bl)[0].errors)
        self.set_radical_name("Single", "kanjidic2")
        self.assertIn("radical/一 name is on the blocklist for this glyph", VAL.validate(self.root, bl)[0].errors)

    def test_missing_blocklist_fails(self):
        c, _ = VAL.validate(self.root, os.path.join(self.root, "no-such.csv"))
        self.assertTrue(any("blocklist missing" in e for e in c.errors))

    def test_tatoeba_sentence_needs_english_id_and_author(self):
        data = common.read_json(self.level_file("items"))
        for rec in data["items"]:
            for s in rec["sentences"]:
                s.update({"source": "tatoeba", "licence": "CC-BY-2.0-FR", "author": "alice", "en_author": ""})
        common.write_json(self.level_file("items"), data)
        c, _ = VAL.validate(self.root)
        self.assertIn("vocabulary/上 sentence 3 english id/author", c.errors)


if __name__ == "__main__":
    unittest.main()
