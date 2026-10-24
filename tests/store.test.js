// Store tests: v4 round trip, migrations, merge, sync state, quarantine, quota. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_SETTINGS, HANDOFF, KEY, QUARANTINE, SYNC_KEY, backup, fresh, load, loadSync, merge, migrateV1, migrateV2, migrateV3, parseImport,
  quarantined, save, saveSync,
} from "../app/store.js";

const NOW = 1_786_000_000_000;
function fakeStorage(init = {}, failSet = null) {
  const m = new Map(Object.entries(init));
  return {
    m,
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => {
      if (failSet) throw failSet;
      m.set(k, String(v));
    },
    removeItem: (k) => m.delete(k),
  };
}
const V2 = {
  version: 2,
  meta: { level: 3, streak: { count: 2, lastDay: "2026-10-07" } },
  cards: {
    "kanji/上:meaning": { stage: 5, due: 100, lapses: 1 },
    "kanji/上:reading": { stage: 6, due: 50, lapses: 0 },
    "radical/big:meaning": { stage: 9, due: null, lapses: 0 },
    "vocabulary/上手:meaning": { stage: 2, due: 70, lapses: 0 },
    "kanji/下:meaning": { stage: 4, due: 30, lapses: 0 },
    "kanji/下:reading": { stage: 9, due: null, lapses: 2 },
  },
};

describe("v2 to v4 (through v3)", () => {
  const s = migrateV2(V2, NOW);

  it("takes the lowest card stage, the earliest due, summed lapses", () => {
    assert.deepEqual(s.items["kanji/上"], { stage: 5, due: 50, lapses: 1, started: NOW, passed: NOW, burned: 0, at: NOW });
    assert.deepEqual(s.items["kanji/下"], { stage: 4, due: 30, lapses: 2, started: NOW, passed: 0, burned: 0, at: NOW });
  });

  it("keeps burned items burned with no due", () => {
    assert.deepEqual(s.items["radical/big"], { stage: 9, due: null, lapses: 0, started: NOW, passed: NOW, burned: NOW, at: NOW });
  });

  it("an orphaned half becomes one item at that stage", () => {
    assert.equal(s.items["vocabulary/上手"].stage, 2);
    assert.equal(s.items["vocabulary/上手"].due, 70);
  });

  it("carries level, seeds the streak, defaults settings", () => {
    assert.equal(s.level, 3);
    assert.equal(s.days["2026-10-07"].done, true);
    assert.equal(s.days["2026-10-06"].done, true);
    assert.equal(s.days["2026-10-05"], undefined);
    assert.deepEqual(s.settings, DEFAULT_SETTINGS);
    assert.equal(s.version, 4);
    assert.equal(s.settingsAt, 0);
    assert.equal(s.session, null);
  });
});

describe("v1 to v4", () => {
  it("maps SM-2 intervals through stages to one item", () => {
    const v1 = {
      version: 1,
      meta: { startLevel: 2, streak: { count: 0, lastDay: "" } },
      cards: { "kanji/上:meaning": { interval: 14, due: 9, lapses: 1 }, "kanji/上:reading": { interval: 6, due: 5, lapses: 0 } },
    };
    const s = migrateV1(v1, NOW);
    assert.deepEqual(s.items["kanji/上"], { stage: 4, due: 5, lapses: 1, started: NOW, passed: 0, burned: 0, at: NOW });
    assert.equal(s.level, 2);
  });
});

const V3 = {
  version: 3, level: 4,
  items: {
    "kanji/上": { stage: 3, due: 500, lapses: 1, started: 100, passed: 0, burned: 0 },
    "kanji/下": { stage: 6, due: 900, lapses: 0, started: 100, passed: 400, burned: 0 },
    "radical/big": { stage: 9, due: null, lapses: 0, started: 100, passed: 200, burned: 700 },
  },
  days: { "2026-10-07": { r: 3, l: 5, miss: 1, up: 2, done: true, freeze: false } },
  settings: { ...DEFAULT_SETTINGS, batch: 7 },
  session: null,
};

describe("v3 to v4", () => {
  const s = migrateV3(V3);

  it("stamps each item with its newest own timestamp and settings with 0", () => {
    assert.equal(s.version, 4);
    assert.deepEqual(Object.values(s.items).map((x) => x.at), [100, 400, 700]);
    assert.equal(s.settingsAt, 0);
    assert.equal(s.items["kanji/上"].stage, 3);
    assert.equal(s.level, 4);
    assert.equal(s.settings.batch, 7);
    assert.equal(s.days["2026-10-07"].up, 2);
  });

  it("parseImport routes a v3 payload through the migration and keeps v4 stamps", () => {
    assert.equal(parseImport(JSON.stringify(V3), NOW).items["radical/big"].at, 700);
    const v4 = { ...V3, version: 4, settingsAt: 55, items: { "kanji/上": { ...V3.items["kanji/上"], at: 123 } } };
    const p = parseImport(v4, NOW);
    assert.equal(p.items["kanji/上"].at, 123);
    assert.equal(p.settingsAt, 55);
  });

  it("migrates the v3 key, backs it up, writes v4", () => {
    const st = fakeStorage({ "jstudy.srs.v3": JSON.stringify(V3) });
    const g = load(st, NOW);
    assert.equal(g.status, "migrated-v3");
    assert.equal(g.store.items["kanji/下"].at, 400);
    assert.equal(st.m.get("jstudy.srs.v3.backup"), JSON.stringify(V3));
    assert.equal(st.m.has("jstudy.srs.v3"), false);
    assert.equal(JSON.parse(st.m.get(KEY)).version, 4);
  });
});

