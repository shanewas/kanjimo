#!/usr/bin/env python3
"""Fetch the pinned open-data sources into a vendor directory and write sources.json.

Usage:
  py -3.11 -I tools/open/fetch.py --vendor DIR --date YYYY-MM-DD [--from MIRROR_DIR]

--from imports the files from a local mirror laid out like the vendor tree
(one subdirectory per source); without it the official URLs are downloaded.
Either way every file's sha256 must match the pin below, or the run fails
and the file already in the vendor tree is left as it was. --date is the day
the pinned files were downloaded; it goes into sources.json, whose hash is
the build's `generated`, so it is given rather than read from the clock.
The downloads are data: nothing in them is executed.
"""
import argparse
import gzip
import os
import re
import shutil
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BuildError, setup, sha256_file, write_json  # noqa: E402

EDRDG = "https://www.edrdg.org/edrdg/licence.html"
SOURCES = [
    {"name": "jmdict", "file": "jmdict/JMdict_e.gz", "license": "CC-BY-SA-4.0",
     "url": "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
     "sha256": "3d5fc0a0f768df4d044744732348f09a47db97a6286c2de1d565e5766212a1ea"},
    {"name": "kanjidic2", "file": "kanjidic2/kanjidic2.xml.gz", "license": "CC-BY-SA-4.0",
     "url": "http://www.edrdg.org/kanjidic/kanjidic2.xml.gz",
     "sha256": "5fc25740c21180e0c2983d3ed546a8009d7891d9dceb4714cd36dd528be2bb58"},
    {"name": "kanjivg", "file": "kanjivg/kanjivg-20260714-main.zip", "license": "CC-BY-SA-3.0",
     "url": "https://github.com/KanjiVG/kanjivg/releases/download/r20260714/kanjivg-20260714-main.zip",
     "sha256": "b5df6cd2bc249dd49b8041eb99e38ba9f8dc6b9ea57962a80084b4a315d1a7fc"},
    {"name": "examples", "file": "examples/examples.utf.gz", "license": "CC-BY",
     "url": "http://ftp.edrdg.org/pub/Nihongo/examples.utf.gz",
     "sha256": "70939ffff2e9f21cc40fe717aaeba4bff14b7ef4e443186ab5805a87448cd85b"},
    {"name": "tatoeba-jpn", "file": "tatoeba/jpn_sentences_detailed.tsv.bz2", "license": "CC-BY-2.0-FR",
     "url": "https://downloads.tatoeba.org/exports/per_language/jpn/jpn_sentences_detailed.tsv.bz2",
     "sha256": "f597d8f76473181f7fae482481030a31565fb427d64d2def8595218d128c6981"},
    {"name": "tatoeba-eng", "file": "tatoeba/eng_sentences_detailed.tsv.bz2", "license": "CC-BY-2.0-FR",
     "url": "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences_detailed.tsv.bz2",
     "sha256": "1d8c40545b4af2c6531d1a8b64941fa9d0fa3ee5bcc11cb705c8d8c1fd930c84"},
    {"name": "tatoeba-links", "file": "tatoeba/jpn-eng_links.tsv.bz2", "license": "CC-BY-2.0-FR",
     "url": "https://downloads.tatoeba.org/exports/per_language/jpn/jpn-eng_links.tsv.bz2",
     "sha256": "0bff645c5e4c172810710d4844409041932826882547f07be1ac1d4d63314705"},
    {"name": "kanjialive", "file": "kanjialive/ka_data.csv", "license": "CC-BY-4.0",
     "url": "https://raw.githubusercontent.com/kanjialive/kanji-data-media/master/language-data/ka_data.csv",
     "sha256": "7b463876a0837bfb1f754a4e1bec43617b62f92b9839bbdf060d6ad0d8dbaf65"},
]
TANOS_SHA = {
    (5, "vocab"): "20f5573aaf1cf73dd79f6556d8314a68464d6d6da2ac7cf2eef3e2fe34273d16",
    (5, "kanji"): "07e03ec4b0fe8ec4141aae3713c141e43a03df2907f78bdef3a7641d9b561de9",
    (4, "vocab"): "e4564d8257c240183c1a92d878426665ae72a4d18db3ed87208155ea38de341b",
    (4, "kanji"): "7922a19751c304ff4d62e391fa72bb8f38b6cc3220f87e8c657bf0a6a966d873",
    (3, "vocab"): "76a9bb99728f210a7a70eccce154c0d265d7a38a6f251926c3fef6b2f94eab6f",
    (3, "kanji"): "db743d52580b36626270cfeb184552295654d2df7c6b7bfd9c2b9d7ceaee25ab",
    (2, "vocab"): "400fae935e09e40e4b6b2dea1b2ca24ff6f4841a3fe2386ffb97de7d0e485f55",
    (2, "kanji"): "da462c435bbfd6ae12bf36c14d6638acfef7e28c7f17460b95f9f77a35eaad83",
    (1, "vocab"): "dfda052e5c5a81155647196da3e95cfc89130b16dfd5bd79ac091a8d6185e2b9",
    (1, "kanji"): "8a772e01fb54e32fc718070b1b3122d080c52125a1537a034b87be42c5932f67",
}
for _lv in (5, 4, 3, 2, 1):
    for _kind in ("vocab", "kanji"):
        SOURCES.append({
            "name": "tanos-n%d-%s" % (_lv, _kind), "file": "tanos/jlpt%d_%s.html" % (_lv, _kind),
            "license": "CC-BY", "url": "https://www.tanos.co.uk/jlpt/jlpt%d/%s/" % (_lv, _kind),
            "sha256": TANOS_SHA[(_lv, _kind)],
            "note": "page read from a Wayback Machine copy of the URL (the host did not resolve on 2026-10-09)"})


