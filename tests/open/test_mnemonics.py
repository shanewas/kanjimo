import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "mnemonics"))
import gate  # noqa: E402
import prepare  # noqa: E402

KANJI = {
    "会": {"readings": {"on": ["かい", "え"], "kun": [{"stem": "あ", "okurigana": "う"}]}, "teach": {"reading": "かい"}},
    "社": {"readings": {"on": ["しゃ"], "kun": [{"stem": "やしろ", "okurigana": ""}]}, "teach": {"reading": "しゃ"}},
    "子": {"readings": {"on": ["し", "す"], "kun": [{"stem": "こ", "okurigana": ""}]}, "teach": {"reading": "し"}},
    "学": {"readings": {"on": ["がく"], "kun": []}, "teach": {"reading": "がく"}},
    "校": {"readings": {"on": ["こう"], "kun": []}, "teach": {"reading": "こう"}},
}


class SegmentTests(unittest.TestCase):
    def test_taught_readings_are_fixed(self):
        parts = prepare.segment("会社", "かいしゃ", KANJI)
        self.assertEqual(parts, [("会", "かい"), ("社", "しゃ")])
        self.assertTrue(all(prepare.taught_ok(c, r, KANJI, "会社") for c, r in parts))

    def test_gemination_counts_as_the_taught_reading(self):
        parts = prepare.segment("学校", "がっこう", KANJI)
        self.assertEqual(parts, [("学", "がっ"), ("校", "こう")])
        self.assertTrue(all(prepare.taught_ok(c, r, KANJI, "学校") for c, r in parts))

    def test_an_untaught_reading_needs_a_mnemonic(self):
        parts = prepare.segment("子", "こ", KANJI)
        self.assertEqual(parts, [("子", "こ")])
        self.assertFalse(prepare.taught_ok("子", "こ", KANJI, "子"))

    def test_kana_okurigana_and_misfits(self):
        self.assertEqual(prepare.segment("会う", "あう", KANJI), [("会", "あ"), ("う", "う")])
        self.assertIsNone(prepare.segment("会社", "かいぎ", KANJI))


class GateTests(unittest.TestCase):
    def test_jaccard_and_long_runs(self):
        ref = "the quick brown fox jumps over the lazy dog near the river bank today"
        ref3 = gate.grams(gate.words(ref), 3)
        runs = gate.grams(gate.words(ref), gate.RUN)
        j, run = gate.check(ref, ref3, runs)
        self.assertEqual((j, run), (1.0, True))
        j, run = gate.check("a slow green turtle naps under a tall oak tree all afternoon", ref3, runs)
        self.assertEqual((j, run), (0.0, False))
        _, run = gate.check("then the quick brown fox jumps over the lazy dog again", set(), runs)
        self.assertTrue(run)


if __name__ == "__main__":
    unittest.main()
