// Engine tests: item lifecycle, availability, picking, session. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { DAY_MS, HOUR_MS } from "../app/scheduler.js";
import {
  answer, completeItem, currentPrompt, dueItems, forecast, isAvailable, kanjiProgress, lessonQueue,
  levelUp, makeSession, pickReviews, resurrect, seedLevels, stageCounts, startItem,
} from "../app/engine.js";

const NOW = 1_786_000_000_000 + 17 * 60 * 1000;
const HOUR = Math.floor(NOW / HOUR_MS) * HOUR_MS;
const LV = 12;
const item = (stage, extra = {}) => ({ stage, due: 0, lapses: 0, started: 1, passed: 0, burned: 0, ...extra });

describe("item lifecycle", () => {
  it("lesson start: Apprentice 1, due on the hour after 4h (2h on level 1)", () => {
    assert.equal(startItem(LV, NOW).stage, 1);
    assert.equal(startItem(LV, NOW).due, HOUR + 4 * HOUR_MS);
    assert.equal(startItem(1, NOW).due, HOUR + 2 * HOUR_MS);
  });

  it("no misses: up one stage with that stage's wait", () => {
    const { state, from, to } = completeItem(item(3), 0, NOW, LV);
    assert.equal(from, 3);
    assert.equal(to, 4);
    assert.equal(state.due, HOUR + 2 * DAY_MS);
    assert.equal(state.lapses, 0);
  });

  it("misses: ceil(n/2) down, doubled at Guru and above, floored at 1", () => {
    const drop = (stage, n) => completeItem(item(stage), n, NOW, LV).to;
    assert.equal(drop(4, 1), 3);
    assert.equal(drop(4, 2), 3);
    assert.equal(drop(4, 3), 2);
    assert.equal(drop(5, 1), 3);
    assert.equal(drop(6, 3), 2);
    assert.equal(drop(8, 5), 2);
    assert.equal(drop(2, 5), 1);
    assert.equal(drop(1, 1), 1);
    const s = completeItem(item(4), 1, NOW, LV).state;
    assert.equal(s.lapses, 1);
    assert.equal(s.due, HOUR + DAY_MS);
  });

  it("stamps passed once at Guru and burned at 9 with no due", () => {
    const g = completeItem(item(4), 0, NOW, LV).state;
    assert.equal(g.passed, NOW);
    assert.equal(completeItem({ ...g, stage: 3 }, 0, NOW + 5, LV).state.passed, NOW);
    const b = completeItem(item(8, { passed: 7 }), 0, NOW, LV).state;
    assert.equal(b.stage, 9);
    assert.equal(b.due, null);
    assert.equal(b.burned, NOW);
    assert.equal(b.passed, 7);
  });

  it("resurrect puts a burned item at Apprentice 1, due now, history kept", () => {
    const r = resurrect(item(9, { due: null, burned: 5, passed: 4, lapses: 2 }), NOW);
    assert.deepEqual(r, { stage: 1, due: NOW, lapses: 2, started: 1, passed: 4, burned: 5 });
  });

  it("never mutates the previous state", () => {
    const prev = item(3);
    completeItem(prev, 1, NOW, LV);
    assert.deepEqual(prev, item(3));
  });
});

const ref = (id, level, type, requires = []) => ({ id, level, type, requires });
const INDEX = [
  ref("radical/a", 1, "radical"), ref("radical/b", 1, "radical"),
  ref("kanji/x", 1, "kanji", ["radical/a", "radical/b"]), ref("kanji/y", 1, "kanji", ["radical/a"]),
  ref("vocabulary/xy", 1, "vocabulary", ["kanji/x", "kanji/y"]), ref("vocabulary/kana", 1, "vocabulary"),
  ref("radical/c", 2, "radical"),
];
const byId = new Map(INDEX.map((r) => [r.id, r]));

