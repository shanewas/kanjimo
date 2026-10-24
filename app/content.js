// Pure data module for the per-level content format: path builders, own-data
// merge, and reading formatting. No DOM, no storage, no Date.now().

export function padLevel(level) {
  return String(level).padStart(2, "0");
}

export function cardsPath(level, root = "../data") {
  return `${root}/cards/level-${padLevel(level)}.json`;
}

export function itemsPath(level, root = "../data") {
  return `${root}/items/level-${padLevel(level)}.json`;
}

export function ownPath(level, root = "../data") {
  return `${root}/own/level-${padLevel(level)}.json`;
}

// Merges proprietary mnemonics and hints from an own/level-NN.json payload onto cardsById.
// cardsById may be a Map or a plain object.
export function mergeOwn(cardsById, own) {
  if (!own) return;
  const entries = Array.isArray(own.cards)
    ? own.cards.map((c) => [c.id, c])
    : Object.entries(own.cards || own);
  const getCard = (id) => (cardsById instanceof Map ? cardsById.get(id) : cardsById[id]);

  for (const [id, data] of entries) {
    if (!data) continue;
    const card = getCard(id);
    if (!card) continue;
    if (data.mnemonic_meaning) card.mnemonic_meaning = data.mnemonic_meaning;
    if (data.mnemonic_reading) card.mnemonic_reading = data.mnemonic_reading;
    if (data.hint) card.hint = data.hint;
    if (data.hints) card.hints = data.hints;
  }
}

export function formatKun(k) {
  if (!k) return "";
  if (typeof k === "string") return k;
  return k.stem + (k.okurigana ? `.${k.okurigana}` : "");
}

// Reading groups from an items record: On'yomi, Kun'yomi, Nanori.
export function readingGroups(rec) {
  if (!rec || !rec.readings) return {};
  const rd = rec.readings;
  const groups = {};
  if (Array.isArray(rd.on) && rd.on.length) groups["On'yomi"] = rd.on;
  if (Array.isArray(rd.kun) && rd.kun.length) groups["Kun'yomi"] = rd.kun.map(formatKun).filter(Boolean);
  if (Array.isArray(rd.nanori) && rd.nanori.length) groups["Nanori"] = rd.nanori;
  return groups;
}

// Group name ("On'yomi" | "Kun'yomi" | null) taught by rec.teach.
export function taughtGroup(rec) {
  const g = rec && rec.teach && rec.teach.group;
  if (g === "on") return "On'yomi";
  if (g === "kun") return "Kun'yomi";
  return null;
}
