// Persistence for the v4 store and migration from v1 (SM-2 cards), v2
// (staged cards) and v3 (one stage per item, no change stamps). Takes the
// storage object as a parameter so tests pass a fake. Imports and stored
// payloads are validated: bad items are dropped, unknown shapes rejected.
import { migrateSm2 } from "./scheduler.js";
import { dayKey, row, shiftKey } from "./ledger.js";

export const KEY = "jstudy.srs.v4";
export const QUARANTINE = "jstudy.srs.v4.quarantine";
export const SYNC_KEY = "jstudy.sync.v1";
export const HANDOFF = "jstudy.srs.v4.previous-account";
const LEGACY = [
  ["jstudy.srs.v3", "jstudy.srs.v3.backup", "migrated-v3"],
  ["jstudy.srs.v2", "jstudy.srs.v2.backup", "migrated-v2"],
  ["jstudy.srs.v1", "jstudy.srs.v1.backup", "migrated-v1"],
];
export const RANGES = { reviewsPerDay: [0, 500], lessonsPerDay: [0, 100], batch: [3, 10], apprenticeCap: [0, 1000] };
export const DEFAULT_SETTINGS = {
  batch: 5, lessonsPerDay: 5, reviewsPerDay: 50, apprenticeCap: 100,
  order: "lowStage", backToBack: true, autostart: true, examDate: "2027-07-04",
};

// Item `at` and `settingsAt` are ms stamps of the last change; merge() picks
// the newer side by them when two devices disagree.
export function fresh() {
  return { version: 4, level: 1, items: {}, days: {}, settings: { ...DEFAULT_SETTINGS }, settingsAt: 0, session: null };
}

const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : 0);
const clampLevel = (n) => (typeof n === "number" && n >= 1 && n <= 60 ? Math.floor(n) : 1);

function sanitizeV4(d) {
  const s = fresh();
  s.level = clampLevel(d.level);
  for (const [rid, st] of Object.entries(d.items)) {
    if (!st || typeof st.stage !== "number" || !Number.isFinite(st.stage)) continue;
    const stage = Math.floor(st.stage);
    if (stage < 1 || stage > 9) continue;
    s.items[rid] = {
      stage,
      due: stage >= 9 ? null : num(st.due),
      lapses: num(st.lapses), started: num(st.started), passed: num(st.passed), burned: num(st.burned),
      at: num(st.at),
    };
  }
  s.settingsAt = num(d.settingsAt);
  for (const [k, r] of Object.entries(d.days || {})) {
    if (r && /^\d{4}-\d{2}-\d{2}$/.test(k)) {
      s.days[k] = { r: num(r.r), l: num(r.l), miss: num(r.miss), up: num(r.up), done: !!r.done, freeze: !!r.freeze };
    }
  }
  if (d.settings && typeof d.settings === "object") Object.assign(s.settings, d.settings);
  for (const [k, [lo, hi]] of Object.entries(RANGES)) {
    const v = s.settings[k];
    s.settings[k] = typeof v === "number" && Number.isFinite(v) ? Math.max(lo, Math.min(hi, Math.floor(v))) : DEFAULT_SETTINGS[k];
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(s.settings.examDate))) s.settings.examDate = DEFAULT_SETTINGS.examDate;
  if (d.session && Array.isArray(d.session.prompts) && d.session.progress) s.session = d.session;
  return s;
}

// v3 had no change stamps: an item's newest own timestamp stands in.
export function migrateV3(v3) {
  const s = sanitizeV4(v3);
  for (const st of Object.values(s.items)) st.at = Math.max(st.started, st.passed, st.burned);
  s.settingsAt = 0;
  return s;
}

// v2 kept one state per card (record:meaning, record:reading). One item now:
// lowest stage, earliest due, summed lapses. Resolves the orphaned-half case
// where only one card ever got graded. Goes on through the v3 migration.
export function migrateV2(v2, nowMs) {
  const items = {};
  for (const [cid, st] of Object.entries(v2.cards || {})) {
    if (!st || typeof st.stage !== "number") continue;
    const rid = cid.split(":")[0];
    const cur = items[rid];
    if (!cur) items[rid] = { stage: st.stage, due: st.due, lapses: num(st.lapses) };
    else {
      cur.stage = Math.min(cur.stage, st.stage);
      cur.due = cur.due == null ? st.due : st.due == null ? cur.due : Math.min(cur.due, st.due);
      cur.lapses += num(st.lapses);
    }
  }
  for (const s of Object.values(items)) {
    s.stage = Math.min(9, Math.max(1, s.stage));
    s.due = s.stage >= 9 ? null : num(s.due);
    s.started = nowMs;
    s.passed = s.stage >= 5 ? nowMs : 0;
    s.burned = s.stage >= 9 ? nowMs : 0;
  }
  const out = { version: 3, level: clampLevel(v2.meta && v2.meta.level), items, days: {}, settings: { ...DEFAULT_SETTINGS }, session: null };
  const st = v2.meta && v2.meta.streak;
  if (st && st.count > 0 && typeof st.lastDay === "string" && /^\d{4}-\d{2}-\d{2}$/.test(st.lastDay)) {
    for (let i = 0; i < st.count; i++) row(out.days, shiftKey(st.lastDay, -i)).done = true;
  }
  return migrateV3(out);
}

