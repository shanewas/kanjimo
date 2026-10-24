// Ledger tests: rows, streak, freezes. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  dayKey, daysActive, daysBetween, level60Date, markDone, pace, projectLevel, recordLessons, recordReview,
  row, settle, shiftKey, streak,
} from "../app/ledger.js";

const SET = { reviewsPerDay: 50, lessonsPerDay: 5 };
const T = "2026-10-08";
const range = (from, n) => Array.from({ length: n }, (_, i) => shiftKey(from, i));
// Replays days in order the way the app does: settle on open, then study.
function simulate(from, n, missed) {
  const d = {};
  for (const k of range(from, n)) {
    settle(d, k);
    if (!missed.includes(k)) row(d, k).done = true;
  }
  return d;
}

describe("rows", () => {
  it("records reviews and lessons", () => {
    const d = {};
    recordReview(d, T, 0, true);
    recordReview(d, T, 2, false);
    recordLessons(d, T, 5);
    assert.deepEqual(d[T], { r: 2, l: 5, miss: 2, up: 1, done: false, freeze: false });
  });

  it("done when both quotas are met or exhausted, and stays done after more work", () => {
    const d = {};
    recordReview(d, T, 0, true);
    assert.equal(markDone(d, T, 10, 3, SET), false);
    assert.equal(markDone(d, T, 0, 0, SET), true);
    recordReview(d, T, 1, false);
    assert.equal(markDone(d, T, 10, 0, SET), true, "extra partial work never undoes the day");
    const e = {};
    row(e, T).r = 50;
    e[T].l = 5;
    assert.equal(markDone(e, T, 99, 99, SET), true);
  });

  it("day keys shift across month and year ends", () => {
    assert.equal(shiftKey("2026-10-01", -1), "2026-09-30");
    assert.equal(shiftKey("2026-12-31", 1), "2027-01-01");
    assert.equal(dayKey(new Date(2026, 0, 5)), "2026-01-05");
  });
});

describe("streak and freezes", () => {
  it("empty ledger: settle is a no-op and streak is 0", () => {
    const d = {};
    settle(d, T);
    assert.deepEqual(d, {});
    assert.equal(streak(d, T), 0);
  });

  it("today counts only when done", () => {
    const d = simulate("2026-10-05", 3, []);
    assert.equal(streak(d, T), 3);
    row(d, T).done = true;
    assert.equal(streak(d, T), 4);
  });

  it("one miss a week is frozen and bridges the chain without counting", () => {
    const d = simulate("2026-09-08", 30, ["2026-09-17", "2026-09-27"]);
    assert.equal(d["2026-09-17"].freeze, true);
    assert.equal(d["2026-09-27"].freeze, true);
    assert.equal(streak(d, "2026-10-08"), 28);
  });

  it("a second miss within seven days ends the chain; history stays", () => {
    const d = simulate("2026-09-08", 30, ["2026-09-17", "2026-09-20"]);
    assert.equal(d["2026-09-17"].freeze, true);
    assert.equal(d["2026-09-20"], undefined);
    assert.equal(streak(d, "2026-10-08"), 17);
    assert.equal(d["2026-09-10"].done, true);
  });

  it("two missed days in a row freeze the first and break on the second", () => {
    const d = simulate("2026-09-08", 30, ["2026-09-17", "2026-09-18"]);
    assert.equal(d["2026-09-17"].freeze, true);
    assert.equal(d["2026-09-18"], undefined);
    assert.equal(streak(d, "2026-10-08"), 19);
  });

  it("daysActive counts rows with any activity in the month", () => {
    const d = {};
    recordReview(d, "2026-10-01", 0, false);
    recordLessons(d, "2026-10-03", 1);
    row(d, "2026-10-05");
    row(d, "2026-09-30").r = 3;
    assert.equal(daysActive(d, "2026-10"), 2);
  });
});

describe("projection", () => {
  it("pace averages lessons over the last fourteen days including today", () => {
    const d = {};
    recordLessons(d, "2026-10-08", 5);
    recordLessons(d, "2026-10-01", 9);
    recordLessons(d, "2026-09-24", 100); // 15th day back: outside the window
    assert.equal(pace(d, "2026-10-08"), 1);
    assert.equal(pace({}, "2026-10-08"), 0);
  });

  it("averages a young ledger over its own days, skipped ones included", () => {
    const d = {};
    recordLessons(d, "2026-10-08", 5);
    assert.equal(pace(d, "2026-10-08"), 5);
    recordLessons(d, "2026-10-10", 5);
    assert.equal(pace(d, "2026-10-10"), 10 / 3);
  });

  it("counts days between keys across a year end", () => {
    assert.equal(daysBetween("2026-10-08", "2027-07-04"), 269);
    assert.equal(daysBetween("2026-10-08", "2026-10-08"), 0);
    assert.equal(daysBetween("2026-10-08", "2026-10-01"), -7);
  });

  it("projects the highest level whose cumulative count fits", () => {
    const cum = [0, 80, 227, 357, 548];
    assert.equal(projectLevel(cum, 0), 1);
    assert.equal(projectLevel(cum, 79), 1);
    assert.equal(projectLevel(cum, 80), 1);
    assert.equal(projectLevel(cum, 300), 2);
    assert.equal(projectLevel(cum, 9000), 4);
  });

  it("dates level 60 from pace, none without one", () => {
    assert.equal(level60Date("2026-10-08", 100, 5), "2026-10-28");
    assert.equal(level60Date("2026-10-08", 0, 5), "2026-10-08");
    assert.equal(level60Date("2026-10-08", 100, 0), null);
  });
});
