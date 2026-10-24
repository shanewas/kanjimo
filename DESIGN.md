# Design System: Kanjimo

## Product Context
- **What this is:** A kanji and vocabulary study app over about 9,200 items in 60 levels, built from open data. WaniKani-style SRS rules run underneath; the surface hands out a fixed daily quota, a Done screen and a year heatmap, for a learner who needs visible progress every day and no decisions before starting.
- **Who it's for:** One solo learner, N1 in 1 year, low daily study time.
- **Space/industry:** Spaced-repetition study tools (WaniKani-style reviews, calm-focus direction chosen over game-y study apps).
- **Project type:** Local-first static web app (plain HTML/CSS/JS, no build) with an optional sync backend.

## Aesthetic Direction
- **Direction:** Warm-paper study space with colour where it carries meaning. Quiet surfaces and one pine accent for actions; every glyph in a lesson or review sits on a band in its type colour (radical azure, kanji madder, vocabulary purple), as on WaniKani, so the kind of item reads before the item does.
- **Decoration level:** Intentional. Subtle paper grain on the page background; soft radial light on glyph bands; flat surfaces elsewhere. Grain disables under `prefers-reduced-motion`.
- **Mood:** A bright desk in the morning: the next action is obvious, progress shows in colour (pine to purple gradients on bars, the ring and the Done headline), reviews feel like turning pages.
- **Anti-slop guards:** Purple marks vocabulary, Guru and the far end of progress gradients; pine stays the action colour. No card grids as a first impression; browse uses band rails plus dense glyph rows. No single radius on every element; no glow shadows; no confetti.

## Typography
- **Display:** Fraunces (optical sizing, 400/600): product voice, Today numbers, wrap-up headings.
- **Body/UI:** Instrument Sans (400/500/600 + italic): everything functional.
- **Japanese:** Noto Sans JP (400/500/700): glyphs, readings, context sentences. Fallback chain: `"Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, sans-serif`.
- **Data/Code:** system mono stack (`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`): counts, timers, debug.
- **Loading:** Google Fonts `<link>` tags at runtime; system fallbacks when offline.
  - `https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600`
  - `https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400;0,500;0,600;1,400`
  - `https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700`
- **Scale:** micro 12 / small 14 / body 16 / lead 20 / title 28 (Fraunces) / display 40 (Fraunces) / glyph-review 120 / glyph-item 96. Body never below 16px.

## Color
- **Approach:** Restrained. Paper neutrals + ink text + one pine accent + type-coded labels (always label + color, never color alone).
- **Light:**
  - `--paper: #f2eee1` (page), `--surface: #faf7ec` (cards/inputs), `--surface-2: #e9e3d2` (wells, hover)
  - `--ink: #211c12` (14.6:1 on paper), `--ink-muted: #6e6757` (4.84:1), `--line: #ddd5c0`
  - `--accent (pine): #2e5b44` (white text 7.79:1): primary actions, due count, progress fill
  - Type codes: `--radical (azure): #2b6cb0` (4.67:1), `--kanji (madder): #b03a2e` (5.18:1), `--vocab (purple): #7b3fa0` (5.91:1)
  - Bands (white text on them): `--radical-band` 5.42:1, `--kanji-band` 6.02:1, `--vocab-band` 6.86:1, `--ok-band: #2e7d43` for a right answer, `--kanji-band` for a wrong one
  - SRS groups (Progress tiles): Apprentice `#b8336f`, Guru `#7b3fa0`, Master `#2b6cb0`, Enlightened `#1d7a94`, Burned `#4a4438`
  - Semantic: success `--accent`, error `--kanji`, info `--radical`
- **Dark:** `--paper: #161310`, `--surface: #201c16`, `--ink: #eae4d3` (14.57:1), `--ink-muted: #a49c88` (6.78:1), `--accent: #7fb894` (dark text 8.10:1), type and SRS codes lightened one step (`--vocab: #c49be3`, 8.06:1), bands deepened one step so white text keeps its contrast.
- **Dark mode strategy:** Same layout, remapped surfaces; accent lightened rather than saturated; grain opacity halved.