function v4(items, extra = {}) {
  const s = { ...fresh(), ...extra };
  for (const [rid, [stage, at, lapses = 0]] of Object.entries(items)) {
    s.items[rid] = { stage, due: at + 10, lapses, started: at, passed: 0, burned: 0, at };
  }
  return s;
}
const TODAY = "2026-10-09";

describe("merge", () => {
  const a = v4({ x: [2, 10], y: [3, 50], z: [5, 20] }, { level: 3, settingsAt: 5, settings: { ...DEFAULT_SETTINGS, batch: 4 } });
  a.days["2026-10-07"] = { r: 3, l: 1, miss: 1, up: 0, done: true, freeze: false };
  a.days["2026-10-08"] = { r: 0, l: 0, miss: 0, up: 0, done: false, freeze: true };
  const b = v4({ x: [4, 30], y: [1, 40, 2], w: [1, 60] }, { level: 2, settingsAt: 9, settings: { ...DEFAULT_SETTINGS, batch: 8 } });
  b.days["2026-10-07"] = { r: 1, l: 5, miss: 0, up: 2, done: false, freeze: false };
  b.days["2026-10-09"] = { r: 2, l: 0, miss: 0, up: 1, done: false, freeze: false };

  it("is idempotent", () => {
    assert.deepEqual(merge(a, a, TODAY), a);
  });

  it("is commutative on items, days and level", () => {
    const ab = merge(a, b, TODAY);
    const ba = merge(b, a, TODAY);
    assert.deepEqual(ab.items, ba.items);
    assert.deepEqual(ab.days, ba.days);
    assert.equal(ab.level, ba.level);
    assert.equal(ab.level, 3);
  });

  it("the newest at wins per item, the rest are unioned", () => {
    const m = merge(a, b, TODAY);
    assert.deepEqual(Object.keys(m.items).sort(), ["w", "x", "y", "z"]);
    assert.equal(m.items.x.stage, 4, "b's x is newer");
    assert.equal(m.items.y.stage, 3, "a's y is newer");
    assert.equal(m.items.z.stage, 5);
    assert.equal(m.items.w.stage, 1);
    assert.equal(m.version, 4);
  });

  it("breaks an at tie by the larger stage, then the larger lapses", () => {
    const p = v4({ x: [2, 10], y: [3, 10, 1] });
    const q = v4({ x: [5, 10], y: [3, 10, 4] });
    assert.equal(merge(p, q, TODAY).items.x.stage, 5);
    assert.equal(merge(q, p, TODAY).items.x.stage, 5);
    assert.equal(merge(p, q, TODAY).items.y.lapses, 4);
    assert.equal(merge(q, p, TODAY).items.y.lapses, 4);
  });

  it("takes field-wise max and OR for days", () => {
    const m = merge(a, b, TODAY);
    assert.deepEqual(m.days["2026-10-07"], { r: 3, l: 5, miss: 1, up: 2, done: true, freeze: false });
    assert.deepEqual(m.days["2026-10-08"], { r: 0, l: 0, miss: 0, up: 0, done: false, freeze: true });
    assert.deepEqual(m.days["2026-10-09"], { r: 2, l: 0, miss: 0, up: 1, done: false, freeze: false });
  });

  it("takes settings from the side with the larger settingsAt", () => {
    assert.equal(merge(a, b, TODAY).settings.batch, 8);
    assert.equal(merge(b, a, TODAY).settings.batch, 8);
    assert.equal(merge(a, b, TODAY).settingsAt, 9);
  });

  it("keeps the local session only when it started today", () => {
    const today = { ...a, session: { startedAt: new Date(2026, 9, 9, 8).getTime(), prompts: [], pos: 0, progress: {}, completed: 0 } };
    const stale = { ...a, session: { ...today.session, startedAt: new Date(2026, 9, 8, 8).getTime() } };
    assert.equal(merge(today, b, TODAY).session, today.session);
    assert.equal(merge(stale, b, TODAY).session, null);
    assert.equal(merge(b, today, TODAY).session, null, "the remote session never comes across");
  });

  it("leaves its inputs alone", () => {
    const before = JSON.stringify([a, b]);
    const m = merge(a, b, TODAY);
    m.items.x.stage = 9;
    m.days["2026-10-07"].r = 99;
    assert.equal(JSON.stringify([a, b]), before);
  });
});