def version_of(name, path):
    """Version string from the file's own header; empty when the file has none."""
    if name == "jmdict":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            m = re.search(r"JMdict created: (\d{4}-\d{2}-\d{2})", f.read(600000))
        return "created " + m.group(1) if m else ""
    if name == "kanjidic2":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            head = f.read(20000)
        v = re.search(r"<database_version>([^<]*)</database_version>", head)
        d = re.search(r"<date_of_creation>([^<]*)</date_of_creation>", head)
        return "%s (created %s)" % (v.group(1) if v else "", d.group(1) if d else "")
    if name == "kanjivg":
        m = re.search(r"kanjivg-(\d{8})", os.path.basename(path))
        return "r" + m.group(1) if m else ""
    return ""


def fetch_one(src, vendor, mirror):
    dest = os.path.join(vendor, *src["file"].split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    # verify a .part copy before it replaces dest, so a bad download or mirror
    # file never overwrites a good vendored one
    part = dest + ".part"
    if mirror:
        origin = os.path.join(mirror, *src["file"].split("/"))
        if not os.path.exists(origin):
            raise BuildError("missing in mirror: " + origin)
        if os.path.abspath(origin) == os.path.abspath(dest):
            part = dest
        else:
            shutil.copyfile(origin, part)
    else:
        with urllib.request.urlopen(src["url"], timeout=120) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
    got = sha256_file(part)
    if got != src["sha256"]:
        if part != dest:
            os.remove(part)
        raise BuildError("sha256 mismatch for %s: expected %s got %s" % (src["file"], src["sha256"], got))
    if part != dest:
        os.replace(part, dest)
    return dest


def main(argv=None):
    setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--from", dest="mirror", default=None)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD the pinned files were downloaded")
    args = ap.parse_args(argv)
    rows = []
    for src in SOURCES:
        dest = fetch_one(src, args.vendor, args.mirror)
        row = {k: v for k, v in src.items()}
        row["version"] = version_of(src["name"], dest)
        rows.append(row)
        print("verified %-16s %s  %s" % (src["name"], src["sha256"][:16], row["version"]))
    write_json(os.path.join(args.vendor, "sources.json"), {"fetched": args.date, "sources": rows})
    print("sources: %d files, %d sha256 verified, 0 mismatches" % (len(rows), len(rows)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as e:
        print("ERROR: %s" % e)
        sys.exit(1)
