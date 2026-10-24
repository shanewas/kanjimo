// Tests for app/content.js: path builders, mergeOwn, reading formats. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  cardsPath,
  formatKun,
  itemsPath,
  mergeOwn,
  ownPath,
  padLevel,
  readingGroups,
  taughtGroup,
} from "../app/content.js";

describe("path builders", () => {
  it("pads level numbers to two digits", () => {
    assert.equal(padLevel(1), "01");
    assert.equal(padLevel(9), "09");
    assert.equal(padLevel(10), "10");
    assert.equal(padLevel(60), "60");
  });

  it("builds paths for cards, items, and own", () => {
    assert.equal(cardsPath(1), "../data/cards/level-01.json");
    assert.equal(itemsPath(4), "../data/items/level-04.json");
    assert.equal(ownPath(60), "../data/own/level-60.json");
    assert.equal(cardsPath(5, "/custom"), "/custom/cards/level-05.json");
  });
});

describe("mergeOwn", () => {
  it("merges mnemonics and hints onto Map cardsById", () => {
    const cardsById = new Map([
      ["kanji/上:meaning", { id: "kanji/上:meaning", answers: ["Above"] }],
      ["kanji/上:reading", { id: "kanji/上:reading", answers: ["じょう"] }],
    ]);
    const own = {
      version: 2,
      level: 1,
      cards: {
        "kanji/上:meaning": {
          mnemonic_meaning: "Above meaning mnemonic.",
          hint: "Above hint.",
        },
        "kanji/上:reading": {
          mnemonic_reading: "Above reading mnemonic.",
          hint: "Reading hint.",
        },
      },
    };

    mergeOwn(cardsById, own);

    const mc = cardsById.get("kanji/上:meaning");
    assert.equal(mc.mnemonic_meaning, "Above meaning mnemonic.");
    assert.equal(mc.hint, "Above hint.");
    assert.equal(mc.mnemonic_reading, undefined);

    const rc = cardsById.get("kanji/上:reading");
    assert.equal(rc.mnemonic_reading, "Above reading mnemonic.");
    assert.equal(rc.hint, "Reading hint.");
  });

  it("handles null or missing own data silently", () => {
    const cardsById = new Map([["card:1", { id: "card:1" }]]);
    mergeOwn(cardsById, null);
    mergeOwn(cardsById, undefined);
    mergeOwn(cardsById, { cards: {} });
    assert.equal(cardsById.get("card:1").mnemonic_meaning, undefined);
  });

  it("supports array-shaped own.cards", () => {
    const cardsById = new Map([["card:1", { id: "card:1" }]]);
    mergeOwn(cardsById, {
      cards: [{ id: "card:1", mnemonic_meaning: "Array mnem", hint: "Array hint" }],
    });
    const c = cardsById.get("card:1");
    assert.equal(c.mnemonic_meaning, "Array mnem");
    assert.equal(c.hint, "Array hint");
  });
});

describe("reading formatting", () => {
  it("formats kun readings with okurigana dots", () => {
    assert.equal(formatKun("うえ"), "うえ");
    assert.equal(formatKun({ stem: "ひと", okurigana: "" }), "ひと");
    assert.equal(formatKun({ stem: "ひと", okurigana: "つ" }), "ひと.つ");
  });

  it("builds reading groups from item readings", () => {
    const rec = {
      readings: {
        on: ["いち", "いつ"],
        kun: [{ stem: "ひと", okurigana: "" }, { stem: "ひと", okurigana: "つ" }],
        nanori: ["かず"],
      },
      teach: { group: "on", reading: "いち" },
    };
    assert.deepEqual(readingGroups(rec), {
      "On'yomi": ["いち", "いつ"],
      "Kun'yomi": ["ひと", "ひと.つ"],
      "Nanori": ["かず"],
    });
    assert.equal(taughtGroup(rec), "On'yomi");
  });

  it("identifies Kun'yomi taught group", () => {
    const rec = {
      readings: { on: [], kun: [{ stem: "やま", okurigana: "" }] },
      teach: { group: "kun", reading: "やま" },
    };
    assert.equal(taughtGroup(rec), "Kun'yomi");
  });
});
