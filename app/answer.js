// Answer checking. Readings: romaji converts, katakana folds, then exact.
// Meanings: edit distance with a tolerance that grows with the answer's
// length (WaniKani doesn't publish its ladder; this one is ours). Shakes
// re-prompt without any state change, as WaniKani does for slips that are
// not real mistakes.
import { toKana } from "./kana.js";

const KANA = /[\u3040-\u30ff]/;
const LATIN = /[a-z]/i;
const SMALL = { ぁ: "あ", ぃ: "い", ぅ: "う", ぇ: "え", ぉ: "お", ゃ: "や", ゅ: "ゆ", ょ: "よ", っ: "つ" };

export function foldKana(s) {
  return s.normalize("NFKC").trim()
    .replace(/[\u30a1-\u30f6]/g, (ch) => String.fromCharCode(ch.charCodeAt(0) - 0x60));
}
const bigKana = (s) => s.replace(/[ぁぃぅぇぉゃゅょっ]/g, (ch) => SMALL[ch]);

export function normalizeMeaning(s) {
  return s.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, "").replace(/\s+/g, " ").trim();
}

export function levenshtein(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[b.length];
}

export function tolerance(len) {
  return len <= 3 ? 0 : len <= 5 ? 1 : len <= 8 ? 2 : 3;
}

// checkAnswer(card, part, input) -> { ok } | { shake: hint }
export function checkAnswer(card, part, input) {
  const raw = (input || "").trim();
  if (!raw) return { shake: "Type an answer first." };
  if (part === "reading") {
    const kana = toKana(raw, true);
    if (LATIN.test(kana)) return { shake: "Readings are kana. Finish the romaji so it converts." };
    const want = foldKana(kana);
    const listed = card.answers.map(foldKana);
    if (listed.includes(want)) return { ok: true };
    if (listed.some((a) => bigKana(a) === bigKana(want))) return { shake: "Check the small kana (ゃ ゅ ょ っ)." };
    return { ok: false };
  }
  if (KANA.test(raw)) return { shake: "This asks for the meaning, in English." };
  const want = normalizeMeaning(raw);
  const listed = card.answers.map(normalizeMeaning);
  if (listed.some((a) => levenshtein(a, want) <= tolerance(a.length))) return { ok: true };
  if (listed.some((a) => a.startsWith("to ") && a.slice(3) === want)) return { shake: "It's a verb: start with “to”." };
  return { ok: false };
}
