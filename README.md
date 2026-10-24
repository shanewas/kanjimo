# Kanjimo

A kanji and vocabulary SRS study app: 60 levels, about 9,200 items, reviews and
lessons on a fixed daily quota, a year heatmap and a streak that forgives one
missed day a week. The hosted version runs at https://kanjimo.shanewas.com and
is invite-only.

Content is built from open data only (JMdict, KANJIDIC2, KanjiVG, Tatoeba and
others; `tools/open/`). Mnemonics are not part of this repository.

## Layout

- `app/`: the frontend. Plain HTML, CSS and ES modules, no build step.
  `engine.js`, `ledger.js`, `answer.js`, `kana.js`, `scheduler.js` and
  `text.js` are pure and covered by `node --test`; `store.js` owns
  localStorage; `sync.js` owns every `/api/*` call; `app.js` renders.
- `server/`: FastAPI + PostgreSQL backend for accounts (email code or Google),
  invites, admin, progress sync and the gate nginx uses for content files.
  See `server/README.md`.
- `tools/open/`: fetches the open sources, builds and validates the content
  tree. `tools/release.py` turns code plus content into a release.
- `tools/mnemonics/`: the pipeline that generates and gates mnemonics.
- `site/`, `legal/`: the public about page, terms and privacy policy.

## Run it locally

Static only, with progress kept in the browser, needs a content tree built by
`tools/open/` (see `tools/open/README.md`) under `data/`:

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

then open http://127.0.0.1:8000/app/. With the backend (accounts and sync),
follow "Dev server" in `server/README.md`.

## Checks

```bash
node --test tests/*.test.js
python -m pytest tests/open tests/release -q
python -m pytest server/tests -q      # embedded PostgreSQL via pgserver
grep -rn innerHTML app/ || echo clean # rendering is textContent-only
```

## Licence

Code: GNU AGPL-3.0 (`LICENSE`). The content a release ships carries its own
licences, listed in `data/LICENSE-DATA.txt` and `ATTRIBUTION.json` of each
release.
