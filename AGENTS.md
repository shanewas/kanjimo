# AGENTS.md

Static app, no build, no npm. Before committing, run the checks listed in
README under "Checks", plus `node --check` on every file in `app/`.

Rules that hold everywhere:

- Render with textContent only. No innerHTML, no HTML strings.
- `app/engine.js`, `ledger.js`, `answer.js`, `kana.js`, `scheduler.js` and
  `text.js` stay pure: no DOM, no storage, no `Date.now()`. A new rule goes
  there, with a test beside it.
- `app/store.js` is the only module that touches progress in localStorage.
  A schema change bumps the version and keeps a migration from every older
  one. The one exception is the theme key `jstudy.theme`, read in
  `app/theme.js` (a blocking script) before first paint and toggled in
  `app.js`; keep the literal identical in both.
- WaniKani's rules (stages, waits, miss formula, unlocks, level-up) are not
  design knobs. Pacing and presentation are.
- Design decisions live in `DESIGN.md`.
