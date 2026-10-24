import os
import tempfile
import unittest

import helpers as H
import readers


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_kanjidic2(self):
        kd, header = readers.read_kanjidic2(H.gz(os.path.join(self.d, "k.xml.gz"), H.KANJIDIC2))
        self.assertEqual(header["database_version"], "2026-281")
        self.assertEqual(kd["上"]["on"], ["ジョウ", "ショウ"])
        self.assertEqual(kd["上"]["kun"], ["うえ", "-うえ", "あ.げる"])
        self.assertEqual(kd["上"]["meanings"], ["above", "up"])      # m_lang="fr" dropped
        self.assertEqual(kd["上"]["nanori"], ["あげ"])
        self.assertEqual((kd["上"]["grade"], kd["上"]["freq"], kd["上"]["strokes"]), (1, 35, 3))
        self.assertIsNone(kd["卜"]["freq"])

    def test_kanjivg_parts_wrappers_splits_and_cdp(self):
        path = H.zipped(os.path.join(self.d, "kvg.zip"), H.KANJIVG)
        kvg = readers.read_kanjivg(path, ["上", "一", "国", "無", "林"])
        self.assertNotIn("無", kvg)
        self.assertEqual([(p["element"], p["position"]) for p in kvg["上"]["parts"]], [("卜", "top"), ("一", "bottom")])
        self.assertEqual(kvg["上"]["strokes"], 3)
        self.assertEqual(kvg["一"]["parts"], [])
        parts = kvg["国"]["parts"]
        self.assertEqual([p["element"] for p in parts], ["囗", "CDP-8BC4"])
        self.assertEqual(len(parts[0]["nodes"]), 2)        # kvg:part 1 and 2 merged
        svg = readers.svg_for(parts[0]["nodes"], "credit")
        self.assertIn('<path d="M1,1"/>', svg)
        self.assertIn('<path d="M9,9"/>', svg)
        self.assertIn("credit", svg)
        self.assertEqual([(p["element"], p["position"], len(p["nodes"])) for p in kvg["林"]["parts"]],
                         [("木", "left", 1), ("木", "right", 1)])       # a repeat is not a split part

    def test_jmdict_entities_and_fields(self):
        path = H.gz(os.path.join(self.d, "JMdict_e.gz"), H.JMDICT)
        codes, created = readers.jmdict_entities(path)
        self.assertEqual(created, "2026-10-08")
        self.assertEqual(codes["noun (common) (futsuumeishi)"], "n")
        entries, n = readers.read_jmdict(path, lambda e: True)
        self.assertEqual(n, 8)
        e = entries[0]
        self.assertEqual(e["k"][0]["pri"], ["news1", "nf01"])
        self.assertEqual(e["s"][0]["pos"], ["n"])
        self.assertEqual(e["s"][1]["stagr"], ["かみ"])
        self.assertEqual(entries[1]["k"][1]["inf"], ["rK"])
        self.assertEqual(entries[1]["s"][0]["misc"], ["uk"])
        self.assertEqual(readers.nf_rank(["news1", "nf05", "nf12"]), 5)

    def test_tanos(self):
        v = H.text(os.path.join(self.d, "v.html"), H.TANOS_VOCAB)
        k = H.text(os.path.join(self.d, "k.html"), H.TANOS_KANJI)
        t = readers.read_tanos({(5, "vocab"): v, (5, "kanji"): k})
        self.assertEqual(t[5]["vocab"], [("一つ", "ひとつ", "one"), ("", "ありがとう", "thank you"), ("上/上方", "うえ", "above")])
        self.assertEqual(t[5]["kanji"], {"上", "一"})

    def test_tatoeba_and_examples(self):
        links = readers.read_links(H.bz(os.path.join(self.d, "l.bz2"), "10\t900\n10\t20\n11\t30\n"))
        self.assertEqual(links["10"], ["20", "900"])
        jp = readers.read_jpn(H.bz(os.path.join(self.d, "j.bz2"), "10\tjpn\t上に行く。\tuser\t\\N\t2020\n11\tjpn\t猫。\t\\N\t\\N\t\\N\n12\tjpn\tx\tu\t\\N\t\\N\n"), {"10", "11"})
        self.assertEqual(jp["10"], ("上に行く。", "user"))
        self.assertEqual(jp["11"], ("猫。", ""))
        self.assertNotIn("12", jp)
        eng = readers.read_eng(H.bz(os.path.join(self.d, "e.bz2"), "20\teng\tGo up.\tdave\t\\N\t2020\n"
                                    "30\teng\tCat.\t\\N\t\\N\t\\N\n40\teng\tNo.\tx\t\\N\t\\N\n"), {"20", "30"})
        self.assertEqual(eng, {"20": ("Go up.", "dave"), "30": ("Cat.", "")})
        ex, lemma = readers.read_examples(H.gz(os.path.join(self.d, "ex.gz"), "A: 上に行く。\tGo up.#ID=20_10\nB: 上(うえ)[01]{上に} 行く{行く}~\n"), {"上"})
        self.assertEqual((ex["10"]["en"], ex["10"]["en_id"]), ("Go up.", "20"))
        self.assertEqual(ex["10"]["hits"], [("上", "うえ", "上に", False)])
        self.assertEqual(lemma["行く"], 1)

    def test_kanjialive(self):
        rows = readers.read_kanjialive(H.text(os.path.join(self.d, "ka.csv"), H.KA_DATA))
        self.assertEqual(rows[0], ("上", "jou-ue", 0, "上", ["うえ"], "above"))
        self.assertEqual(rows[1][3:5], ("上手", ["じょうず", "うわて"]))


if __name__ == "__main__":
    unittest.main()
