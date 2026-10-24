// Keyword marks helper for study prose. Pure: no DOM, no storage.

const KANA_ONLY = /^[ぁ-ゖァ-ヺー]+$/;

// Splits text into [{ text, mark }] segments, mark being the class of the term
// found there (null for plain text). English terms match whole words, any
// case, plural "s" included; kana terms match whole kana runs only. Longer
// terms win over shorter ones that start at the same spot.
export function marks(text, terms) {
  const usable = terms.filter((t) => t.text && t.text.trim())
    .sort((a, b) => b.text.length - a.text.length);
  if (!usable.length) return [{ text, mark: null }];
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const kana = "\\u3041-\\u3096\\u30a1-\\u30fa\\u30fc";
  const re = new RegExp(usable.map((t) => (KANA_ONLY.test(t.text)
    ? `((?<![${kana}])${esc(t.text)}(?![${kana}]))`
    : `((?<![A-Za-z])${esc(t.text.trim())}(?:e?s)?(?![A-Za-z]))`)).join("|"), "gi");
  const out = [];
  let at = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > at) out.push({ text: text.slice(at, m.index), mark: null });
    out.push({ text: m[0], mark: usable[m.slice(1).findIndex((g) => g !== undefined)].mark });
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push({ text: text.slice(at), mark: null });
  return out;
}
