// Stage table tests. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  DAY_MS, HOUR_MS, dueAfter, floorHour, fmtWait, migrateSm2, stageGroup, stageName, waitFor,
} from "../app/scheduler.js";

const NOW = 1_786_000_000_000 + 17 * 60 * 1000;
const HOUR = Math.floor(NOW / HOUR_MS) * HOUR_MS;
const LV = 12;

describe("stages", () => {
  it("names all nine stages plus lesson", () => {
    assert.equal(stageName(0), "Lesson");
    assert.equal(stageName(1), "Apprentice 1");
    assert.equal(stageName(4), "Apprentice 4");
    assert.equal(stageName(5), "Guru 1");
    assert.equal(stageName(6), "Guru 2");
    assert.equal(stageName(7), "Master");
    assert.equal(stageName(8), "Enlightened");
    assert.equal(stageName(9), "Burned");
  });

  it("groups stages for progress display", () => {
    assert.equal(stageGroup(0), "lesson");
    assert.equal(stageGroup(3), "apprentice");
    assert.equal(stageGroup(5), "guru");
    assert.equal(stageGroup(7), "master");
    assert.equal(stageGroup(8), "enlightened");
    assert.equal(stageGroup(9), "burned");
  });

  it("uses WK fixed waits, null at Burned", () => {
    assert.equal(waitFor(1, LV), 4 * HOUR_MS);
    assert.equal(waitFor(4, LV), 2 * DAY_MS);
    assert.equal(waitFor(5, LV), 7 * DAY_MS);
    assert.equal(waitFor(8, LV), 120 * DAY_MS);
    assert.equal(waitFor(9, LV), null);
  });

  it("accelerates apprentice waits on levels 1-2", () => {
    assert.equal(waitFor(1, 1), 2 * HOUR_MS);
    assert.equal(waitFor(3, 2), 8 * HOUR_MS);
    assert.equal(waitFor(4, 2), 1 * DAY_MS);
    assert.equal(waitFor(5, 1), 7 * DAY_MS);
  });

  it("formats waits for button labels", () => {
    assert.equal(fmtWait(4 * HOUR_MS), "4h");
    assert.equal(fmtWait(2 * DAY_MS), "2d");
    assert.equal(fmtWait(30 * DAY_MS), "1mo");
    assert.equal(fmtWait(null), "never");
  });
});

describe("hour rounding", () => {
  it("floors to the start of the hour", () => {
    assert.equal(floorHour(NOW), HOUR);
    assert.equal(floorHour(HOUR), HOUR);
    assert.equal(floorHour(HOUR + HOUR_MS - 1), HOUR);
  });

  it("due = floor(now + wait); accelerated on level 1; null at Burned", () => {
    assert.equal(dueAfter(1, LV, NOW), HOUR + 4 * HOUR_MS);
    assert.equal(dueAfter(1, 1, NOW), HOUR + 2 * HOUR_MS);
    assert.equal(dueAfter(4, LV, NOW), HOUR + 2 * DAY_MS);
    assert.equal(dueAfter(9, LV, NOW), null);
  });
});

describe("migrateSm2", () => {
  it("maps intervals to nearest stages without auto-burning", () => {
    assert.equal(migrateSm2({ interval: 0, due: 5, lapses: 0 }).stage, 1);
    assert.equal(migrateSm2({ interval: 1, due: 5, lapses: 0 }).stage, 3);
    assert.equal(migrateSm2({ interval: 6, due: 5, lapses: 0 }).stage, 4);
    assert.equal(migrateSm2({ interval: 13, due: 5, lapses: 0 }).stage, 5);
    assert.equal(migrateSm2({ interval: 29, due: 5, lapses: 0 }).stage, 6);
    assert.equal(migrateSm2({ interval: 60, due: 5, lapses: 0 }).stage, 7);
    assert.equal(migrateSm2({ interval: 400, due: 5, lapses: 2 }).stage, 8);
  });

  it("preserves due timestamps and lapse counts", () => {
    const m = migrateSm2({ interval: 6, due: 123, lapses: 2 });
    assert.equal(m.due, 123);
    assert.equal(m.lapses, 2);
  });
});