## Spacing
- **Base unit:** 8px. **Density:** Comfortable.
- **Scale:** 2xs 2 / xs 4 / sm 8 / md 16 / lg 24 / xl 32 / 2xl 48 / 3xl 64.

## Layout
- **Approach:** Grid-disciplined. Single centered measure for Today/Review (720px); browse/search widen to 1024px.
- **Grid:** 12 columns ≥1024px, 8 columns 768–1023px, 4 columns below 768px.
- **Max content width:** 1024px browse/search, 720px review/item.
- **Border radius:** sm 6 (chips, inputs), md 10 (buttons), lg 16 (panels), full 9999 (avatar dots, toggles). Never one radius everywhere.
- **Glance hierarchy (P1 gates on these):**
  - Today: due count → Start CTA → streak/progress strip.
  - Review: glyph → answer input → grade buttons.
  - Item: identity header (glyph/reading/meaning/audio) → mnemonics → context → composition chips.
  - Browse: band rails with progress bars → dense glyph rows. Search: input → keyboard-first result list.

## Motion
- **Approach:** Minimal-functional. Only transitions that aid comprehension: input focus, the answer pill popping in on reveal (200ms), panels rising into place on a view change (220ms), bars filling (300ms).
- **Easing:** enter ease-out, exit ease-in, move ease-in-out.
- **Duration:** micro 50–100ms, short 150–250ms, medium 250–400ms. Nothing above 400ms.
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` disables grain animation, crossfades, and autoplay; all state changes become instant.

## Interaction States (exact copy)
- **Today, work owed:** ring "12 / 50 reviews" + "2 / 5 lessons · + 83 waiting" + [Start session]. With autostart on, opening the app skips this screen.
- **Today, quota met:** ring full + "Done for today." + muted [Keep going] when anything remains.
- **Today, nothing owed:** "Nothing to do yet. Lessons open as items reach Guru." + [Browse levels]. The day counts as done.
- **Today, nothing due right now:** "Next: 6 reviews at 12:00 (in 2h)" under the button, in pine.
- **Level line:** "Level 1 · 16/18 kanji passed · 1 more to level 2" over a pine-to-purple bar.
- **First run:** "Begin." + [Start Level 1] [Pick a start level] + Browse/Search links. Never an empty ring.
- **Lesson pane:** "Lesson 2 of 5 · New kanji · Level 1", the glyph band with the meaning under the glyph, step tabs [Meaning] [Reading] (radicals: [Name]).
  - Meaning step: "Built from these radicals" chips joined by "+" (vocabulary: kanji chips; radicals instead end with "Found in kanji"), "Also accepted: …", the meaning mnemonic with its keywords marked, a Hint box when the item has one.
  - Reading step: kanji show On'yomi / Kun'yomi / Nanori rows, the group the mnemonic teaches large with "learn this one" and the rest muted; vocabulary shows its reading large. Audio plays once on arrival, beside "Say it out loud with the audio." Then the reading mnemonic, a Hint box, and "In a sentence": up to three Japanese lines, each over its English.
  - The batch sits at the bottom as type-coloured tiles; [Back] [Next] or [Start quiz]. Enter or → moves on, ← goes back.
- **Keyword marks:** radical names tinted azure, kanji meanings madder, vocabulary meanings purple, readings in an ink pill, the way WaniKani's pages colour them. Marks come from the item's own answers and its parts, matched as whole words.
- **Prompt:** "Item 7 of 55 · Level 3" + a thin progress bar, the glyph band, then the ask bar: "Kanji **Reading**" on ink, "Vocabulary **Meaning**" on a light bar, "Radical **Name**" for radicals. The answer box says what it wants ("答え (romaji turns into kana)" or "Meaning, in English"). No audio before the answer. The previous item's move sits above the band: "上 · Apprentice 4 → Apprentice 3".
- **Shake:** the box shakes, a hint appears under it ("Readings are kana. Finish the romaji so it converts."), nothing is recorded.
- **Answered right:** the typed answer in a green pill, "Correct." + listed answers, [Missed it] [Got it · Apprentice 3 · 1d] with Got it outlined as the default. Vocabulary readings play their audio once. Enter advances.
- **Answered wrong:** the typed answer in a red pill, "Not quite. Correct answer: …", and the mnemonic for the missed half already open below it. [Missed it] is outlined as the default. The half comes back within three prompts.
- **Pause:** "10 done" + "40 left in this session. Stop here and the rest waits; nothing is lost." + [Keep going] [Stop].
- **Done:** "Done for today." (or "Done.") in a pine-to-purple gradient, minutes + streak, any "Level 4 unlocked." notice, reviewed / first-try ("–" with no reviews) / lessons / reached Guru today / still due, "New today" tiles linking to each item, "Next: 6 reviews at 12:00 (in 2h)", "Level 3: 61% → 68%", "N1 in 268 days · projected level 9", [Today] [Keep going].
- **Progress:** year of day cells to the exam date (done = pine, some = light pine, frozen = outlined, ahead = hairline), legend, streak + days this month, stage tiles topped and numbered in their SRS colour, level bar.
- **Item page:** the glyph on a type-coloured tile, meaning, reading rows as in the lesson, mnemonics with Hint boxes, context sentences as Japanese over English.
- **Fetch fail:** "Couldn't load {file}. Check the server is running." + [Retry].
- **Parse fail:** "Couldn't read {file}. It may be corrupt." + [Retry].
- **Corrupt progress:** "Saved progress looked damaged, so this session started fresh." + [Download damaged data].
- **Migrated progress:** "Progress migrated to one stage per item. Nothing was lost; the old data is kept as a backup."
- **Storage full:** "Browser storage is full, progress paused. Export a backup, free space, then keep going."
- **Audio missing/offline:** Speaker control renders muted with tooltip "Audio unavailable"; reviews continue.
- **Search zero hits:** "No matches for '{q}'." + [Clear search].
- **Empty states** carry warmth + one primary action + context; error states always offer the next step.

## Session Micro-Flow (state machine)
```
open ─autostart─▶ session: reviews (day's quota, lowest stage first) ─▶ pause every 10 ─▶ lesson panes ×5 ─▶ quiz ─▶ Done
prompt ─Enter─▶ check ─┬─ shake: re-prompt, nothing recorded
                       └─ answered: Enter accepts the verdict, 1 / 2 override
answered ─▶ other half next (back to back) │ item complete ─▶ one stage move, shown on the next prompt
miss ─▶ that half returns within three prompts; misses sum into one drop when the item completes
End early / nav away ─▶ day's done flag settled, no wrap-up │ reload mid-session ─▶ resumes
```
- A wrong answer opens the mnemonic inline at once, without leaving the card.
- Progress ("Item 7 of 55") and End early persist at the top of every prompt.
- New items get a study pane (two steps for kanji and vocabulary) before their quiz; the pane never repeats after a reload.

## Learning Principles
Each surface choice above leans on a finding from learning research. The SRS rules underneath are WaniKani's and don't change.
- **Retrieval before exposure.** Testing beats restudy for retention (Karpicke & Roediger 2008, *Science* 319; Dunlosky et al. 2013, *PSPI* 14(1) rate practice testing and distributed practice the only two high-utility techniques). So nothing on a prompt gives the answer away: audio plays only after a reading is answered.
- **Immediate feedback after a miss.** A failed attempt followed at once by the answer teaches more than seeing the answer alone; delayed feedback loses most of that (Kornell, Hays & Bjork 2009, *JEP:LMC* 35(4); Hays, Kornell & Bjork 2012). Errors made with confidence are the ones corrected best (Metcalfe 2017, *Annual Review of Psychology* 68). So a miss shows the correct answer and the mnemonic without a click.
- **Parts at first sight.** Pointing out a character's components when it is first presented helps recall most (Taft & Chung 1999); component analysis beat whole-kanji memorising for retention (Flaherty & Noguchi 1998, *JALT Journal* 20(2)). So kanji lessons open with their radicals, vocabulary lessons with their kanji, radicals with kanji they appear in.
- **Keyword mnemonics, made visible.** The keyword method (Atkinson & Raugh 1975, *Journal of Experimental Psychology: Human Learning and Memory*) links a sound-alike keyword to the meaning through an image; WaniKani's mnemonics are built that way. Marking the keywords in the text points the eye at the link.
- **Say it aloud.** Words produced aloud are remembered 10 to 25% better than words read silently (MacLeod et al. 2010, *JEP:LMC* 36). So the reading step plays the audio and asks for the word out loud.
- **Context of good quality.** Context sentences that carry clear clues build meaning knowledge more than sheer repetition (Webb 2008, *Reading in a Foreign Language* 20(2)). So sentences show as Japanese over English, three at a time, instead of one run-on paragraph.
- **Come back on time.** Spacing has an optimal gap, and a gap that's too short costs more than one that's too long (Cepeda et al. 2008, *Psychological Science* 19(11)); repeated spaced retrieval to criterion is what makes learning durable (Rawson & Dunlosky, successive relearning). So Today and Done say when the next reviews open.
- **A daily cue.** Habit automaticity grows fastest in the first repetitions and a single missed day doesn't reset it (Lally et al. 2010, *European Journal of Social Psychology* 40). That backs the morning auto-open and the one-miss-a-week freeze.

## Responsive Contract
- Desktop-first, usable to 360px. Full-width answer input; grade buttons thumb-reachable (min 44px targets); no horizontal scroll at any width.
- Preview and P1 QA screenshot 1280 / 768 / 360px.

## Accessibility Baseline
- WCAG AA pairs listed under Color; visible `:focus-visible` rings on all interactive elements.
- Full-keyboard review: type → Enter submits → Enter advances (1 / 2 override the checker); Enter steps through lesson panes and the pause.
- Reduced-motion disables grain, crossfade, autoplay. Type is always label + color.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-09-17 | Warm-paper minimal, pine accent, ochre vocab (no purple) | Calm-focus direction; avoids the top AI-slop tells |
| 2026-09-17 | Fraunces + Instrument Sans + Noto Sans JP | Editorial display, functional body, proper Japanese; all verified servable |
| 2026-09-17 | Dense glyph rows over card grids for browse | 9,400 items need density; cards would read as generic slop |
| 2026-09-17 | First-run Today variant required in P0 preview | Day-1 empty queue is the top product gap from review |
| 2026-10-08 | One SRS stage per item, WaniKani's miss formula once per item | Per-card state stranded halves and made a miss free |
| 2026-10-08 | Daily quota ring instead of the true due count | A 400-review pile after a bad week is the quit trigger |
| 2026-10-08 | Forgiving streak: one frozen miss per seven days | A lost chain is where people stop; history never resets |
| 2026-10-08 | Projection shown even when it says level 9 | Visible progress has to be true progress |
| 2026-10-09 | Purple for vocabulary and Guru; type-coloured glyph bands; pine-to-purple progress gradients | Owner asked for a livelier surface with purple in it; colour now carries item type and SRS group, as on WaniKani |
| 2026-10-09 | Ask bar names the half ("Kanji **Reading**"), reading bar on ink | Answering a meaning when a reading was asked is the commonest avoidable miss |
| 2026-10-09 | Two-step lessons with parts, on'yomi/kun'yomi focus, hints, sentence pairs | One thing to learn per screen; components at first sight (see Learning Principles) |
| 2026-10-09 | Mnemonic opens on a miss; audio only after the answer | Immediate corrective feedback; the prompt stays a real retrieval |
| 2026-10-09 | Pace averages a young ledger over its own age | Day one read "projected level 1, level 60 around 2098" at five lessons a day |
| 2026-10-19 | No payments: every level open after sign-in; Stripe, Pro and the paywall removed | A free service; the daily file budget stays as the anti-scrape limit |