describe("availability and level-up", () => {
  it("kanji opens once every radical has passed; a later drop keeps it open", () => {
    const items = { "radical/a": item(5, { passed: 1 }) };
    assert.equal(isAvailable(byId.get("kanji/x"), items, 1), false);
    assert.equal(isAvailable(byId.get("kanji/y"), items, 1), true);
    items["radical/b"] = item(2, { passed: 1 });
    assert.equal(isAvailable(byId.get("kanji/x"), items, 1), true);
  });

  it("level caps lessons; started items close; prerequisite-free vocab opens", () => {
    assert.equal(isAvailable(byId.get("radical/c"), {}, 1), false);
    assert.equal(isAvailable(byId.get("radical/c"), {}, 2), true);
    assert.equal(isAvailable(byId.get("radical/a"), { "radical/a": item(1) }, 1), false);
    assert.equal(isAvailable(byId.get("vocabulary/kana"), {}, 1), true);
  });

  it("lesson queue: level, then radical < kanji < vocabulary, then index order", () => {
    const passed = () => item(5, { passed: 1 });
    const items = { "radical/a": passed(), "radical/b": passed(), "kanji/x": passed(), "kanji/y": passed() };
    assert.deepEqual(lessonQueue(INDEX, items, 2).map((r) => r.id), ["vocabulary/xy", "vocabulary/kana", "radical/c"]);
  });

  it("levels up at 17 of 18 kanji passed, not 16; cascades; stops at 60", () => {
    const idx = [];
    for (let i = 0; i < 18; i++) idx.push(ref(`kanji/${i}`, 1, "kanji"));
    idx.push(ref("kanji/l2", 2, "kanji"));
    const items = {};
    for (let i = 0; i < 16; i++) items[`kanji/${i}`] = item(5, { passed: 1 });
    assert.equal(levelUp(idx, items, 1), 1);
    items["kanji/16"] = item(5, { passed: 1 });
    assert.equal(levelUp(idx, items, 1), 2);
    assert.deepEqual(kanjiProgress(idx, items, 1), { total: 18, passed: 17 });
    assert.deepEqual(kanjiProgress(idx, items, 1, "radical"), { total: 0, passed: 0 });
    items["kanji/l2"] = item(6, { passed: 1 });
    assert.equal(levelUp(idx, items, 1), 3);
    assert.equal(levelUp([ref("kanji/z", 60, "kanji")], { "kanji/z": item(5, { passed: 1 }) }, 60), 60);
  });
});

describe("due and picking", () => {
  const items = {
    a: item(3, { due: NOW - 1 }), b: item(1, { due: NOW }), c: item(5, { due: NOW + 1 }),
    d: item(9, { due: null }), e: item(6, { due: NOW - 5 }),
  };

  it("due = stage 1-8 with due at or before now", () => {
    assert.deepEqual(dueItems(items, NOW).sort(), ["a", "b", "e"]);
  });

  it("lowStage sorts by stage then due and caps at n", () => {
    assert.deepEqual(pickReviews(["a", "b", "e"], items, byId, 5, "lowStage"), ["b", "a", "e"]);
    assert.deepEqual(pickReviews(["a", "b", "e"], items, byId, 2, "lowStage"), ["b", "a"]);
    assert.deepEqual(pickReviews(["a"], items, byId, 0, "lowStage"), []);
  });

  it("apprenticeFirst keeps apprentice ahead; shuffled permutes with the rng", () => {
    assert.equal(pickReviews(["e", "a", "b"], items, byId, 3, "apprenticeFirst", () => 0.99)[2], "e");
    assert.deepEqual(pickReviews(["a", "b", "e"], items, byId, 3, "shuffled", () => 0).sort(), ["a", "b", "e"]);
  });

  it("lowLevel orders by index level", () => {
    const its = { "radical/c": item(1, { due: 0 }), "radical/a": item(1, { due: 0 }) };
    assert.deepEqual(pickReviews(["radical/c", "radical/a"], its, byId, 2, "lowLevel", () => 0), ["radical/a", "radical/c"]);
  });

  it("counts stages by group", () => {
    assert.deepEqual(stageCounts(items), { apprentice: 2, guru: 2, master: 0, enlightened: 0, burned: 1 });
  });
});

