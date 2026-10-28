// Kana conversion and answer checking. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { toKana } from "../app/kana.js";
import { checkAnswer, foldKana, levenshtein, normalizeMeaning, tolerance } from "../app/answer.js";

describe("romaji to kana", () => {
  it("converts syllables, youon, sokuon, long vowels", () => {
    assert.equal(toKana("kyou"), "きょう");
    assert.equal(toKana("gakkou"), "がっこう");
    assert.equal(toKana("toukyou"), "とうきょう");
    assert.equal(toKana("matcha"), "まっちゃ");
    assert.equal(toKana("shi si chi ti tsu tu fu hu ji zi"), "し し ち ち つ つ ふ ふ じ じ");
    assert.equal(toKana("ra-men", true), "らーめん");
  });

  it("handles n before consonants, nn, n', and a trailing n", () => {
    assert.equal(toKana("shinbun", true), "しんぶん");
    assert.equal(toKana("onna"), "おんな");
    assert.equal(toKana("onnna"), "おんな");
    assert.equal(toKana("konnichiwa"), "こんにちわ");
    assert.equal(toKana("ten'in", true), "てんいん");
    assert.equal(toKana("tenn"), "てんn");
    assert.equal(toKana("tenn", true), "てん");
    assert.equal(toKana("ten"), "てn");
    assert.equal(toKana("ten", true), "てん");
    assert.equal(toKana("nya"), "にゃ");
  });

  // The field re-converts its own output on every keystroke, so each
  // intermediate state has to survive the next letter.
  const live = (word) => { let v = ""; for (const ch of word) v = toKana(v + ch); return v; };
  it("survives keystroke-by-keystroke conversion", () => {
    assert.equal(live("nya"), "にゃ");
    assert.equal(live("gyuunyuu"), "ぎゅうにゅう");
    assert.equal(live("onna"), "おんな");
    assert.equal(live("minna"), "みんな");
    assert.equal(live("konnichiwa"), "こんにちわ");
    assert.equal(toKana(live("sennen"), true), "せんねん");
    assert.equal(toKana(live("zannen"), true), "ざんねん");
    assert.equal(toKana(live("shinbun"), true), "しんぶん");
    assert.equal(live("matcha"), "まっちゃ");
    assert.equal(live("gakkou"), "がっこう");
    assert.equal(live("xtsu"), "っ");
    assert.equal(live("sh"), "sh");
    assert.equal(toKana(live("tenn"), true), "てん");
  });

  it("passes kana through and leaves unconvertible letters", () => {
    assert.equal(toKana("うえ"), "うえ");
    assert.equal(toKana("アメリカ"), "アメリカ");
    assert.equal(toKana("ky"), "ky");
    assert.equal(toKana("xtsu ltu xya"), "っ っ ゃ");
  });
});

describe("answer check", () => {
  const kanji = { answers: ["Above", "Up", "Over"] };
  const reading = { answers: ["じょう"] };
  const kata = { answers: ["アメリカ"] };
  const verb = { answers: ["To Eat"] };
  const long = { answers: ["Construction"] };

  it("readings: romaji converts, katakana folds, exact otherwise", () => {
    assert.deepEqual(checkAnswer(reading, "reading", "jou"), { ok: true });
    assert.deepEqual(checkAnswer(reading, "reading", "じょう"), { ok: true });
    assert.deepEqual(checkAnswer(kata, "reading", "amerika"), { ok: true });
    assert.deepEqual(checkAnswer(kata, "reading", "アメリカ"), { ok: true });
    assert.deepEqual(checkAnswer(reading, "reading", "jo"), { ok: false });
  });

  it("readings: full-width romaji and inner spaces still convert", () => {
    assert.deepEqual(checkAnswer({ answers: ["か"] }, "reading", "ｋａ"), { ok: true });
    assert.deepEqual(checkAnswer({ answers: ["きょう"] }, "reading", "ｋｙｏｕ"), { ok: true });
    assert.deepEqual(checkAnswer({ answers: ["きょう"] }, "reading", "ＫＹＯＵ"), { ok: true });
    assert.deepEqual(checkAnswer({ answers: ["かき"] }, "reading", "ka ki"), { ok: true });
    assert.deepEqual(checkAnswer({ answers: ["かき"] }, "reading", "ka　ki"), { ok: true });
    assert.deepEqual(checkAnswer({ answers: ["か"] }, "reading", "ｋｉ"), { ok: false });
    assert.deepEqual(checkAnswer(reading, "reading", "ｊｏ"), { ok: false });
  });

  it("readings: shakes on leftover latin, small-kana slips, empty input", () => {
    assert.ok(checkAnswer(reading, "reading", "jouk").shake);
    assert.ok(checkAnswer(reading, "reading", "じよう").shake);
    assert.ok(checkAnswer(reading, "reading", "  ").shake);
  });

  it("meanings: tolerance scales with the listed answer's length", () => {
    assert.deepEqual([tolerance(3), tolerance(5), tolerance(8), tolerance(9)], [0, 1, 2, 3]);
    assert.deepEqual(checkAnswer(kanji, "meaning", "abov"), { ok: true });
    assert.deepEqual(checkAnswer(kanji, "meaning", "UP"), { ok: true });
    assert.deepEqual(checkAnswer(kanji, "meaning", "ip"), { ok: false });
    assert.deepEqual(checkAnswer(long, "meaning", "constrction"), { ok: true });
    assert.deepEqual(checkAnswer(long, "meaning", "konstrukshun"), { ok: false });
  });

  it("meanings: shakes for kana input and a verb without 'to'", () => {
    assert.ok(checkAnswer(kanji, "meaning", "うえ").shake);
    assert.ok(checkAnswer(verb, "meaning", "eat").shake);
    assert.deepEqual(checkAnswer(verb, "meaning", "to eat"), { ok: true });
  });

  it("helpers", () => {
    assert.equal(levenshtein("kitten", "sitting"), 3);
    assert.equal(foldKana("アメリカ"), "あめりか");
    assert.equal(normalizeMeaning("  Don't  Know! "), "dont know");
  });
});
