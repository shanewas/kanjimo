// WaniKani stage table. Dependency-free ES module shared by the browser app
// and node --test. No DOM, no storage.
// Stages: 0 lesson, 1-4 Apprentice, 5-6 Guru, 7 Master, 8 Enlightened,
// 9 Burned. Fixed waits per stage; levels 1-2 use accelerated apprentice
// waits. Reviews open at the start of the hour, as on WaniKani.

export const HOUR_MS = 60 * 60 * 1000;
export const DAY_MS = 24 * HOUR_MS;

const WAIT = {
  1: 4 * HOUR_MS,
  2: 8 * HOUR_MS,
  3: 1 * DAY_MS,
  4: 2 * DAY_MS,
  5: 7 * DAY_MS,
  6: 14 * DAY_MS,
  7: 30 * DAY_MS,
  8: 120 * DAY_MS,
};
const WAIT_FAST = { 1: 2 * HOUR_MS, 2: 4 * HOUR_MS, 3: 8 * HOUR_MS, 4: 1 * DAY_MS };

export function stageName(stage) {
  if (stage <= 0) return "Lesson";
  if (stage <= 4) return `Apprentice ${stage}`;
  if (stage <= 6) return `Guru ${stage - 4}`;
  if (stage === 7) return "Master";
  if (stage === 8) return "Enlightened";
  return "Burned";
}

export function stageGroup(stage) {
  if (stage <= 0) return "lesson";
  if (stage <= 4) return "apprentice";
  if (stage <= 6) return "guru";
  if (stage === 7) return "master";
  if (stage === 8) return "enlightened";
  return "burned";
}

// Wait after reaching `stage` before the next review. Null at Burned (never).
export function waitFor(stage, level) {
  if (stage >= 9) return null;
  if (stage < 1) return 0;
  if ((level || 99) <= 2 && stage <= 4) return WAIT_FAST[stage];
  return WAIT[stage];
}

export function fmtWait(ms) {
  if (ms == null) return "never";
  const h = Math.round(ms / HOUR_MS);
  if (h < 24) return `${h}h`;
  const d = Math.round(ms / DAY_MS);
  if (d < 30) return `${d}d`;
  return `${Math.round(d / 30)}mo`;
}

export function floorHour(ms) {
  return Math.floor(ms / HOUR_MS) * HOUR_MS;
}

// Due time after reaching `stage`: null at Burned, else floored to the hour.
export function dueAfter(stage, level, nowMs) {
  const wait = waitFor(stage, level);
  return wait == null ? null : floorHour(nowMs + wait);
}

// migrateSm2(sm) -> stage state for v1 (SM-2) backups only. Maps the old
// interval to the nearest stage; nothing auto-burns; due preserved.
export function migrateSm2(sm) {
  const iv = (sm && sm.interval) || 0;
  let stage = 1;
  if (iv >= 90) stage = 8;
  else if (iv >= 30) stage = 7;
  else if (iv >= 14) stage = 6;
  else if (iv >= 7) stage = 5;
  else if (iv >= 2) stage = 4;
  else if (iv >= 1) stage = 3;
  return {
    stage,
    due: sm && typeof sm.due === "number" ? sm.due : 0,
    lapses: (sm && sm.lapses) || 0,
  };
}
