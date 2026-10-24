# Open-data content pipeline

Builds the product's study content from open sources only (JMdict, KANJIDIC2,
KanjiVG, Tatoeba with the Tanaka word index, the tanos JLPT lists, Kanji alive
recordings). Stdlib Python 3.11, deterministic output, no network at build time.
Nothing under the repo's `data/` directory is read; the pack step refuses such
paths and refuses any output that names the scraped course.

```
set PYTHONUTF8=1
py -3.11 -I tools\open\fetch.py --vendor BUILD\vendor --date 2026-10-09 [--from MIRROR_DIR]
py -3.11 -I tools\open\build.py --vendor BUILD\vendor --out BUILD\open [--levels 1-3]
py -3.11 -I tools\open\validate.py BUILD\open            # must end in "0 errors"
py -3.11 -m unittest discover -s tests\open -v            # hermetic, temp dirs only
```

`fetch.py` pins every source by sha256 (table at the top of the file) and
writes `vendor/sources.json`; `--from` imports a local mirror instead of
downloading. Each file is verified as a `.part` copy before it replaces the
vendored one, so a failed fetch leaves the old file in place. `--date` is
required: it is the day the pinned files were downloaded (2026-10-09 for the
current pins), recorded in `sources.json` instead of today's date so a re-fetch
of the same pins gives the same `sources.json`. `build.py` re-hashes every
vendored file against `sources.json` and stops on a mismatch, and stops if
`overrides/blocked-names.csv` is missing; it then runs every stage and prints
counts; a rerun on the same vendor tree is byte-identical (`generated` is the
sha256 of `sources.json`).

## Stages (one module each)

| Module | Rule |
|---|---|
| `kanji.py` | inventory = KANJIDIC2 grades 1-6 and 8 (2,136 joyo); keyword = first meaning after the mechanical clean-up, clashes reported; readings on/kun(+okurigana)/nanori; ordering = newspaper rank + 150 x grade tier + 20 x strokes + 60 x (parts beyond two), cut into 60 equal slices; taught reading = the one most of the word inventory uses, on'yomi on ties (`overrides/readings.csv`) |
| `components.py` | KanjiVG parts (only `kvg:part` pieces are merged, so 林 keeps both 木); a part that is a kanji taught two or more levels earlier is referenced as that kanji; a shape used by one kanji is shown inline; the rest are component items (`radical/<glyph>`, `radical/cdp-<code>`); names from KANJIDIC2, then a shortened Unicode radical name, else `overrides/components.csv` (`status=proposed` rows are for the owner's review; such names ship in the open files under CC BY-SA 4.0, `src.name` "own"); names on `overrides/blocked-names.csv` are refused, matched ignoring case, outer spaces and a plural "s" (the file must exist; `validate.py` checks the same) |
| `vocab.py` | candidates = JMdict entries with a common tag or nf rank <= 30, or on a tanos list, written with inventory kanji only, at most four kanji, not archaic/rare/proper noun/particle; per kanji at least 2 and at most 9 words preferring the taught reading, then other readings, then frequency; kana-only words capped at 300 |
| `levels.py` | word level = highest kanji level, ranked by nf then Tatoeba lemma count, capped at ceil(words / 60 x 1.25) per level with spill-over |
| `sentences.py` | up to three Tatoeba/Tanaka pairs: 8-30 characters, English of two or more words, known author for the Japanese and the English (`author`, `en_id`, `en_author`; a Tatoeba sentence takes an authored translation from `eng_sentences_detailed`, a Tanaka pair's English is credited to the Tanaka Corpus since `examples.utf` names no author), kanji at or below the word's level (one level above at half score), checked examples and shorter sentences first |
| `audio.py` | Kanji alive recordings matched by form and reading; files are not downloaded, `media-manifest.json` lists the archive members |
| `pack.py` | `search-index.json`, `cards/level-NN.json`, `items/level-NN.json`, `images/*.svg`, `LICENSES.json`, `ATTRIBUTION.json`, `attribution.md`, `sources.json`, `media-manifest.json`, `report.json` |

`blocklist.py` regenerates `overrides/blocked-names.csv` from the app's
current radical names versus KANJIDIC2 (the only permitted read of `data/`).
