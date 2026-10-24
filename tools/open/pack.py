"""Pack stage: write the output tree from the built structures.

Every JSON file goes through common.write_json (sorted keys, LF, no BOM, no
timestamps, refusal of the scraped course's name). `generated` is the sha256
of sources.json, so a rerun on the same inputs is byte-identical.
"""
import os

from common import LICENSE_OPEN, write_json, write_text, sha256_text, dumps
from readers import svg_for

KVG_CREDIT = "Derived from KanjiVG (http://kanjivg.tagaini.net), copyright 2009-2026 Ulrich Apel, CC BY-SA 3.0"

LICENSES = {
    "CC-BY-SA-4.0": {"name": "Creative Commons Attribution-ShareAlike 4.0 International",
                     "url": "https://creativecommons.org/licenses/by-sa/4.0/"},
    "CC-BY-SA-3.0": {"name": "Creative Commons Attribution-ShareAlike 3.0 Unported",
                     "url": "https://creativecommons.org/licenses/by-sa/3.0/"},
    "CC-BY-4.0": {"name": "Creative Commons Attribution 4.0 International",
                  "url": "https://creativecommons.org/licenses/by/4.0/"},
    "CC-BY-2.0-FR": {"name": "Creative Commons Attribution 2.0 France",
                     "url": "https://creativecommons.org/licenses/by/2.0/fr/"},
    "CC-BY": {"name": "Creative Commons Attribution (version not stated by the source)",
              "url": "https://creativecommons.org/licenses/by/4.0/"},
    "Unicode-3.0": {"name": "Unicode License v3", "url": "https://www.unicode.org/license.txt"},
    "own": {"name": "the product's own terms", "url": ""},
}

SOURCES = {
    "jmdict": {"license": "CC-BY-SA-4.0", "holder": "Electronic Dictionary Research and Development Group",
               "url": "https://www.edrdg.org/wiki/JMdict-EDICT_Dictionary_Project.html",
               "terms": "https://www.edrdg.org/edrdg/licence.html"},
    "kanjidic2": {"license": "CC-BY-SA-4.0", "holder": "Electronic Dictionary Research and Development Group",
                  "url": "https://www.edrdg.org/wiki/KANJIDIC_Project.html",
                  "terms": "https://www.edrdg.org/edrdg/licence.html"},
    "kanjivg": {"license": "CC-BY-SA-3.0", "holder": "Ulrich Apel", "url": "http://kanjivg.tagaini.net",
                "terms": "https://creativecommons.org/licenses/by-sa/3.0/",
                "modifications": "components extracted and renamed; stroke images cut from the SVGs; relicensed as CC BY-SA 4.0 per 3.0 section 4(b)(ii)"},
    "tatoeba": {"license": "CC-BY-2.0-FR", "holder": "Tatoeba Project contributors (author on each sentence)",
                "url": "https://tatoeba.org", "terms": "https://tatoeba.org/en/terms_of_use"},
    "tanaka": {"license": "CC-BY", "holder": "Tanaka Corpus (public domain origin, distributed CC BY via Tatoeba)",
               "url": "https://www.edrdg.org/wiki/Tanaka_Corpus.html"},
    "tanos": {"license": "CC-BY", "holder": "Jonathan Waller", "url": "https://www.tanos.co.uk/jlpt/",
              "terms": "https://www.tanos.co.uk/jlpt/sharing/"},
    "kanjialive": {"license": "CC-BY-4.0", "holder": "Kanji alive", "url": "https://kanjialive.com",
                   "terms": "https://github.com/kanjialive/kanji-data-media"},
    "unicode": {"license": "Unicode-3.0", "holder": "Unicode, Inc.", "url": "https://www.unicode.org/"},
    # names the owner wrote sit inside the BY-SA files (index, items, card answers),
    # so they are released under that file licence rather than the owner's own terms
    "own": {"license": "CC-BY-SA-4.0", "holder": "the product's owner", "url": "",
            "note": "component names written for this product; released under CC BY-SA 4.0 with the open files"},
}

FIELDS = {
    "kanji.meanings": "kanjidic2", "kanji.readings": "kanjidic2", "kanji.grade": "kanjidic2",
    "kanji.freq": "kanjidic2", "kanji.strokes": "kanjidic2", "kanji.parts": "kanjivg",
    "kanji.jlpt": "tanos", "kanji.teach": "computed from the vocabulary inventory",
    "kanji.level": "computed from kanjidic2 and kanjivg", "radical.glyph": "kanjivg",
    "radical.meanings": "kanjidic2, unicode or own (see src.name)", "radical.images": "kanjivg",
    "vocabulary.meanings": "jmdict", "vocabulary.readings": "jmdict", "vocabulary.word_type": "jmdict",
    "vocabulary.nf": "jmdict", "vocabulary.jlpt": "tanos", "vocabulary.sentences": "tatoeba / tanaka",
    "vocabulary.audio": "kanjialive",
}