describe("sync state", () => {
  it("defaults when nothing is stored or storage is blocked", () => {
    assert.deepEqual(loadSync(fakeStorage()), { rev: 0, dirty: false, lastPullAt: 0, user: null });
    assert.deepEqual(loadSync(null), { rev: 0, dirty: false, lastPullAt: 0, user: null });
    assert.deepEqual(loadSync(fakeStorage({ [SYNC_KEY]: "{bad" })), { rev: 0, dirty: false, lastPullAt: 0, user: null });
  });

  it("round-trips and coerces fields", () => {
    const st = fakeStorage();
    saveSync(st, { rev: 12, dirty: true, lastPullAt: NOW, user: 7 });
    assert.deepEqual(loadSync(st), { rev: 12, dirty: true, lastPullAt: NOW, user: 7 });
    saveSync(st, { rev: "x", dirty: 1, user: {} });
    assert.deepEqual(loadSync(st), { rev: 0, dirty: true, lastPullAt: 0, user: null });
    saveSync(null, { rev: 1 }); // blocked storage is not an error
  });

  it("backs a store up under its own key and tolerates blocked storage", () => {
    const st = fakeStorage();
    const s = { ...fresh(), level: 4 };
    backup(st, s);
    assert.deepEqual(JSON.parse(st.getItem(HANDOFF)), s);
    assert.equal(st.getItem(KEY), null, "the live store is left alone");
    backup(fakeStorage({}, new Error("quota")), s);
  });
});

describe("load and save", () => {
  it("fresh when nothing is stored", () => {
    const g = load(fakeStorage(), NOW);
    assert.equal(g.status, "fresh");
    assert.deepEqual(g.store, fresh());
  });

  it("migrates a v2 key, backs it up, writes v4", () => {
    const st = fakeStorage({ "jstudy.srs.v2": JSON.stringify(V2) });
    const g = load(st, NOW);
    assert.equal(g.status, "migrated-v2");
    assert.equal(g.store.items["kanji/上"].stage, 5);
    assert.equal(st.m.get("jstudy.srs.v2.backup"), JSON.stringify(V2));
    assert.equal(st.m.has("jstudy.srs.v2"), false);
    assert.equal(JSON.parse(st.m.get(KEY)).version, 4);
  });

  it("quarantines a corrupt v4 payload", () => {
    const st = fakeStorage({ [KEY]: "{not json" });
    const g = load(st, NOW);
    assert.equal(g.status, "corrupt");
    assert.equal(st.m.get(QUARANTINE), "{not json");
    assert.equal(quarantined(st), "{not json");
    assert.equal(st.m.has(KEY), false);
    assert.equal(quarantined(null), "");
  });

  it("still returns the migrated store when the backup write fails", () => {
    const full = new Error("full");
    full.name = "QuotaExceededError";
    const st = fakeStorage({ "jstudy.srs.v2": JSON.stringify(V2) }, full);
    const g = load(st, NOW);
    assert.equal(g.status, "migrated-v2");
    assert.equal(g.store.items["kanji/上"].stage, 5);
    assert.equal(st.m.has("jstudy.srs.v2"), true, "old key kept until a save succeeds");
  });

  it("clamps imported settings to the ranges the UI allows", () => {
    const s = parseImport({ version: 3, items: {}, settings: { batch: 0, reviewsPerDay: -5, lessonsPerDay: 1000, apprenticeCap: 2.7, examDate: "soon" } }, NOW);
    assert.deepEqual([s.settings.batch, s.settings.reviewsPerDay, s.settings.lessonsPerDay, s.settings.apprenticeCap], [3, 0, 100, 2]);
    assert.equal(s.settings.examDate, DEFAULT_SETTINGS.examDate);
  });

  it("round-trips a v4 store and drops malformed items", () => {
    const s = fresh();
    s.items["kanji/上"] = { stage: 3, due: 5, lapses: 0, started: 1, passed: 0, burned: 0, at: 1 };
    s.items.bad = { stage: "x" };
    s.level = 7;
    s.days["2026-10-07"] = { r: 3, l: 0, miss: 1, up: 2, done: true, freeze: false };
    const st = fakeStorage();
    assert.equal(save(st, s), null);
    const g = load(st, NOW);
    assert.equal(g.status, "ok");
    assert.deepEqual(Object.keys(g.store.items), ["kanji/上"]);
    assert.equal(g.store.level, 7);
    assert.equal(g.store.days["2026-10-07"].up, 2);
  });

  it("reports quota and blocked storage", () => {
    const quota = new Error("full");
    quota.name = "QuotaExceededError";
    assert.equal(save(fakeStorage({}, quota), fresh()), "quota");
    assert.equal(save(null, fresh()), "denied");
    assert.equal(load(null, NOW).status, "readonly");
  });

  it("rejects junk imports", () => {
    assert.throws(() => parseImport("[1,2]", NOW));
    assert.throws(() => parseImport('{"version":5,"items":{}}', NOW));
    assert.throws(() => parseImport("nope", NOW));
  });
});