describe("session", () => {
  const entries = () => [
    { rid: "radical/a", parts: ["meaning"] },
    { rid: "kanji/x", parts: ["meaning", "reading"] },
    { rid: "vocabulary/xy", parts: ["meaning", "reading"], lesson: true },
  ];

  it("a radical completes after one half, a kanji after both, back to back", () => {
    const s = makeSession(entries(), true, NOW);
    assert.deepEqual(currentPrompt(s), { rid: "radical/a", part: "meaning", lesson: false });
    assert.equal(answer(s, true).type, "complete");
    assert.equal(answer(s, true).type, "half");
    const ev = answer(s, true);
    assert.equal(ev.type, "complete");
    assert.equal(ev.rid, "kanji/x");
    assert.equal(ev.incorrect, 0);
  });

  it("a miss re-asks after at most three prompts and counts once on completion", () => {
    const s = makeSession(entries(), true, NOW);
    answer(s, true);
    const miss = answer(s, false);
    assert.equal(miss.type, "reask");
    assert.equal(miss.after, 3);
    assert.deepEqual(s.prompts.slice(s.pos).map((p) => `${p.rid}:${p.part}`),
      ["kanji/x:reading", "vocabulary/xy:meaning", "vocabulary/xy:reading", "kanji/x:meaning"]);
    assert.equal(answer(s, true).type, "half");
    assert.equal(answer(s, true).type, "half");
    assert.equal(answer(s, true).type, "lesson");
    const ev = answer(s, true);
    assert.equal(ev.type, "complete");
    assert.equal(ev.incorrect, 1);
    assert.equal(ev.end, true);
    assert.equal(completeItem(item(4), ev.incorrect, NOW, LV).to, 3);
  });

  it("the last prompt re-asks immediately; lesson misses count nothing", () => {
    const s = makeSession([{ rid: "vocabulary/xy", parts: ["meaning", "reading"], lesson: true }], true, NOW);
    answer(s, true);
    assert.equal(answer(s, false).after, 0);
    assert.equal(s.progress["vocabulary/xy"].missR, 0);
    const ev = answer(s, true);
    assert.equal(ev.type, "lesson");
    assert.equal(ev.end, true);
  });

  it("chunk flag on every tenth completed review", () => {
    const s = makeSession(Array.from({ length: 11 }, (_, i) => ({ rid: `r${i}`, parts: ["meaning"] })), true, NOW);
    const flags = [];
    for (let i = 0; i < 11; i++) flags.push(!!answer(s, true).chunk);
    assert.deepEqual(flags, [false, false, false, false, false, false, false, false, false, true, false]);
  });

  it("shuffled mode mixes review halves across items; the lesson quiz still comes last", () => {
    const s = makeSession(entries(), false, NOW, () => 0);
    assert.equal(s.prompts.length, 5);
    assert.notDeepEqual(s.prompts.slice(0, 3), makeSession(entries(), true, NOW).prompts.slice(0, 3));
    assert.deepEqual(s.prompts.slice(3).map((p) => p.lesson), [true, true]);
  });

  it("a start level seeds everything below it at Guru 1, due in a week", () => {
    const items = { "radical/a": item(2) };
    assert.equal(seedLevels(INDEX, items, 2, NOW), 5);
    assert.equal(items["radical/a"].stage, 2, "existing state untouched");
    assert.deepEqual(items["kanji/x"], { stage: 5, due: HOUR + 7 * DAY_MS, lapses: 0, started: NOW, passed: NOW, burned: 0 });
    assert.equal(items["radical/c"], undefined, "level 2 itself is not seeded");
    assert.equal(seedLevels(INDEX, items, 1, NOW), 0);
  });
});

describe("forecast", () => {
  it("counts due now, within a day and within a week; burned items never", () => {
    const items = {
      a: item(1, { due: NOW - HOUR_MS }),
      b: item(2, { due: NOW + 3 * HOUR_MS }),
      c: item(5, { due: NOW + 2 * DAY_MS }),
      d: item(7, { due: NOW + 30 * DAY_MS }),
      e: item(9, { due: null }),
    };
    assert.deepEqual(forecast(items, NOW), { now: 1, day: 2, week: 3 });
    assert.deepEqual(forecast({}, NOW), { now: 0, day: 0, week: 0 });
  });
});