ATTRIBUTION = [
    "JMdict and KANJIDIC2: Electronic Dictionary Research and Development Group, "
    "CC BY-SA 4.0, https://www.edrdg.org/edrdg/licence.html (entries selected, reordered and reformatted)",
    "KanjiVG: copyright 2009-2026 Ulrich Apel, CC BY-SA 3.0, http://kanjivg.tagaini.net "
    "(components extracted and renamed; stroke images cut from the SVGs)",
    "Example sentences: Tatoeba Project, CC BY 2.0 FR, https://tatoeba.org, authors of the Japanese "
    "and the English named on each sentence; Tanaka Corpus, CC BY, https://www.edrdg.org/wiki/Tanaka_Corpus.html",
    "Component names marked src.name \"own\" were written for this product and are released under CC BY-SA 4.0",
    "JLPT levels: unofficial lists by Jonathan Waller, CC BY, https://www.tanos.co.uk/jlpt/",
    "Word recordings: Kanji alive, CC BY 4.0, https://github.com/kanjialive/kanji-data-media",
]


def image_name(elem):
    return "images/%s.svg" % ("cdp-" + elem[4:].lower() if elem.startswith("CDP-") else "u%04x" % ord(elem))


def write_images(out, images):
    """images: {path: [kvg nodes]}."""
    for path, nodes in sorted(images.items()):
        write_text(os.path.join(out, path), svg_for(nodes, KVG_CREDIT))


def header(level, extra=None):
    h = {"version": 2, "license": LICENSE_OPEN, "attribution": ATTRIBUTION}
    if level is not None:
        h["level"] = level
    h.update(extra or {})
    return h


def write_levels(out, items, cards, lo, hi):
    for lv in range(lo, hi + 1):
        write_json(os.path.join(out, "items", "level-%02d.json" % lv),
                   header(lv, {"items": [r for r in items if r["level"] == lv]}))
        write_json(os.path.join(out, "cards", "level-%02d.json" % lv),
                   header(lv, {"cards": [c for c in cards if c["level"] == lv]}))


def write_index(out, records, generated):
    write_json(os.path.join(out, "search-index.json"),
               header(None, {"generated": generated, "records": records}))


def write_licenses(out, versions, authors):
    sources = {k: dict(v) for k, v in SOURCES.items()}
    for k, v in versions.items():
        if k in sources:
            sources[k]["version"] = v
    write_json(os.path.join(out, "LICENSES.json"),
               {"license": LICENSE_OPEN, "licenses": LICENSES, "sources": sources, "fields": FIELDS})
    write_json(os.path.join(out, "ATTRIBUTION.json"),
               {"attribution": ATTRIBUTION, "sources": sources, "sentence_authors": authors})


def attribution_md(versions, n_authors, n_native):
    return """# Attribution

## Dictionary data

This product uses the JMdict/EDICT and KANJIDIC dictionary files. These files are the property
of the Electronic Dictionary Research and Development Group (https://www.edrdg.org/), and are
used in conformance with the Group's licence (Creative Commons Attribution-ShareAlike 4.0,
https://www.edrdg.org/edrdg/licence.html).
Projects: https://www.edrdg.org/wiki/JMdict-EDICT_Dictionary_Project.html and
https://www.edrdg.org/wiki/KANJIDIC_Project.html. Versions used: JMdict %(jmdict)s,
KANJIDIC2 %(kanjidic2)s. The entries were selected, reordered and reformatted; the open data
files (search-index.json, items/, cards/) are themselves available under CC BY-SA 4.0.

## Kanji component data

Kanji component structure is derived from KanjiVG (http://kanjivg.tagaini.net), release
%(kanjivg)s, copyright 2009-2026 Ulrich Apel, Creative Commons Attribution-ShareAlike 3.0.
Modified: components were extracted and renamed; component images are KanjiVG strokes.
The derived data is distributed under CC BY-SA 4.0 as permitted by section 4(b) of the 3.0 licence.

## Example sentences

Example sentences come from the Tatoeba Project (https://tatoeba.org), Creative Commons
Attribution 2.0 FR, and the Tanaka Corpus (public domain origin, distributed CC BY via Tatoeba,
https://www.edrdg.org/wiki/Tanaka_Corpus.html). Each Tatoeba sentence shows the author of the
Japanese and of the English, with both sentence ids (%(authors)d authors in this build).
Pairs without a recorded author are from the Tanaka Corpus as distributed in examples.utf,
which names no per-sentence author; both sides of those pairs are credited to the Tanaka
Corpus under its CC BY terms. Sentences may have been shortened or corrected.

## JLPT levels

Level labels follow the unofficial lists by Jonathan Waller, https://www.tanos.co.uk/jlpt/,
Creative Commons Attribution. The Japan Foundation and JEES publish no official lists.

## Audio

Word recordings marked "native" are from Kanji alive (https://kanjialive.com),
Creative Commons Attribution 4.0 (https://github.com/kanjialive/kanji-data-media);
%(native)d words in this build. This build contains no synthesised audio.

Component names written for this product (marked "own") appear inside the open data files
and are released under CC BY-SA 4.0 with them. The level ordering and the application are
(c) <owner> 2026.
""" % {"jmdict": versions.get("jmdict", ""), "kanjidic2": versions.get("kanjidic2", ""),
       "kanjivg": versions.get("kanjivg", ""), "authors": n_authors, "native": n_native}


def write_rest(out, sources_text, versions, authors, n_native, manifest, report):
    write_text(os.path.join(out, "sources.json"), sources_text)
    write_licenses(out, versions, authors)
    write_text(os.path.join(out, "attribution.md"), attribution_md(versions, len(authors), n_native))
    write_json(os.path.join(out, "media-manifest.json"), {"files": manifest})
    write_json(os.path.join(out, "report.json"), report)


def generated_of(sources_text):
    return sha256_text(sources_text)


def canonical(obj):
    return dumps(obj)
