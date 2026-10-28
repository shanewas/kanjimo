// WaniKani rules over item state. Pure: no DOM, no storage, no Date.now().
// Callers pass nowMs and, where order is random, an rng.
// Item state: { stage, due, lapses, started, passed, burned }; timestamps in
// ms, 0 when the event has not happened, due null once burned.
import { DAY_MS, dueAfter, stageGroup } from "./scheduler.js";

const TYPE_ORDER = { radical: 0, kanji: 1, vocabulary: 2 };

export function startItem(level, nowMs) {
  return { stage: 1, due: dueAfter(1, level, nowMs), lapses: 0, started: nowMs, passed: 0, burned: 0 };
}

// One stage move per completed item: up one when every half was right, else
// down ceil(incorrect / 2), doubled at Guru and above, floored at 1.
export function completeItem(prev, incorrect, nowMs, level) {
  const from = prev.stage;
  const to = incorrect > 0
    ? Math.max(1, from - Math.ceil(incorrect / 2) * (from >= 5 ? 2 : 1))
    : Math.min(9, from + 1);
  const state = { ...prev, stage: to, due: dueAfter(to, level, nowMs), lapses: prev.lapses + (incorrect > 0 ? 1 : 0) };
  if (to >= 5 && !state.passed) state.passed = nowMs;
  if (to >= 9 && !state.burned) state.burned = nowMs;
  return { state, from, to };
}

export function resurrect(prev, nowMs) {
  return { ...prev, stage: 1, due: nowMs };
}

// An item stamped after the session started was written elsewhere (another
// device's sync); grading it again would move it a second stage.
export function gradedElsewhere(st, startedAtMs) {
  return !!st && !!st.at && st.at > startedAtMs;
}

// Lessons open at or below the current level once every prerequisite has
// passed Guru at some point; a later drop never re-locks.
export function isAvailable(ref, items, level) {
  if (items[ref.id] || ref.level > level) return false;
  return ref.requires.every((d) => items[d] && items[d].passed > 0);
}

export function lessonQueue(index, items, level) {
  return index.filter((r) => isAvailable(r, items, level))
    .sort((a, b) => a.level - b.level || TYPE_ORDER[a.type] - TYPE_ORDER[b.type]);
}

export function dueItems(items, nowMs) {
  return Object.keys(items).filter((id) => items[id].stage < 9 && items[id].due <= nowMs);
}

function shuffle(arr, rng) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// Which due items a session shows. Sorts are stable, so a shuffle before a
// grouped sort leaves each group shuffled inside.
export function pickReviews(rids, items, indexById, n, order, rng = Math.random) {
  const out = rids.slice();
  if (order === "lowStage") out.sort((a, b) => items[a].stage - items[b].stage || items[a].due - items[b].due);
  else {
    shuffle(out, rng);
    if (order === "apprenticeFirst") out.sort((a, b) => (items[a].stage > 4) - (items[b].stage > 4));
    else if (order === "lowLevel") out.sort((a, b) => indexById.get(a).level - indexById.get(b).level);
  }
  return out.slice(0, Math.max(0, n));
}

// "Keep going" past the quota serves another quota-sized batch of reviews
// (see buildEntries in app.js), so with reviewsPerDay 0 it can only serve
// lessons. Offering it for reviews alone would bounce straight back, unsent.
export function canKeepGoing(reviewsLeft, lessonsReady, reviewsPerDay) {
  return lessonsReady > 0 || (reviewsPerDay > 0 && reviewsLeft > 0);
}

// The day's done flag settles the streak, but it refuses autostart only
// when no work is owed: reviews that fell due after an idle morning (or
// lessons that opened since) still open straight into a session.
export function doneBlocksAutostart(todayDone, reviewsDue, lessonsReady) {
  return !!todayDone && reviewsDue <= 0 && lessonsReady <= 0;
}

export function kanjiProgress(index, items, level, type = "kanji") {
  let total = 0, passed = 0;
  for (const r of index) {
    if (r.level !== level || r.type !== type) continue;
    total += 1;
    if (items[r.id] && items[r.id].passed > 0) passed += 1;
  }
  return { total, passed };
}

// 90% of a level's kanji passed opens the next level; cascades, max 60.
export function levelUp(index, items, level) {
  while (level < 60) {
    const { total, passed } = kanjiProgress(index, items, level);
    if (!total || passed * 10 < total * 9) break;
    level += 1;
  }
  return level;
}

// Reviews coming due: now, within the next 24 hours, within the next 7 days
// (each window includes the ones before it).
export function forecast(items, nowMs) {
  const f = { now: 0, day: 0, week: 0 };
  for (const s of Object.values(items)) {
    if (s.stage >= 9) continue;
    if (s.due <= nowMs) f.now += 1;
    if (s.due <= nowMs + DAY_MS) f.day += 1;
    if (s.due <= nowMs + 7 * DAY_MS) f.week += 1;
  }
  return f;
}

export function stageCounts(items) {
  const c = { apprentice: 0, guru: 0, master: 0, enlightened: 0, burned: 0 };
  for (const s of Object.values(items)) c[stageGroup(s.stage)] += 1;
  return c;
}

// Session: a flat prompt list over entries [{ rid, parts, lesson }]. Plain
// data, so it serialises into the store and resumes after a reload.
export function makeSession(entries, backToBack, nowMs, rng = Math.random) {
  const reviews = [];
  const lessons = [];
  const progress = {};
  for (const e of entries) {
    for (const part of e.parts) (e.lesson ? lessons : reviews).push({ rid: e.rid, part, lesson: !!e.lesson });
    progress[e.rid] = { need: e.parts.length, done: 0, missM: 0, missR: 0 };
  }
  // Reviews shuffle as a block; the lesson quiz always follows them.
  if (!backToBack) shuffle(reviews, rng);
  return { startedAt: nowMs, prompts: reviews.concat(lessons), pos: 0, progress, completed: 0 };
}

// A learner who starts above level 1 already knows the levels below: they
// enter at Guru 1, due in a week, so they unlock dependants and get reviewed.
export function seedLevels(index, items, level, nowMs) {
  let n = 0;
  for (const r of index) {
    if (r.level >= level || items[r.id]) continue;
    items[r.id] = { stage: 5, due: dueAfter(5, r.level, nowMs), lapses: 0, started: nowMs, passed: nowMs, burned: 0 };
    n += 1;
  }
  return n;
}

export function currentPrompt(s) {
  return s.prompts[s.pos] || null;
}

// A wrong half counts a miss (reviews only) and comes back after at most
// three other prompts; a right half advances, and an item's last half
// completes it. Returns { type: half | reask | complete | lesson, ... }.
export function answer(s, correct) {
  const p = s.prompts[s.pos];
  const pr = s.progress[p.rid];
  if (!correct) {
    if (!p.lesson) pr[p.part === "meaning" ? "missM" : "missR"] += 1;
    s.prompts.splice(s.pos, 1);
    const after = Math.min(3, s.prompts.length - s.pos);
    s.prompts.splice(s.pos + after, 0, p);
    return { type: "reask", after };
  }
  pr.done += 1;
  s.pos += 1;
  const end = s.pos >= s.prompts.length;
  if (pr.done < pr.need) return { type: "half", end };
  if (p.lesson) return { type: "lesson", rid: p.rid, end };
  s.completed += 1;
  return { type: "complete", rid: p.rid, incorrect: pr.missM + pr.missR, chunk: s.completed % 10 === 0, end };
}
