// Romaji → hiragana, live. Hepburn plus the common keyboard spellings
// (si/ti/tu/hu/zi, sya/tya/zya, xtsu). Kana and anything else pass through;
// a lone trailing "n" stays until `final` (submit) turns it into ん.
const T = {
  a: "あ", i: "い", u: "う", e: "え", o: "お",
  ka: "か", ki: "き", ku: "く", ke: "け", ko: "こ", kya: "きゃ", kyu: "きゅ", kyo: "きょ",
  sa: "さ", shi: "し", si: "し", su: "す", se: "せ", so: "そ", sha: "しゃ", shu: "しゅ", sho: "しょ", she: "しぇ",
  sya: "しゃ", syu: "しゅ", syo: "しょ",
  ta: "た", chi: "ち", ti: "ち", tsu: "つ", tu: "つ", te: "て", to: "と", cha: "ちゃ", chu: "ちゅ", cho: "ちょ", che: "ちぇ",
  tya: "ちゃ", tyu: "ちゅ", tyo: "ちょ",
  na: "な", ni: "に", nu: "ぬ", ne: "ね", no: "の", nya: "にゃ", nyu: "にゅ", nyo: "にょ",
  ha: "は", hi: "ひ", fu: "ふ", hu: "ふ", he: "へ", ho: "ほ", hya: "ひゃ", hyu: "ひゅ", hyo: "ひょ",
  fa: "ふぁ", fi: "ふぃ", fe: "ふぇ", fo: "ふぉ",
  ma: "ま", mi: "み", mu: "む", me: "め", mo: "も", mya: "みゃ", myu: "みゅ", myo: "みょ",
  ya: "や", yu: "ゆ", yo: "よ",
  ra: "ら", ri: "り", ru: "る", re: "れ", ro: "ろ", rya: "りゃ", ryu: "りゅ", ryo: "りょ",
  wa: "わ", wo: "を", n: "ん",
  ga: "が", gi: "ぎ", gu: "ぐ", ge: "げ", go: "ご", gya: "ぎゃ", gyu: "ぎゅ", gyo: "ぎょ",
  za: "ざ", ji: "じ", zi: "じ", zu: "ず", ze: "ぜ", zo: "ぞ", ja: "じゃ", ju: "じゅ", jo: "じょ", je: "じぇ",
  jya: "じゃ", jyu: "じゅ", jyo: "じょ", zya: "じゃ", zyu: "じゅ", zyo: "じょ",
  da: "だ", di: "ぢ", du: "づ", de: "で", do: "ど", dya: "ぢゃ", dyu: "ぢゅ", dyo: "ぢょ",
  ba: "ば", bi: "び", bu: "ぶ", be: "べ", bo: "ぼ", bya: "びゃ", byu: "びゅ", byo: "びょ",
  pa: "ぱ", pi: "ぴ", pu: "ぷ", pe: "ぺ", po: "ぽ", pya: "ぴゃ", pyu: "ぴゅ", pyo: "ぴょ",
  va: "ゔぁ", vi: "ゔぃ", vu: "ゔ", ve: "ゔぇ", vo: "ゔぉ",
  xa: "ぁ", xi: "ぃ", xu: "ぅ", xe: "ぇ", xo: "ぉ", la: "ぁ", li: "ぃ", lu: "ぅ", le: "ぇ", lo: "ぉ",
  xya: "ゃ", xyu: "ゅ", xyo: "ょ", lya: "ゃ", lyu: "ゅ", lyo: "ょ",
  xtsu: "っ", ltsu: "っ", xtu: "っ", ltu: "っ",
};
const VOWEL = /[aeiouy]/;
// Every proper prefix of a table key ("ny", "sh", "xts"): typed at the end of
// the field it stays romaji until the next letter decides the syllable.
const PREFIXES = new Set();
for (const k of Object.keys(T)) for (let i = 1; i < k.length; i++) PREFIXES.add(k.slice(0, i));

export function toKana(input, final = false) {
  // NFKC first: full-width IME romaji (ｋａ) becomes plain ka.
  const s = input.normalize("NFKC").toLowerCase();
  let out = "";
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    const d = s[i + 1];
    const tail = s.slice(i);
    if (!final && tail.length <= 3 && !T[tail] && PREFIXES.has(tail)) {
      out += tail;
      break;
    }
    if (c === "-") {
      out += "ー";
      i += 1;
    } else if (c < "a" || c > "z") {
      out += c;
      i += 1;
    } else if (c === "n" && d === "'") {
      out += "ん";
      i += 2;
    } else if (c === "n" && d === undefined) {
      // A lone trailing n waits for the next letter; on submit it is ん,
      // unless the field already ends in ん (the user typed "nn").
      out += final ? (out.endsWith("ん") ? "" : "ん") : "n";
      i += 1;
    } else if (c === "n" && d === "n") {
      // "nn" before a vowel or at the end is ん + a pending n (onna, konn…);
      // before a consonant both letters are one ん.
      const after = s[i + 2];
      out += "ん";
      i += after === undefined || VOWEL.test(after) ? 1 : 2;
    } else if (c === "n" && !VOWEL.test(d)) {
      out += "ん";
      i += 1;
    } else if (!VOWEL.test(c) && c !== "n" && (d === c || (c === "t" && d === "c"))) {
      out += "っ";
      i += 1;
    } else {
      let len = 4;
      while (len > 0 && !T[s.slice(i, i + len)]) len -= 1;
      out += len ? T[s.slice(i, i + len)] : c;
      i += len || 1;
    }
  }
  return out;
}
