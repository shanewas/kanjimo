import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import release  # noqa: E402


def content_tree(root: Path, extra: str = "") -> Path:
    (root / "cards").mkdir(parents=True)
    (root / "search-index.json").write_text(json.dumps({"records": [], "note": extra}), encoding="utf-8")
    (root / "ATTRIBUTION.json").write_text("{}", encoding="utf-8")
    (root / "report.json").write_text("{}", encoding="utf-8")
    (root / "cards" / "level-01.json").write_text('{"cards": []}', encoding="utf-8")
    return root


class ReleaseTest(unittest.TestCase):
    def test_builds_server_and_www_with_gzip_twins(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            release.build(content_tree(tmp / "open"), tmp / "rel", "abc123")
            www = tmp / "rel" / "www"
            self.assertTrue((tmp / "rel" / "server" / "jstudy" / "main.py").is_file())
            self.assertFalse(list((tmp / "rel" / "server").rglob("__pycache__")))
            self.assertEqual((www / "app" / "version.txt").read_text(encoding="utf-8"), "abc123\n")
            self.assertTrue((www / "legal" / "terms.html").is_file())
            card = www / "data" / "cards" / "level-01.json"
            self.assertEqual(gzip.decompress((card.parent / "level-01.json.gz").read_bytes()), card.read_bytes())
            self.assertFalse((www / "data" / "report.json").exists())

    def test_refuses_the_scraped_course(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with self.assertRaises(release.ReleaseError):
                release.build(content_tree(tmp / "open", "see WaniKani"), tmp / "rel", "x")
            with self.assertRaises(release.ReleaseError):
                release.build(release.REPO / "data", tmp / "rel2", "x")


if __name__ == "__main__":
    unittest.main()