export function migrateV1(v1, nowMs) {
  const cards = {};
  for (const [cid, st] of Object.entries(v1.cards || {})) if (st && typeof st === "object") cards[cid] = migrateSm2(st);
  return migrateV2({ version: 2, cards, meta: { level: v1.meta.startLevel, streak: v1.meta.streak } }, nowMs);
}

// Accepts a v1 to v4 payload (string or object); throws on anything else.
export function parseImport(raw, nowMs) {
  const d = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!d || typeof d !== "object") throw new Error("schema");
  if (d.version === 1 && d.cards && d.meta) return migrateV1(d, nowMs);
  if (d.version === 2 && d.cards && d.meta) return migrateV2(d, nowMs);
  if (d.version === 3 && d.items && typeof d.items === "object") return migrateV3(d);
  if (d.version === 4 && d.items && typeof d.items === "object") return sanitizeV4(d);
  throw new Error("schema");
}

// Two devices' copies of one store, folded into one. Pure, idempotent, and
// commutative on items, days, level and settings, so both sides converge
// whichever pushes first. `a` is the local side: only its session can
// survive, and only when it started today (`todayKey` passed in to keep
// this pure).
const ZERO_DAY = { r: 0, l: 0, miss: 0, up: 0, done: false, freeze: false };
function newer(x, y) {
  return x.at !== y.at ? x.at > y.at : x.stage !== y.stage ? x.stage > y.stage : x.lapses > y.lapses;
}
export function merge(a, b, todayKey) {
  const out = fresh();
  out.level = Math.max(a.level, b.level);
  for (const [rid, st] of Object.entries(a.items)) out.items[rid] = { ...st };
  for (const [rid, st] of Object.entries(b.items)) {
    const cur = out.items[rid];
    if (!cur || newer(st, cur)) out.items[rid] = { ...st };
  }
  for (const k of new Set([...Object.keys(a.days), ...Object.keys(b.days)])) {
    const x = a.days[k] || ZERO_DAY;
    const y = b.days[k] || ZERO_DAY;
    out.days[k] = {
      r: Math.max(x.r, y.r), l: Math.max(x.l, y.l), miss: Math.max(x.miss, y.miss), up: Math.max(x.up, y.up),
      done: x.done || y.done, freeze: x.freeze || y.freeze,
    };
  }
  // A settingsAt tie breaks on the serialized settings, so both devices
  // pick the same side whichever one is local.
  const s = a.settingsAt !== b.settingsAt
    ? (b.settingsAt > a.settingsAt ? b : a)
    : (JSON.stringify(b.settings) > JSON.stringify(a.settings) ? b : a);
  out.settings = { ...s.settings };
  out.settingsAt = s.settingsAt;
  out.session = a.session && dayKey(new Date(a.session.startedAt)) === todayKey ? a.session : null;
  return out;
}

// Sync bookkeeping, apart from the store so a push never rewrites progress:
// the server revision last seen, whether local changes await a push, and
// when the server copy was last pulled.
export function loadSync(storage) {
  try {
    const d = JSON.parse(storage.getItem(SYNC_KEY));
    const user = typeof d.user === "number" || typeof d.user === "string" ? d.user : null;
    return { rev: num(d.rev), dirty: !!d.dirty, lastPullAt: num(d.lastPullAt), user };
  } catch {
    return { rev: 0, dirty: false, lastPullAt: 0, user: null }; // nothing stored yet, or storage blocked
  }
}

// A store set aside when another account signs in on this browser; the
// newest one only, kept for recovery since it may hold unpushed changes.
export function backup(storage, store) {
  try {
    storage.setItem(HANDOFF, JSON.stringify(store));
  } catch { /* storage full or blocked: the previous account's copy is on the server */ }
}

export function saveSync(storage, state) {
  try {
    storage.setItem(SYNC_KEY, JSON.stringify(state));
  } catch { /* storage full or blocked: save() reports it, sync retries next time */ }
}

export function load(storage, nowMs) {
  let raw = null;
  try {
    raw = storage.getItem(KEY);
  } catch {
    return { store: fresh(), status: "readonly" };
  }
  if (raw) {
    try {
      return { store: parseImport(raw, nowMs), status: "ok" };
    } catch {
      try {
        storage.setItem(QUARANTINE, raw);
        storage.removeItem(KEY);
      } catch { /* storage unusable; memory-only from here */ }
      return { store: fresh(), status: "corrupt" };
    }
  }
  for (const [key, backup, status] of LEGACY) {
    const old = storage.getItem(key);
    if (!old) continue;
    let store;
    try {
      store = parseImport(old, nowMs);
    } catch {
      continue; // unreadable legacy payload stays where it is
    }
    try {
      storage.setItem(backup, old);
      storage.removeItem(key);
      storage.setItem(KEY, JSON.stringify(store));
    } catch { /* the migrated store is still returned; boot saves it again */ }
    return { store, status };
  }
  return { store: fresh(), status: "fresh" };
}

export function quarantined(storage) {
  try {
    return storage.getItem(QUARANTINE) || "";
  } catch {
    return "";
  }
}

export function save(storage, store) {
  try {
    storage.setItem(KEY, JSON.stringify(store));
    return null;
  } catch (e) {
    return (e && (e.name === "QuotaExceededError" || e.code === 22)) ? "quota" : "denied";
  }
}
