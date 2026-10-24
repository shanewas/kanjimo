import io
import os
import tempfile
import unittest

import helpers as H
import build
import common
import fetch


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mirror = os.path.join(self.tmp.name, "mirror")
        self.vendor = os.path.join(self.tmp.name, "vendor")
        os.makedirs(os.path.join(self.mirror, "jmdict"))
        path = H.gz(os.path.join(self.mirror, "jmdict", "JMdict_e.gz"), H.JMDICT)
        self.sha = common.sha256_file(path)
        self.saved = fetch.SOURCES
        fetch.SOURCES = [{"name": "jmdict", "file": "jmdict/JMdict_e.gz", "license": "CC-BY-SA-4.0",
                          "url": "http://127.0.0.1:9/never-used", "sha256": self.sha}]

    def tearDown(self):
        fetch.SOURCES = self.saved
        self.tmp.cleanup()

    def test_import_from_mirror_verifies_and_writes_sources(self):
        self.assertEqual(fetch.main(["--vendor", self.vendor, "--from", self.mirror, "--date", "2026-10-09"]), 0)
        self.assertTrue(os.path.exists(os.path.join(self.vendor, "jmdict", "JMdict_e.gz")))
        src = common.read_json(os.path.join(self.vendor, "sources.json"))
        self.assertEqual(src["fetched"], "2026-10-09")
        row = src["sources"][0]
        self.assertEqual((row["name"], row["sha256"], row["version"], row["license"]),
                         ("jmdict", self.sha, "created 2026-10-08", "CC-BY-SA-4.0"))

    def test_sha_mismatch_fails(self):
        fetch.SOURCES[0]["sha256"] = "0" * 64
        with self.assertRaises(common.BuildError):
            fetch.main(["--vendor", self.vendor, "--from", self.mirror, "--date", "2026-10-09"])
        self.assertFalse(os.path.exists(os.path.join(self.vendor, "sources.json")))

    def test_missing_mirror_file_fails(self):
        fetch.SOURCES[0]["file"] = "jmdict/missing.gz"
        with self.assertRaises(common.BuildError):
            fetch.main(["--vendor", self.vendor, "--from", self.mirror, "--date", "2026-10-09"])

    def test_date_is_required(self):
        with self.assertRaises(SystemExit):
            fetch.main(["--vendor", self.vendor, "--from", self.mirror])

    def test_bad_mirror_file_keeps_vendored_file(self):
        fetch.main(["--vendor", self.vendor, "--from", self.mirror, "--date", "2026-10-09"])
        H.text(os.path.join(self.mirror, "jmdict", "JMdict_e.gz"), "corrupt")
        with self.assertRaises(common.BuildError):
            fetch.main(["--vendor", self.vendor, "--from", self.mirror, "--date", "2026-10-09"])
        dest = os.path.join(self.vendor, "jmdict", "JMdict_e.gz")
        self.assertEqual(common.sha256_file(dest), self.sha)
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_bad_download_keeps_vendored_file(self):
        fetch.main(["--vendor", self.vendor, "--from", self.mirror, "--date", "2026-10-09"])
        saved = fetch.urllib.request.urlopen
        fetch.urllib.request.urlopen = lambda url, timeout: io.BytesIO(b"truncated")
        try:
            with self.assertRaises(common.BuildError):
                fetch.main(["--vendor", self.vendor, "--date", "2026-10-09"])
        finally:
            fetch.urllib.request.urlopen = saved
        dest = os.path.join(self.vendor, "jmdict", "JMdict_e.gz")
        self.assertEqual(common.sha256_file(dest), self.sha)
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_build_rehashes_vendored_files(self):
        fetch.main(["--vendor", self.vendor, "--from", self.mirror, "--date", "2026-10-09"])
        paths, _, _, fetched = build.source_paths(self.vendor)
        self.assertEqual(fetched, "2026-10-09")
        H.text(paths["jmdict"], "changed after fetch")
        with self.assertRaises(common.BuildError):
            build.source_paths(self.vendor)

    def test_missing_blocklist_fails(self):
        with self.assertRaises(common.BuildError):
            common.read_blocklist(os.path.join(self.tmp.name, "blocked-names.csv"))


if __name__ == "__main__":
    unittest.main()
