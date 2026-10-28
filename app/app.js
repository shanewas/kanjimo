// Japanese Study app. Static, no build. Renders with textContent-only DOM
// construction (no raw-HTML string injection anywhere). No external links:
// component references resolve to internal item pages or plain text.
// Rules live in engine.js and ledger.js (pure); persistence in store.js.
import { fmtWait, stageName, waitFor } from "./scheduler.js";
import {
  answer, completeItem, currentPrompt, dueItems, forecast, gradedElsewhere, isAvailable, kanjiProgress,
  lessonQueue, levelUp, makeSession, pickReviews, resurrect, seedLevels, stageCounts, startItem,
} from "./engine.js";
import {
  dayKey, daysActive, daysBetween, level60Date, markDone, pace, projectLevel, recordLessons, recordReview,
  row, settle, shiftKey, streak,
} from "./ledger.js";
import * as Store from "./store.js";
import * as Sync from "./sync.js";
const todayKey = () => dayKey(new Date());
import { checkAnswer } from "./answer.js";
import { toKana } from "./kana.js";
import { marks } from "./text.js";
import {
  cardsPath,
  itemsPath,
  mergeOwn,
  ownPath,
  padLevel,
  readingGroups,
  taughtGroup,
} from "./content.js";

const THEME_KEY = "jstudy.theme"; // same literal is read in theme.js before first paint
const SESSION_SOFT_MINUTES = 10;
const BANDS = [
  ["Pleasant", 1, 10], ["Painful", 11, 20], ["Death", 21, 30],
  ["Hell", 31, 40], ["Paradise", 41, 50], ["Reality", 51, 60],
];
const maxLevel = () => (DB.index && DB.index.length ? Math.max(...DB.index.map((r) => r.level)) : 60);
const activeBands = () => {
  const m = maxLevel();
  return BANDS.filter(([, a]) => a <= m).map(([name, a, b]) => [name, a, Math.min(b, m)]);
};
const TYPE_LABEL = { radical: "Radical", kanji: "Kanji", vocabulary: "Vocab" };

// ---------- tiny DOM helpers (textContent only) ----------
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}
function link(href, text, cls) {
  const a = el("a", cls, text);
  a.href = href;
  return a;
}
// Internal link resolver: a scraped component href becomes an internal record
// id when it resolves, else null (rendered as plain text, never outbound).
function internalId(raw) {
  try {
    const segs = new URL(raw, "https://example.invalid/").pathname.replace(/^\/+|\/+$/g, "").split("/");
    if (segs.length !== 2) return null;
    const kinds = { radicals: "radical", kanji: "kanji", vocabulary: "vocabulary" };
    if (!kinds[segs[0]]) return null;
    const id = `${kinds[segs[0]]}/${decodeURIComponent(segs[1])}`;
    return DB.indexById.has(id) ? id : null;
  } catch {
    return null;
  }
}

// ---------- per-level content loading (cards, items, own) ----------
const levelCache = new Map(); // level -> { items: [], cards: [] }
const levelInFlight = new Map(); // level -> Promise
async function fetchJson(url, label) {
  let res;
  try {
    // Always revalidate: artifacts are rebuilt in place, and a stale cached
    // copy (missing fields) silently breaks gating, stages, and search.
    res = await fetch(url, { cache: "no-cache" });
  } catch {
    throw { kind: "fetch", url, label };
  }
  // Gated files on the online version: 401 wants a login, 403 is the daily download limit.
  if (res.status === 401) throw { kind: "login", url, label, status: 401 };
  if (res.status === 403) throw { kind: "limit", url, label, status: 403 };
  if (!res.ok) throw { kind: "fetch", url, label, status: res.status };
  try {
    return await res.json();
  } catch {
    throw { kind: "parse", url, label };
  }
}
async function loadLevel(level) {
  if (levelCache.has(level)) return levelCache.get(level);
  if (levelInFlight.has(level)) return levelInFlight.get(level);

  const p = (async () => {
    const pad = padLevel(level);
    const [cardsData, itemsData] = await Promise.all([
      fetchJson(cardsPath(level), `cards/level-${pad}.json`),
      fetchJson(itemsPath(level), `items/level-${pad}.json`),
    ]);

    let ownData = null;
    try {
      ownData = await fetchJson(ownPath(level), `own/level-${pad}.json`);
    } catch (e) {
      // 404 treated as no own data silently; 401 or 403 re-thrown
      if (e && e.status !== 404 && e.status !== undefined) throw e;
    }

    for (const c of cardsData.cards || []) DB.cardsById.set(c.id, c);
    for (const it of itemsData.items || []) DB.itemsById.set(it.id, it);
    if (ownData) mergeOwn(DB.cardsById, ownData);

    const res = { items: itemsData.items || [], cards: cardsData.cards || [] };
    levelCache.set(level, res);
    // Bound the cache: keep at most 8 levels (index + current + session spill).
    if (levelCache.size > 8) levelCache.delete(levelCache.keys().next().value);
    return res;
  })();

  levelInFlight.set(level, p);
  try {
    return await p;
  } finally {
    levelInFlight.delete(level);
  }
}
async function levelRecords(level) {
  const data = await loadLevel(level);
  return data.items;
}

// ---------- persistent state ----------
let storage = null; // window.localStorage, or null when the browser blocks it
let storeStatus = "fresh"; // see Store.load
let saveFailed = null; // "quota" | "denied" | null
function persist() {
  saveFailed = Store.save(storage, DB.store);
}
// Every local change also queues a push; a copy pulled from the server
// goes through persist() alone, since it is already there.
function saveStore() {
  persist();
  Sync.schedule();
}

// ---------- data boot ----------
const DB = {
  store: Store.fresh(),
  index: null, // search-index.json records
  cardsLoaded: false,
  cardsById: new Map(),
  itemsById: new Map(),
  indexById: new Map(),
  ready: false,
  loadError: null,
};
async function bootData() {
  const recs = await fetchJson("../data/search-index.json", "search-index.json");
  DB.index = recs.records || [];
  for (const r of DB.index) DB.indexById.set(r.id, r);
  DB.ready = true;
}
function levelsForSession() {
  const s = DB.store;
  const currentLevel = s.level || 1;
  const levels = new Set([currentLevel]);
  const due = dueItems(s.items, Date.now());
  for (const rid of due) {
    const ref = DB.indexById.get(rid);
    if (ref && ref.level <= currentLevel) levels.add(ref.level);
  }
  const lessons = lessonQueue(DB.index, s.items, currentLevel);
  for (const r of lessons) {
    if (r.level <= currentLevel) levels.add(r.level);
  }
  if (s.session) {
    for (const p of s.session.prompts || []) {
      const ref = DB.indexById.get(p.rid);
      if (ref) levels.add(ref.level);
    }
  }
  return [...levels].sort((a, b) => a - b);
}
async function ensureCards() {
  // One level at a time: a parallel fan-out tripped nginx's per-IP connection cap (503).
  for (const level of levelsForSession()) await loadLevel(level);
  DB.cardsLoaded = true;
}

// ---------- audio (mp3 first, error fallback, then mute) ----------
function pickAudio(list, skip) {
  const rest = (list || []).filter((a) => a && a.url && a.url !== skip);
  return rest.find((a) => (a.content_type || "").includes("mpeg")) || rest[0] || null;
}
// Two in three words and every kanji reading have no recording. The device's
// own Japanese voice reads the kana then: kana, not the kanji, so it can't
// pick the wrong reading.
const canSpeak = typeof speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined";
function speak(kana) {
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(kana);
  u.lang = "ja-JP";
  u.rate = 0.85;
  const ja = speechSynthesis.getVoices().filter((x) => /^ja\b/i.test(x.lang));
  const voice = ja.find((x) => /natural/i.test(x.name)) || ja[0]; // Edge's neural voices sound far closer to a person
  if (voice) u.voice = voice;
  speechSynthesis.speak(u);
}
function speakButton(kana) {
  const btn = el("button", "btn btn-ghost btn-sm audio-btn", "▶ Hear it");
  btn.type = "button";
  btn.title = "Read by your device's Japanese voice";
  btn.addEventListener("click", () => speak(kana));
  return btn;
}
// nginx serves recordings only as /media/audio/<hash>.mp3|webm; the open build still lists
// archive paths (audio/kanjialive/...) that 404, so those count as no recording.
const SERVED_AUDIO = /^(\.\.)?\/media\/audio\/[a-f0-9]{16,64}\.(mp3|webm)$/;
function audioButton(list, kana = "") {
  const btn = el("button", "btn btn-ghost btn-sm audio-btn", "▶ Play audio");
  btn.type = "button";
  const playable = (list || []).filter((a) => a && a.url && (SERVED_AUDIO.test(a.url) || /^https:\/\//.test(a.url)));
  if (!playable.length && kana && canSpeak) return speakButton(kana);
  const giveUp = () => {
    if (kana && canSpeak) {
      btn.textContent = "▶ Hear it";
      btn.title = "Read by your device's Japanese voice";
      speak(kana);
      return;
    }
    btn.disabled = true;
    btn.textContent = "🔇 Audio unavailable";
    btn.title = "Audio unavailable";
  };
  if (!playable.length) {
    btn.disabled = true;
    btn.textContent = "🔇 Audio unavailable";
    btn.title = "Audio unavailable";
    return btn;
  }
  const player = new Audio();
  let tried = new Set();
  let failed = false;
  player.addEventListener("error", () => {
    const next = pickAudio(playable, [...tried].pop());
    if (next && !tried.has(next.url)) {
      tried.add(next.url);
      player.src = next.url;
      player.play().catch(() => {});
    } else {
      failed = true;
      giveUp();
    }
  });
  btn.addEventListener("click", () => {
    if (failed) return giveUp();
    const first = pickAudio(playable, null);
    tried = new Set([first.url]);
    player.src = first.url;
    player.play().catch((e) => {
      if (e && e.name === "NotAllowedError") return; // autoplay refused; a click still works
      failed = true;
      giveUp();
    });
  });
  return btn;
}
// Hearing the word once, then saying it, is the point of the reading step;
// reduced motion keeps audio to explicit clicks.
function autoplay(btn) {
  if (!btn.disabled && !matchMedia("(prefers-reduced-motion: reduce)").matches) btn.click();
}

// ---------- misc ----------
function normalizeAnswer(s) {
  return (s || "").trim().toLowerCase().replace(/\s+/g, " ");
}
function fillGlyph(box, card) {
  box.textContent = "";
  box.style.setProperty("--chars", String([...(card.glyph || card.glyph_alt || "?")].length));
  if (card.glyph) {
    box.textContent = card.glyph;
  } else if (card.glyph_alt) {
    box.textContent = card.glyph_alt;
  } else if ((card.images || [])[0]) {
    const img = document.createElement("img");
    img.src = card.images[0];
    img.alt = card.answers[0] || "radical image";
    box.appendChild(img);
  } else {
    box.textContent = "?";
  }
}
function typeChip(type) {
  const map = { radical: "chip-radical", kanji: "chip-kanji", vocabulary: "chip-vocab" };
  return el("span", "chip " + (map[type] || "chip-vocab"), TYPE_LABEL[type] || type);
}
// Scraped prose: footer-polluted tails ("About Blog API … Tofugu LLC") get cut.
// `terms` mark the mnemonic's keywords the way WaniKani's pages colour them.
const cutFooter = (text) => text.split(/About Blog API/)[0].trim();
function renderText(parent, text, terms = []) {
  for (const para of cutFooter(text).split(/\n{2,}|\n(?=\S)/)) {
    const t = para.trim();
    if (!t) continue;
    const p = el("p", "prose");
    for (const s of marks(t, terms)) p.append(s.mark ? el("mark", `hl hl-${s.mark}`, s.text) : s.text);
    parent.appendChild(p);
  }
}
// Context sentences as Japanese over English, with Tatoeba/author attribution.
function renderSentences(parent, list, max = 3) {
  if (!list || !list.length) return;
  for (const s of list.slice(0, max)) {
    const box = el("div", "ctx");
    box.append(el("div", "j", s.ja), el("div", "e", s.en));
    const credit = s.source === "tatoeba" || s.source === "tanaka"
      ? (s.author ? `Tatoeba · ${s.author}` : "Tatoeba")
      : (s.author && s.author !== "personal" ? s.author : "");
    if (credit) box.appendChild(el("div", "credit small muted", credit));
    parent.appendChild(box);
  }
}
// Keywords for an item's mnemonic: its own answers, plus the meanings (or,
// for readings, the readings) of the parts it's built from.
function termsFor(rid, part) {
  const ref = DB.indexById.get(rid);
  const card = DB.cardsById.get(`${rid}:${part}`);
  const terms = ((card && card.answers) || []).map((text) => ({ text, mark: part === "reading" ? "reading" : ref.type }));
  for (const id of ref.requires) {
    const c = DB.indexById.get(id);
    if (!c) continue;
    if (part === "meaning") terms.push({ text: c.meanings[0], mark: c.type });
    else for (const text of c.readings || []) terms.push({ text, mark: "reading" });
  }
  if (part === "reading") terms.push({ text: ref.meanings[0], mark: ref.type });
  return terms;
}
const FULL_TYPE = { radical: "Radical", kanji: "Kanji", vocabulary: "Vocabulary" };
// The glyph on a band in its type colour, as on WaniKani: type reads at a glance.
function glyphBand(card, type, caption) {
  const band = el("div", `band band-${type}`);
  const g = el("div", "band-glyph");
  fillGlyph(g, card);
  band.appendChild(g);
  if (caption) band.appendChild(el("div", "band-caption", caption));
  return band;
}
// What is being asked, in words big enough that a reading is never answered
// with a meaning by mistake.
function askBar(type, part) {
  const bar = el("div", `ask ask-${part}`);
  bar.append(`${FULL_TYPE[type]} `, el("b", null, part === "reading" ? "Reading" : type === "radical" ? "Name" : "Meaning"));
  return bar;
}
function glyphOf(rid) {
  const r = DB.indexById.get(rid);
  return (r && (r.glyph || r.meanings[0])) || rid;
}

// ---------- session building: daily quota + lesson budget ----------
function todayRow() {
  return DB.store.days[todayKey()] || { r: 0, l: 0 };
}
// Lessons offered now: batch size, the day's remaining allowance, and the
// Apprentice cap (0 disables it) all bound it.
function lessonBudget() {
  const s = DB.store.settings;
  if (s.apprenticeCap && stageCounts(DB.store.items).apprentice > s.apprenticeCap) return 0;
  return Math.max(0, Math.min(s.batch, s.lessonsPerDay - todayRow().l));
}
function lessonsReady() {
  return lessonQueue(DB.index, DB.store.items, DB.store.level).slice(0, lessonBudget());
}
function partsOf(rid) {
  return DB.cardsById.has(`${rid}:reading`) ? ["meaning", "reading"] : ["meaning"];
}
// Only items the artifacts can prompt for. An id left in the store by a
// rebuilt cards.json would otherwise sit due forever.
const servable = (rid) => DB.cardsById.has(`${rid}:meaning`);
function buildEntries() {
  const s = DB.store.settings;
  const due = dueItems(DB.store.items, Date.now()).filter(servable);
  // Past the quota, "Keep going" serves another quota-sized batch.
  const left = s.reviewsPerDay - todayRow().r;
  const picked = pickReviews(due, DB.store.items, DB.indexById, left > 0 ? left : s.reviewsPerDay, s.order);
  const entries = picked.map((rid) => ({ rid, parts: partsOf(rid) }));
  for (const r of lessonsReady()) if (servable(r.id)) entries.push({ rid: r.id, parts: partsOf(r.id), lesson: true });
  return entries;
}
// Days until the next review, when no lessons can open, owe nothing: mark
// them done now so a stretch with nothing to do never breaks the chain.
function markIdleDays() {
  const s = DB.store.settings;
  const items = DB.store.items;
  const lessonsPossible = lessonQueue(DB.index, items, DB.store.level).length > 0
    && !(s.apprenticeCap && stageCounts(items).apprentice > s.apprenticeCap);
  if (lessonsPossible) return;
  let next = Infinity;
  for (const st of Object.values(items)) if (st.stage < 9 && st.due < next) next = st.due;
  if (!Number.isFinite(next)) return;
  const until = dayKey(new Date(next));
  for (let k = shiftKey(todayKey(), 1); k < until; k = shiftKey(k, 1)) row(DB.store.days, k).done = true;
}

// ---------- view root ----------
const view = () => document.getElementById("view");
function clearView() {
  const v = view();
  v.textContent = "";
  v.className = "wrap";
  return v;
}
function setNav(current) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.getAttribute("data-nav") === current) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}
function updateBadge() {
  const b = document.getElementById("dueBadge");
  const n = signedOutOnline() ? 0 : dueItems(DB.store.items, Date.now()).length;
  if (n > 0) {
    b.hidden = false;
    b.textContent = n > 99 ? "99+" : String(n);
  } else b.hidden = true;
}
function toast(v, text) {
  v.prepend(el("div", "toast", text));
}
function errorPanel(v, err, retry) {
  if (err && err.kind === "login") {
    syncNotice = "Sign in to open that.";
    if (location.hash.startsWith("#/account")) render();
    else location.hash = "#/account";
    return;
  }
  const p = el("div", "panel narrow");
  const fb = el("div", "feedback bad");
  if (err && err.kind === "limit") {
    fb.append(el("b", null, "Today's download limit is used up. "), document.createTextNode("Come back tomorrow."));
    p.appendChild(fb);
    v.appendChild(p);
    return;
  }
  if (err && err.kind === "parse") {
    fb.append(el("b", null, `Couldn't read ${err.label || "data"}. `), document.createTextNode("It may be corrupt. "));
  } else {
    fb.append(el("b", null, `Couldn't load ${err.label || "data"}. `), document.createTextNode("Check the server is running. "));
  }
  const btn = el("button", "btn btn-ghost btn-sm", "Retry");
  btn.type = "button";
  btn.addEventListener("click", retry);
  fb.appendChild(btn);
  p.appendChild(fb);
  v.appendChild(p);
}
function maybeNotices(v) {
  if (storeStatus === "corrupt") {
    const t = el("div", "toast", "Saved progress looked damaged, so this session started fresh. ");
    const dl = el("button", "linklike", "Download damaged data");
    dl.type = "button";
    dl.style.color = "inherit";
    dl.addEventListener("click", () => {
      const raw = Store.quarantined(storage);
      if (raw) download("japanese-study-damaged.json", raw);
    });
    t.appendChild(dl);
    v.prepend(t);
    storeStatus = "ok";
  } else if (storeStatus === "migrated-v2" || storeStatus === "migrated-v1") {
    toast(v, "Progress migrated to one stage per item. Nothing was lost; the old data is kept as a backup.");
    storeStatus = "ok";
  }
  if (saveFailed === "quota") {
    toast(v, "Browser storage is full, progress paused. Export a backup, free space, then keep going.");
  } else if (saveFailed === "denied" || storeStatus === "readonly") {
    toast(v, "Browser storage is blocked, progress lasts for this tab only.");
  }
  if (syncNotice) {
    toast(v, syncNotice);
    syncNotice = "";
  }
}
function syncLine(parent) {
  const st = Sync.status();
  if (st.mode === "unknown") return;
  const line = el("p", "small muted");
  if (st.mode === "off") line.textContent = "Not synced";
  else if (st.mode === "down") line.textContent = "Sync paused";
  else if (st.mode === "anon") line.append("Not synced · ", link("#/account", "Sign in", "linklike"));
  else line.textContent = st.error ? "Sync paused" : st.dirty ? "Syncing…" : "Synced";
  parent.appendChild(line);
}

// ---------- Today ----------
let cumCache = null;
function cumulative() {
  if (!cumCache) {
    const max = maxLevel();
    cumCache = new Array(max + 1).fill(0);
    for (const r of DB.index) cumCache[r.level] += 1;
    for (let l = 1; l <= max; l++) cumCache[l] += cumCache[l - 1];
  }
  return cumCache;
}
function pct(p) {
  return p.total ? Math.round((100 * p.passed) / p.total) : 0;
}
function projection() {
  const today = todayKey();
  const p = pace(DB.store.days, today);
  const started = Object.keys(DB.store.items).length;
  const toExam = daysBetween(today, DB.store.settings.examDate);
  const cum = cumulative();
  const max = maxLevel();
  return {
    pace: p, toExam,
    level: projectLevel(cum, started + p * Math.max(0, toExam)),
    level60: level60Date(today, cum[max] - started, p),
  };
}
function projectionLine() {
  const pr = projection();
  const exam = pr.toExam >= 0 ? `N1 in ${pr.toExam} day${pr.toExam === 1 ? "" : "s"}` : "Exam date passed";
  return pr.pace > 0 ? `${exam} · projected level ${pr.level}` : `${exam} · no pace yet`;
}
function streakStrip(parent) {
  const today = todayKey();
  const strip = el("div", "streak");
  for (const [n, lbl] of [[streak(DB.store.days, today), "day streak"], [daysActive(DB.store.days, today.slice(0, 7)), "days this month"]]) {
    const d = el("div");
    d.append(el("b", null, String(n)), document.createTextNode(lbl));
    strip.appendChild(d);
  }
  parent.appendChild(strip);
}
// When to come back: the next batch of reviews and its hour. Spacing only
// works if the learner returns when items fall due.
function nextReviewLine() {
  const now = Date.now();
  let next = Infinity, n = 0;
  for (const st of Object.values(DB.store.items)) {
    if (st.stage >= 9) continue;
    if (st.due < next) {
      next = st.due;
      n = 1;
    } else if (st.due === next) {
      n += 1;
    }
  }
  if (!Number.isFinite(next)) return "";
  if (next <= now) return `${dueItems(DB.store.items, now).length} reviews ready now`;
  const at = new Date(next);
  const day = dayKey(at) === todayKey() ? "" : dayKey(at) === shiftKey(todayKey(), 1) ? " tomorrow" : ` on ${dayKey(at)}`;
  const mins = Math.round((next - now) / 60000);
  const rel = mins < 60 ? `${mins} min` : fmtWait(next - now);
  return `Next: ${n} review${n === 1 ? "" : "s"}${day} at ${at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} (in ${rel})`;
}
function levelBar(parent, level, p, caption) {
  const max = maxLevel();
  const toLevelUp = Math.max(0, Math.ceil((p.total * 9) / 10) - p.passed); // levelUp's 90% bar, integer-safe
  const goal = level < max && toLevelUp ? ` · ${toLevelUp} more to level ${level + 1}` : "";
  parent.appendChild(el("p", "small muted", caption || `Level ${level} · ${p.passed}/${p.total} kanji passed${level >= max ? " · max" : goal}`));
  if (level < max && p.total > 0) {
    const bar = el("div", "bar");
    const fill = el("i");
    fill.style.width = pct(p) + "%";
    bar.appendChild(fill);
    parent.appendChild(bar);
  }
  // Early in a level only radicals move; say so, or the bar reads as stuck.
  const rp = kanjiProgress(DB.index, DB.store.items, level, "radical");
  if (rp.total && rp.passed < rp.total) {
    parent.appendChild(el("p", "small muted", `Radicals at Guru: ${rp.passed}/${rp.total} · each one opens the kanji built from it`));
  }
}
function renderToday(v) {
  setNav("today");
  document.body.classList.remove("focus");
  maybeNotices(v);
  const items = DB.store.items;
  const level = DB.store.level;
  const s = DB.store.settings;

  if (Object.keys(items).length === 0) {
    // First run: never an empty "0 due".
    const p = el("div", "panel narrow");
    p.appendChild(el("div", "f-display today-num", "Begin."));
    p.appendChild(el("p", "muted", `Start at level ${level}, ${s.lessonsPerDay} new items a day. Kanji unlock as radicals reach Guru.`));
    const row = el("div", "btn-row");
    const go = el("button", "btn btn-primary", `Start Level ${level}`);
    go.type = "button";
    go.addEventListener("click", () => { location.hash = "#/review"; });
    const pick = el("button", "btn btn-ghost", "Pick a start level");
    pick.type = "button";
    pick.addEventListener("click", () => renderStartLevel(v));
    row.append(go, pick);
    p.appendChild(row);
    const alt = el("p", "small muted");
    alt.append(document.createTextNode("Already studying? "));
    const b = link("#/browse", "Browse levels", "linklike");
    const sr = link("#/search", "search the dictionary", "linklike");
    alt.append(
      b,
      document.createTextNode(" or "),
      sr,
      document.createTextNode(". · "),
      link("#/licenses", "Licences", "linklike")
    );
    p.appendChild(alt);
    syncLine(p);
    v.appendChild(p);
    return;
  }

  const today = todayKey();
  const due = dueItems(items, Date.now()).length;
  const lessons = lessonsReady().length;
  const idle = !due && !lessons;
  // Nothing owed on either side counts as done, today and on the empty
  // days ahead, so a stretch with nothing to do never breaks the chain.
  if (idle && !(DB.store.days[today] && DB.store.days[today].done)) {
    settle(DB.store.days, today);
    markDone(DB.store.days, today, 0, 0, s);
    markIdleDays();
    saveStore();
  }
  const row = todayRow();
  const waiting = Math.max(0, lessonQueue(DB.index, items, level).length - lessons);
  const units = s.reviewsPerDay + s.lessonsPerDay;
  const share = row.done || !units ? 100
    : Math.round((100 * (Math.min(row.r, s.reviewsPerDay) + Math.min(row.l, s.lessonsPerDay))) / units);
  const p = el("div", "panel narrow");
  const ring = el("div", "ring");
  ring.style.setProperty("--p", String(share));
  ring.setAttribute("role", "img");
  ring.setAttribute("aria-label", `${row.r} of ${s.reviewsPerDay} reviews and ${row.l} of ${s.lessonsPerDay} lessons today`);
  const inner = el("div");
  inner.append(document.createTextNode(`${row.r} / ${s.reviewsPerDay}`), el("small", null, "reviews"));
  ring.appendChild(inner);
  p.appendChild(ring);
  p.appendChild(el("p", "muted", `${row.l} / ${s.lessonsPerDay} lessons${waiting ? ` · + ${waiting} waiting` : ""}`));
  const btns = el("div", "btn-row");
  if (row.done && row.r + row.l > 0) {
    p.appendChild(el("p", null, "Done for today."));
    if (!idle) btns.appendChild(link("#/review", "Keep going", "btn btn-ghost btn-sm"));
  } else if (idle) {
    p.appendChild(el("p", "muted", "Nothing to do yet. Lessons open as items reach Guru. Today counts as done."));
    btns.appendChild(link("#/browse", "Browse levels", "btn btn-ghost"));
  } else {
    const go = el("button", "btn btn-primary", "Start session");
    go.type = "button";
    go.addEventListener("click", () => { location.hash = "#/review"; });
    btns.appendChild(go);
  }
  p.appendChild(btns);
  if (!due) {
    const nr = nextReviewLine();
    if (nr) p.appendChild(el("p", "small next-review", nr));
  }
  streakStrip(p);
  levelBar(p, level, kanjiProgress(DB.index, items, level));
  p.appendChild(el("p", "small muted", projectionLine()));
  const more = el("p", "small");
  more.append(
    link("#/progress", "Progress", "linklike"),
    document.createTextNode(" · "),
    link("#/settings", "Settings", "linklike"),
    document.createTextNode(" · "),
    link("#/licenses", "Licences", "linklike")
  );
  p.appendChild(more);
  syncLine(p);
  v.appendChild(p);

  const util = el("div", "panel narrow");
  util.appendChild(el("div", "sec-h", "Progress backup"));
  const brow = el("div", "btn-row");
  const ex = el("button", "btn btn-ghost btn-sm", "Export backup");
  ex.type = "button";
  ex.addEventListener("click", exportBackup);
  const im = el("button", "btn btn-ghost btn-sm", "Restore backup…");
  im.type = "button";
  im.addEventListener("click", () => importBackup());
  brow.append(ex, im);
  util.appendChild(brow);
  v.appendChild(util);
}

function renderStartLevel(v) {
  clearView();
  setNav("today");
  const p = el("div", "panel narrow");
  p.appendChild(el("h1", null, "Pick a start level"));
  p.appendChild(el("p", "muted", "Everything below this level counts as known: it enters at Guru 1 and comes back for review in a week. Higher levels open as kanji reach Guru."));
  const form = el("div", "inline-form");
  const input = document.createElement("input");
  input.type = "number";
  input.min = "1";
  input.max = String(maxLevel());
  input.value = String(DB.store.level);
  input.setAttribute("aria-label", "Start level");
  const save = el("button", "btn btn-primary btn-sm", "Save");
  save.type = "button";
  save.addEventListener("click", () => {
    const now = Date.now();
    DB.store.level = Math.max(1, Math.min(maxLevel(), parseInt(input.value, 10) || 1));
    seedLevels(DB.index, DB.store.items, DB.store.level, now);
    for (const st of Object.values(DB.store.items)) if (!st.at) st.at = now;
    saveStore();
    location.hash = "#/review";
  });
  form.append(input, save);
  p.appendChild(form);
  v.appendChild(p);
  input.focus();
  input.select();
}

// ---------- export / import ----------
function download(name, text) {
  const blob = new Blob([text], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    URL.revokeObjectURL(a.href);
    a.remove();
  }, 1000);
}
function exportBackup() {
  download(`japanese-study-backup-${todayKey()}.json`, JSON.stringify(DB.store));
}
function importBackup() {
  const input = document.getElementById("importFile");
  if (!input) return;
  input.value = "";
  input.click();
}
function initImport() {
  if (document.getElementById("importFile")) return;
  const input = document.createElement("input");
  input.type = "file";
  input.id = "importFile";
  input.accept = "application/json,.json";
  input.className = "visually-hidden";
  input.setAttribute("aria-hidden", "true");
  input.setAttribute("tabindex", "-1");
  input.addEventListener("change", () => {
    const f = input.files && input.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        // A restored backup is the newest word on every item, so it wins any
        // later merge against the server copy.
        const now = Date.now();
        DB.store = Store.parseImport(rd.result, now);
        for (const st of Object.values(DB.store.items)) st.at = now;
        DB.store.settingsAt = now;
        settle(DB.store.days, todayKey());
        saveStore();
        updateBadge();
        render();
        toast(view(), "Backup restored. Nothing was lost.");
      } catch {
        toast(view(), "That file is not a study backup. Nothing changed.");
      }
    };
    rd.readAsText(f);
  });
  document.body.appendChild(input);
}

// ---------- review session ----------
// Micro-flow: prompt → answered → next … → wrap-up. The engine owns the
// prompt list (kept in store.session, so a reload resumes); this file owns
// rendering, the typed-answer check and the per-session stats.
let session = null;
let phase = "idle"; // prompt | answered | graded
let stats = null;
let lastMove = ""; // stage change of the item just completed, shown once
let verdict = false; // checker's call on the current answer; Enter accepts it
function newStats() {
  return {
    reviewed: 0, firstTry: 0, lessons: 0, opened: [], learned: [],
    startLevel: DB.store.level, startPct: pct(kanjiProgress(DB.index, DB.store.items, DB.store.level)),
  };
}
async function startSession(v) {
  setNav("review");
  document.body.classList.add("focus");
  if (!DB.cardsLoaded) {
    const wait = el("div", "panel narrow");
    wait.appendChild(el("div", "skeleton", null));
    v.appendChild(wait);
  }
  try {
    await ensureCards();
  } catch (e) {
    document.body.classList.remove("focus");
    errorPanel(clearView(), e, () => render());
    return;
  }
  const saved = DB.store.session;
  if (saved && dayKey(new Date(saved.startedAt)) === todayKey() && currentPrompt(saved)) session = saved;
  else session = makeSession(buildEntries(), DB.store.settings.backToBack, Date.now());
  if (!currentPrompt(session)) {
    session = null;
    DB.store.session = null;
    location.hash = "#/today";
    return;
  }
  stats = newStats();
  lastMove = "";
  DB.store.session = session;
  saveStore();
  renderPrompt(v);
}
function sessionCounts() {
  const all = Object.values(session.progress);
  return { done: all.filter((p) => p.done >= p.need).length, total: all.length };
}
function sessionProgress() {
  const { done, total } = sessionCounts();
  return `Item ${Math.min(done + 1, total)} of ${total}`;
}
// Shared top of a prompt and its reveal: where you are, then what is asked.
function promptHead(panel, p, card) {
  const { done, total } = sessionCounts();
  const line = el("div", "progress-line");
  line.append(el("span", null, `${sessionProgress()}${p.lesson ? " · New" : ""} · Level ${card.level}`), endLink());
  const bar = el("div", "bar session-bar");
  const fill = el("i");
  fill.style.width = `${Math.round((100 * done) / total)}%`;
  bar.appendChild(fill);
  panel.append(line, bar);
  if (lastMove) {
    panel.appendChild(el("div", "feedback info", lastMove));
    lastMove = "";
  }
  panel.append(glyphBand(card, card.type), askBar(card.type, p.part));
}
function cardFor(p) {
  return DB.cardsById.get(`${p.rid}:${p.part}`);
}
function endLink() {
  const end = el("button", "linklike", "End early");
  end.type = "button";
  end.addEventListener("click", () => finishSession(view()));
  return end;
}
function renderPrompt(v) {
  clearView();
  setNav("review");
  document.body.classList.add("focus");
  document.onkeydown = null;
  const p = session && currentPrompt(session);
  if (!p) return finishSession(view());
  if (p.lesson && !session.studied) {
    lastMove = "";
    return renderLessonPane(v, 0);
  }
  const card = cardFor(p);
  const panel = el("div", "panel narrow");
  if (Date.now() - session.startedAt > SESSION_SOFT_MINUTES * 60 * 1000) {
    const n = el("div", "feedback info");
    n.append(document.createTextNode("Past 10 minutes. "), endLink());
    panel.appendChild(n);
  }
  promptHead(panel, p, card);

  phase = "prompt";
  const input = document.createElement("input");
  input.className = "answer";
  input.placeholder = p.part === "reading" ? "答え (romaji turns into kana)" : "Meaning, in English";
  if (p.part === "reading") input.lang = "ja";
  input.setAttribute("aria-label", "Your answer");
  input.setAttribute("autocomplete", "off");
  input.setAttribute("autocapitalize", "off");
  input.setAttribute("spellcheck", "false");
  panel.appendChild(input);
  const hint = el("p", "small muted");
  hint.append(document.createTextNode("Press "), el("kbd", null, "Enter"), document.createTextNode(" to reveal."));
  panel.appendChild(hint);
  v.appendChild(panel);
  input.focus();
  if (p.part === "reading") {
    input.addEventListener("input", () => {
      const k = toKana(input.value.replace(/\s+/g, ""));
      if (k !== input.value) input.value = k;
    });
  }
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    e.stopPropagation(); // the reveal screen's document handler must not see this same Enter
    const r = checkAnswer(card, p.part, input.value);
    if (r.shake) return showShake(panel, input, r.shake);
    revealAnswer(view(), r.ok, p.part === "reading" ? toKana(input.value, true) : input.value);
  });
}
function showShake(panel, input, msg) {
  let hint = panel.querySelector(".shake-hint");
  if (!hint) {
    hint = el("div", "feedback info shake-hint");
    panel.appendChild(hint);
  }
  hint.textContent = msg;
  input.classList.remove("shake");
  void input.offsetWidth;
  input.classList.add("shake");
  input.focus();
  input.select();
}
// Study pane per lesson item, then the quiz over the batch. Kanji and
// vocabulary take two steps, meaning then reading, so each screen holds one
// thing to learn; radicals take one. Parts are shown at first sight, since
// that is when pointing them out helps recall most. Readings, hints and
// context come from the level file (one cached fetch per level).
function lessonItems() {
  return [...new Set(session.prompts.filter((p) => p.lesson).map((p) => p.rid))];
}
// On'yomi / Kun'yomi / Nanori rows, the group taught by rec.teach set apart.
function readingRows(rec) {
  const groups = readingGroups(rec);
  if (!Object.keys(groups).length) return null;
  const focus = taughtGroup(rec);
  const box = el("div", "readings");
  for (const [name, list] of Object.entries(groups)) {
    const isFocus = focus === name;
    const row = el("div", `rg${isFocus ? " focus" : focus ? " dim" : ""}`);
    row.append(el("span", null, name), el("b", null, list.join("、")));
    if (isFocus) row.appendChild(el("i", "tag", "learn this one"));
    box.appendChild(row);
  }
  return box;
}
function partChips(parent, label, partsOrRec, joined, asLink = false) {
  const ids = Array.isArray(partsOrRec) ? partsOrRec : ((partsOrRec && (partsOrRec.parts || partsOrRec.requires)) || []);
  const inlineParts = (!Array.isArray(partsOrRec) && partsOrRec && partsOrRec.inline_parts) || [];
  if (!ids.length && !inlineParts.length) return;
  const row = el("div", "compose");
  for (const id of ids) {
    const r = DB.indexById.get(id);
    if (!r) continue;
    if (joined && row.children.length) row.appendChild(el("span", "plus", "+"));
    const c = asLink ? link(`#/item/${encodeURIComponent(r.id)}`, "", `part part-${r.type}`) : el("span", `part part-${r.type}`);
    if (r.glyph) c.appendChild(el("b", null, r.glyph));
    else if (r.images && r.images[0]) {
      const img = document.createElement("img");
      img.src = r.images[0].startsWith("http") ? r.images[0] : `../data/${r.images[0]}`;
      img.alt = r.meanings[0] || "part";
      c.appendChild(img);
    }
    c.append(r.meanings[0] || "");
    row.appendChild(c);
  }
  for (const ip of inlineParts) {
    if (joined && row.children.length) row.appendChild(el("span", "plus", "+"));
    const c = el("span", "part part-radical");
    if (ip.image) {
      const img = document.createElement("img");
      img.src = ip.image.startsWith("http") ? ip.image : `../data/${ip.image}`;
      img.alt = ip.glyph || "part";
      c.appendChild(img);
    }
    if (ip.glyph) c.appendChild(el("b", null, ip.glyph));
    row.appendChild(c);
  }
  if (row.children.length) parent.append(el("div", "sec-h", label), row);
}
function addHint(parent, text, terms) {
  if (!text) return;
  const box = el("div", "hint");
  box.appendChild(el("div", "sec-h", "Hint"));
  renderText(box, text, terms);
  parent.appendChild(box);
}
let paneToken = 0; // a slow level fetch must not paint over a newer pane
async function renderLessonPane(v, i, step = 0) {
  const token = ++paneToken;
  const ids = lessonItems();
  const rid = ids[i];
  const ref = DB.indexById.get(rid);
  const mc = DB.cardsById.get(`${rid}:meaning`);
  const rc = DB.cardsById.get(`${rid}:reading`);
  const steps = rc ? ["Meaning", "Reading"] : ["Name"];
  let rec = null;
  try {
    await loadLevel(ref.level);
    rec = DB.itemsById.get(rid) || null;
  } catch { /* the lesson works from the cards alone */ }
  if (!session || session.studied || token !== paneToken) return;
  clearView();
  window.scrollTo(0, 0);
  setNav("review");
  document.body.classList.add("focus");
  const panel = el("div", "panel narrow lesson");
  const line = el("div", "progress-line");
  line.append(el("span", null, `Lesson ${i + 1} of ${ids.length} · New ${FULL_TYPE[ref.type].toLowerCase()} · Level ${ref.level}`), endLink());
  panel.append(line, glyphBand(mc, ref.type, mc.answers[0]));
  const tabs = el("div", "steps");
  steps.forEach((name, k) => {
    const b = el("button", null, name);
    b.type = "button";
    if (k === step) b.setAttribute("aria-current", "step");
    b.addEventListener("click", () => renderLessonPane(view(), i, k));
    tabs.appendChild(b);
  });
  panel.appendChild(tabs);

  if (step === 0) {
    if (ref.type !== "radical") partChips(panel, ref.type === "kanji" ? "Built from these radicals" : "Built from these kanji", rec || ref.requires, true);
    if (mc.answers.length > 1) panel.appendChild(el("p", "muted", `Also accepted: ${mc.answers.slice(1).join(", ")}`));
    if (mc.word_type) panel.appendChild(el("p", "small muted", mc.word_type));
    if (mc.mnemonic_meaning) {
      panel.appendChild(el("div", "sec-h", ref.type === "radical" ? "Mnemonic" : "Meaning mnemonic"));
      renderText(panel, mc.mnemonic_meaning, termsFor(rid, "meaning"));
    }
    addHint(panel, mc.hint, termsFor(rid, "meaning"));
    if (ref.type === "radical") {
      const found = DB.index.filter((r) => r.type === "kanji" && r.requires.includes(rid)).slice(0, 6).map((r) => r.id);
      partChips(panel, "Found in kanji", found, false);
    }
  } else {
    const rows = ref.type === "kanji" && readingRows(rec);
    panel.appendChild(rows || el("p", "lesson-reading", rc.answers.join("、")));
    const say = el("div", "say");
    const kana = (ref.type === "kanji" && rec && rec.teach && rec.teach.reading) || rc.answers[0];
    if ((rc.audio && rc.audio.length) || canSpeak) {
      const btn = audioButton(rc.audio, kana);
      say.append(btn, el("span", "small muted", "Say it out loud with the audio."));
      autoplay(btn);
    } else {
      say.appendChild(el("span", "small muted", "Say it out loud once before moving on."));
    }
    panel.appendChild(say);
    if (rc.mnemonic_reading) {
      panel.appendChild(el("div", "sec-h", "Reading mnemonic"));
      renderText(panel, rc.mnemonic_reading, termsFor(rid, "reading"));
    }
    addHint(panel, rc.hint, termsFor(rid, "reading"));
    if (rec && rec.sentences && rec.sentences.length) {
      panel.appendChild(el("div", "sec-h", "In a sentence"));
      renderSentences(panel, rec.sentences);
    }
  }

  const strip = el("div", "batch");
  ids.forEach((id, k) => {
    const r = DB.indexById.get(id);
    const b = el("button", `batch-item t-${r.type}${k === i ? " is-current" : ""}`, r.glyph || r.meanings[0]);
    b.type = "button";
    b.title = r.meanings[0] || "";
    b.addEventListener("click", () => renderLessonPane(view(), k, 0));
    strip.appendChild(b);
  });
  const startQuiz = () => {
    session.studied = true;
    DB.store.session = session;
    saveStore();
    renderPrompt(view());
  };
  const go = (d) => {
    let ni = i;
    let ns = step + d;
    if (ns < 0) {
      ni = i - 1;
      if (ni < 0) return;
      ns = partsOf(ids[ni]).length - 1;
    } else if (ns >= steps.length) {
      ni = i + 1;
      ns = 0;
    }
    if (ni >= ids.length) return startQuiz();
    renderLessonPane(view(), ni, ns);
  };
  const row = el("div", "btn-row");
  if (i > 0 || step > 0) {
    const back = el("button", "btn btn-ghost", "Back");
    back.type = "button";
    back.addEventListener("click", () => go(-1));
    row.appendChild(back);
  }
  const last = i + 1 >= ids.length && step + 1 >= steps.length;
  const next = el("button", "btn btn-primary", last ? "Start quiz" : "Next");
  next.type = "button";
  next.addEventListener("click", () => go(1));
  row.appendChild(next);
  const keys = el("p", "small muted");
  keys.append(el("kbd", null, "Enter"), " or ", el("kbd", null, "→"), last ? " starts the quiz · " : " next · ", el("kbd", null, "←"), " back");
  panel.append(row, keys, strip);
  v.appendChild(panel);
  next.focus({ preventScroll: true });
  next.onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      next.click();
    }
  };
  document.onkeydown = (e) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      go(1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      go(-1);
    }
  };
}
// Chunk pause after every ten completed reviews: keep going or stop here.
function renderPause(v) {
  clearView();
  setNav("review");
  const left = Object.values(session.progress).filter((p) => p.done < p.need).length;
  const panel = el("div", "panel narrow");
  panel.appendChild(el("div", "wrapup-num", `${session.completed} done`));
  panel.appendChild(el("p", "muted", `${left} left in this session. Stop here and the rest waits; nothing is lost.`));
  const row = el("div", "btn-row");
  const go = el("button", "btn btn-primary", "Keep going");
  go.type = "button";
  go.addEventListener("click", () => renderPrompt(view()));
  const stop = el("button", "btn btn-ghost", "Stop");
  stop.type = "button";
  stop.addEventListener("click", () => finishSession(view()));
  row.append(go, stop);
  panel.appendChild(row);
  v.appendChild(panel);
  go.focus();
  go.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); go.click(); } };
}
// A miss on an item without a mnemonic still gets something to hold on to:
// the parts it is built from, or the reading groups and one sentence.
function missHelp(panel, p) {
  const ref = DB.indexById.get(p.rid);
  const rec = DB.itemsById.get(p.rid) || null;
  if (!ref) return;
  if (p.part === "meaning") {
    if (ref.type === "kanji") partChips(panel, "Built from these radicals", rec || ref.requires, true);
    else if (ref.type === "vocabulary") partChips(panel, "Built from these kanji", rec || ref.requires, true);
    else partChips(panel, "Found in kanji", DB.index.filter((r) => r.type === "kanji" && r.requires.includes(p.rid)).slice(0, 6).map((r) => r.id), false);
    return;
  }
  const rows = ref.type === "kanji" && rec && readingRows(rec);
  if (rows) panel.appendChild(rows);
  if (rec && rec.sentences && rec.sentences.length) {
    panel.appendChild(el("div", "sec-h", "In a sentence"));
    renderSentences(panel, rec.sentences.slice(0, 1));
  }
}
function revealAnswer(v, ok, value) {
  if (phase !== "prompt") return;
  phase = "answered";
  verdict = ok;
  const p = currentPrompt(session);
  const card = cardFor(p);
  clearView();
  setNav("review");
  document.body.classList.add("focus");
  const panel = el("div", "panel narrow");
  promptHead(panel, p, card);
  const typed = el("div", `response ${ok ? "ok" : "bad"}`, normalizeAnswer(value) ? value.trim() : "(blank)");
  if (p.part === "reading") typed.lang = "ja";
  panel.appendChild(typed);
  const fb = el("div", ok ? "feedback good" : "feedback bad");
  if (ok) {
    fb.append(el("b", null, "Correct. "), card.answers.join(", "));
  } else {
    fb.append(el("b", null, "Not quite. "), `Correct answer: ${card.answers.join(", ")}`);
  }
  panel.appendChild(fb);
  // A miss gets its mnemonic at once: feedback right after a failed
  // retrieval is when the correction sticks best.
  const m = !ok && (p.part === "meaning" ? card.mnemonic_meaning : card.mnemonic_reading);
  if (m) {
    const box = el("div", "hint");
    box.appendChild(el("div", "sec-h", p.part === "meaning" ? "Meaning mnemonic" : "Reading mnemonic"));
    renderText(box, m, termsFor(p.rid, p.part));
    panel.appendChild(box);
  } else if (!ok) missHelp(panel, p);
  if (p.part === "reading" && ((card.audio && card.audio.length) || canSpeak)) {
    const say = el("div", "say");
    const btn = audioButton(card.audio, card.answers[0]);
    say.append(btn, el("span", "small muted", "Say it with the audio."));
    panel.appendChild(say);
    autoplay(btn);
  }
  const grades = el("div", "grades");
  grades.style.gridTemplateColumns = "repeat(2, 1fr)";
  // What "Got it" does: completes the item only on its last half, and the
  // move then counts every miss so far.
  const pr = session.progress[p.rid];
  const st = DB.store.items[p.rid];
  const incorrect = pr.missM + pr.missR;
  let gotLabel;
  if (pr.done + 1 < pr.need) gotLabel = `${p.part === "meaning" ? "reading" : "meaning"} next`;
  else if (p.lesson || !st) gotLabel = `${stageName(1)} · ${fmtWait(waitFor(1, card.level))}`;
  else {
    const { to } = completeItem(st, incorrect, Date.now(), card.level);
    gotLabel = `${stageName(to)} · ${fmtWait(waitFor(to, card.level))}${incorrect ? ` after ${incorrect} miss${incorrect === 1 ? "" : "es"}` : ""}`;
  }
  // The checker's verdict is the default Enter takes; the other button is the
  // override for a typo the checker missed or a lucky guess.
  const miss = el("button", ok ? "grade" : "grade is-default miss");
  miss.type = "button";
  miss.append(document.createTextNode("Missed it"), el("small", null, "again soon"));
  miss.addEventListener("click", () => gradeCurrent(view(), false));
  const got = el("button", ok ? "grade is-default" : "grade");
  got.type = "button";
  got.append(document.createTextNode("Got it"), el("small", null, gotLabel));
  got.addEventListener("click", () => gradeCurrent(view(), true));
  grades.append(miss, got);
  panel.appendChild(grades);
  const hint = el("p", "small muted");
  hint.append(document.createTextNode("Keys: "), el("kbd", null, "Enter"), document.createTextNode(" next · "), el("kbd", null, "1"), document.createTextNode(" missed · "), el("kbd", null, "2"), document.createTextNode(" got it"));
  panel.appendChild(hint);
  v.appendChild(panel);
  document.onkeydown = (e) => {
    if (phase !== "answered") return;
    if (e.key === "Enter") {
      e.preventDefault();
      gradeCurrent(view(), verdict);
    } else if (e.key === "1") {
      e.preventDefault();
      gradeCurrent(view(), false);
    } else if (e.key === "2") {
      e.preventDefault();
      gradeCurrent(view(), true);
    }
  };
}
function gradeCurrent(v, correct) {
  if (phase !== "answered") return;
  phase = "graded";
  document.onkeydown = null;
  const now = Date.now();
  const ev = answer(session, correct);
  if (ev.type === "complete" || ev.type === "lesson") {
    // A sync pull can replace the store mid-session: skip items that vanished
    // or that another device already graded or started.
    const rec = DB.indexById.get(ev.rid);
    const st = DB.store.items[ev.rid];
    const elsewhere = !rec || (ev.type === "complete" ? !st || gradedElsewhere(st, session.startedAt) : !!st);
    const level = rec ? rec.level : 0;
    if (elsewhere) {
      lastMove = `${glyphOf(ev.rid)} · already graded on another device`;
    } else if (ev.type === "complete") {
      const { state, from, to } = completeItem(DB.store.items[ev.rid], ev.incorrect, now, level);
      DB.store.items[ev.rid] = { ...state, at: now };
      recordReview(DB.store.days, todayKey(), ev.incorrect, to > from);
      stats.reviewed += 1;
      if (ev.incorrect === 0) stats.firstTry += 1;
      lastMove = `${glyphOf(ev.rid)} · ${stageName(from)} → ${stageName(to)}`;
      const before = DB.store.level;
      DB.store.level = levelUp(DB.index, DB.store.items, before);
      for (let l = before + 1; l <= DB.store.level; l++) stats.opened.push(l);
    } else {
      DB.store.items[ev.rid] = { ...startItem(level, now), at: now };
      recordLessons(DB.store.days, todayKey(), 1);
      stats.lessons += 1;
      stats.learned.push(ev.rid);
      lastMove = `${glyphOf(ev.rid)} · ${stageName(1)}, next review in ${fmtWait(waitFor(1, level))}`;
    }
  }
  DB.store.session = session;
  saveStore();
  updateBadge();
  if (ev.end) finishSession(v);
  else if (ev.chunk) renderPause(v);
  else renderPrompt(v);
}
// Ends the session without rendering: completed items are already saved,
// so only the day's done flag and the resumable session need writing.
function closeSession() {
  document.onkeydown = null;
  session = null;
  phase = "idle";
  DB.store.session = null;
  settle(DB.store.days, todayKey());
  markDone(DB.store.days, todayKey(), dueItems(DB.store.items, Date.now()).length, lessonsReady().length, DB.store.settings);
  markIdleDays();
  saveStore();
  updateBadge();
}
function finishSession(v) {
  const s = stats || newStats();
  const startedAt = session ? session.startedAt : Date.now();
  closeSession();
  document.body.classList.remove("focus");
  clearView();
  setNav("review");
  const today = todayKey();
  const items = DB.store.items;
  const level = DB.store.level;
  const remaining = dueItems(items, Date.now()).length;
  const lessons = lessonsReady().length;
  const acc = s.reviewed ? Math.round((100 * s.firstTry) / s.reviewed) : 0;
  const mins = Math.max(1, Math.round((Date.now() - startedAt) / 60000));
  const days = streak(DB.store.days, today);
  const guruToday = Object.values(items).filter((x) => x.passed && dayKey(new Date(x.passed)) === today).length;
  const done = !!(DB.store.days[today] && DB.store.days[today].done);
  const p = el("div", "panel narrow");
  p.appendChild(el("div", "wrapup-num cheer", done ? "Done for today." : "Done."));
  p.appendChild(el("p", "muted", `${mins} minute${mins === 1 ? "" : "s"} · streak ${days} day${days === 1 ? "" : "s"}`));
  for (const lv of s.opened) {
    const fb = el("div", "feedback good");
    fb.append(el("b", null, `Level ${lv} unlocked. `), document.createTextNode("New radicals wait in your next session."));
    p.appendChild(fb);
  }
  const grid = el("div", "stat-grid");
  for (const [n, lbl, cls] of [[s.reviewed, "reviewed", ""], [s.reviewed ? `${acc}%` : "–", "first-try", ""], [s.lessons, "lessons", "stat-vocab"],
    [guruToday, "reached Guru today", "stat-guru"], [remaining, "still due", ""]]) {
    const st = el("div", `stat ${cls}`);
    st.append(el("b", null, String(n)), el("span", null, lbl));
    grid.appendChild(st);
  }
  p.appendChild(grid);
  if (s.learned.length) {
    p.appendChild(el("div", "sec-h", "New today"));
    const row = el("div", "batch flat");
    for (const rid of s.learned) {
      const r = DB.indexById.get(rid);
      const a = link(`#/item/${encodeURIComponent(rid)}`, r.glyph || r.meanings[0], `batch-item t-${r.type}`);
      a.title = r.meanings[0] || "";
      row.appendChild(a);
    }
    p.appendChild(row);
  }
  const nr = nextReviewLine();
  if (nr) p.appendChild(el("p", "next-review", nr));
  // Level position, as a delta from the start of the session.
  const kp = kanjiProgress(DB.index, items, level);
  levelBar(p, level, kp, level !== s.startLevel ? `Level ${s.startLevel} → ${level}` : `Level ${level}: ${s.startPct}% → ${pct(kp)}%`);
  p.appendChild(el("p", "small muted", projectionLine()));
  const row = el("div", "btn-row");
  row.append(link("#/today", "Today", "btn btn-primary"));
  if (remaining > 0 || lessons > 0) row.append(link("#/review", "Keep going", "btn btn-ghost"));
  p.appendChild(row);
  v.appendChild(p);
}

// ---------- browse ----------
function levelStats(level) {
  let total = 0, started = 0, burned = 0;
  for (const r of DB.index) {
    if (r.level !== level) continue;
    total += 1;
    const st = DB.store.items[r.id];
    if (st) started += 1;
    if (st && st.stage >= 9) burned += 1;
  }
  return { total, started, burned };
}
function renderBrowse(v) {
  setNav("browse");
  document.body.classList.remove("focus");
  v.appendChild(el("h1", null, "Browse"));
  const max = maxLevel();
  const bands = activeBands();
  v.appendChild(el("p", "sub", `${max} levels in ${bands.length} bands. Bars show share started.`));
  const rails = el("div", "rails");
  for (const [name, a, b] of bands) {
    let total = 0, started = 0;
    for (let lv = a; lv <= b; lv++) {
      const s = levelStats(lv);
      total += s.total;
      started += s.started;
    }
    const pct = total ? Math.round((100 * started) / total) : 0;
    const rail = link(`#/browse/${a}-${b}`, "", "rail");
    rail.appendChild(el("b", null, `${name} ${a}–${b}`));
    const bar = el("div", "bar");
    const fill = el("i");
    fill.style.width = pct + "%";
    bar.appendChild(fill);
    rail.append(bar, el("span", "mono small", `${started}/${total}`));
    rails.appendChild(rail);
  }
  v.appendChild(rails);
}
function renderBand(v, a, b) {
  setNav("browse");
  document.body.classList.remove("focus");
  const band = activeBands().find(([, x, y]) => x === a && y === b);
  v.appendChild(el("h1", null, band ? `${band[0]} ${a}–${b}` : `Levels ${a}–${b}`));
  v.appendChild(link("#/browse", "← All bands", "linklike"));
  for (let lv = a; lv <= b; lv++) {
    const s = levelStats(lv);
    const h = el("h2", null, `Level ${lv}`);
    const meta = el("p", "sub", `${s.started}/${s.total} started · ${s.burned} burned`);
    v.append(h, meta);
    const row = el("div", "glyph-row");
    for (const r of DB.index) {
      if (r.level !== lv) continue;
      const st = DB.store.items[r.id];
      const locked = !st && !isAvailable(r, DB.store.items, DB.store.level);
      const g = link(`#/item/${encodeURIComponent(r.id)}`, r.glyph || r.meanings[0] || "?", locked ? "locked" : (st ? "done" : null));
      g.title = locked ? `${r.type} · locked (needs Guru prerequisites)` : `${r.type} · ${(r.meanings[0] || "")}`;
      row.appendChild(g);
    }
    v.appendChild(row);
  }
}

// ---------- search ----------
function searchRecords(q) {
  const needle = normalizeAnswer(q);
  if (!needle) return [];
  const out = [];
  for (const r of DB.index) {
    const hay = [r.glyph, ...(r.meanings || []), ...(r.readings || [])]
      .join(" ").toLowerCase();
    if (hay.includes(needle)) {
      out.push(r);
      if (out.length >= 30) break;
    }
  }
  return out;
}
function renderSearch(v, initial) {
  setNav("search");
  document.body.classList.remove("focus");
  v.appendChild(el("h1", null, "Search"));
  v.appendChild(el("p", "sub", "Glyph, meaning, or reading. Arrow keys + Enter to open."));
  const input = document.createElement("input");
  input.className = "answer";
  input.value = initial || "";
  input.setAttribute("aria-label", "Search");
  input.setAttribute("autocomplete", "off");
  input.setAttribute("spellcheck", "false");
  v.appendChild(input);
  const list = el("ul", "result-list");
  v.appendChild(list);
  let active = 0;
  function paint() {
    list.textContent = "";
    const q = input.value;
    if (!normalizeAnswer(q)) return;
    const hits = searchRecords(q);
    if (!hits.length) {
      const li = el("li");
      li.appendChild(el("p", "prose", `No matches for ‘${q.trim()}’. `));
      const clr = el("button", "linklike", "Clear search");
      clr.type = "button";
      clr.addEventListener("click", () => { input.value = ""; paint(); input.focus(); });
      li.appendChild(clr);
      list.appendChild(li);
      return;
    }
    active = Math.min(active, hits.length - 1);
    hits.forEach((r, i) => {
      const li = el("li");
      const a = link(`#/item/${encodeURIComponent(r.id)}`, "");
      if (i === active) a.classList.add("active");
      a.appendChild(el("span", "g", r.glyph || "？"));
      const mid = el("span", null, (r.meanings[0] || "") + " ");
      if ((r.readings || []).length) mid.appendChild(el("span", "m", `· ${r.readings.slice(0, 3).join(", ")}`));
      const right = el("span", "sp");
      right.appendChild(typeChip(r.type));
      const k = el("kbd", null, "↵");
      right.appendChild(k);
      a.append(mid, right);
      li.appendChild(a);
      list.appendChild(li);
    });
  }
  input.addEventListener("input", () => { active = 0; paint(); });
  input.addEventListener("keydown", (e) => {
    const links = [...list.querySelectorAll("a")];
    if (e.key === "ArrowDown" && links.length) {
      e.preventDefault();
      active = Math.min(active + 1, links.length - 1);
      paint();
    } else if (e.key === "ArrowUp" && links.length) {
      e.preventDefault();
      active = Math.max(active - 1, 0);
      paint();
    } else if (e.key === "Enter" && links[active]) {
      e.preventDefault();
      links[active].click();
    }
  });
  paint();
  input.focus();
}

// ---------- item page ----------
// Renders raw sections in the fixed order: identity header, mnemonics,
// context, composition. Skips nav/junk sections and footer-polluted text.
async function renderItem(v, rid) {
  setNav("");
  document.body.classList.remove("focus");
  const ref = DB.indexById.get(rid);
  if (!ref) {
    const p = el("div", "panel narrow");
    p.appendChild(el("p", "prose", "That item is not in the index."));
    p.appendChild(link("#/search", "← Search", "linklike"));
    v.appendChild(p);
    return;
  }
  let rec = null;
  try {
    await loadLevel(ref.level);
    rec = DB.itemsById.get(rid) || null;
  } catch (e) {
    errorPanel(v, e, () => render());
    return;
  }
  if (!rec) {
    const p = el("div", "panel narrow");
    p.appendChild(el("p", "prose", "That item is missing from its level file."));
    v.appendChild(p);
    return;
  }
  const p = el("div", "panel narrow");
  // Identity header.
  const head = el("div", "item-head");
  const glyph = el("div", `item-glyph tile band-${rec.type}`);
  if (rec.glyph) glyph.textContent = rec.glyph;
  else if (rec.glyph_alt) glyph.textContent = rec.glyph_alt;
  else if ((rec.images || [])[0]) {
    const img = document.createElement("img");
    const src0 = rec.images[0];
    img.src = src0.startsWith("http") ? src0 : `../data/${src0}`;
    img.alt = "radical image";
    glyph.appendChild(img);
  }
  const id = el("div", "item-id");
  const chipRow = el("span");
  chipRow.appendChild(typeChip(rec.type));
  chipRow.append(document.createTextNode(` Level ${rec.level} `));
  const st = DB.store.items[rid];
  chipRow.appendChild(el("span", "chip chip-new", st ? stageName(st.stage) : "Not started"));
  id.appendChild(chipRow);
  const card = DB.cardsById.get(rid + ":meaning");
  id.appendChild(el("h2", null, (card && card.answers[0]) || (ref.meanings[0] || "")));
  const rows = rec.type === "kanji" && readingRows(rec);
  if (rows) id.appendChild(rows);
  else if ((ref.readings || []).length) id.appendChild(el("div", "rd", ref.readings.join(" · ")));
  const audioList = (rec.audio && rec.audio.length) ? rec.audio : ((DB.cardsById.get(rid + ":reading") && DB.cardsById.get(rid + ":reading").audio) || []);
  const kana = rec.type === "kanji" ? (rec.teach && rec.teach.reading) || "" : (ref.readings || [])[0] || "";
  if (audioList.length || (kana && canSpeak)) {
    const r = el("div", "btn-row");
    r.appendChild(audioButton(audioList, kana));
    id.appendChild(r);
  }
  head.append(glyph, id);
  p.appendChild(head);

  // Mnemonics & hints from own/
  const mc = DB.cardsById.get(`${rid}:meaning`);
  const rc = DB.cardsById.get(`${rid}:reading`);
  const hasMnemonic = (mc && (mc.mnemonic_meaning || mc.hint)) || (rc && (rc.mnemonic_reading || rc.hint));
  if (hasMnemonic) {
    p.appendChild(el("div", "sec-h", "Mnemonics"));
    if (mc && (mc.mnemonic_meaning || mc.hint)) {
      if (rc && mc.mnemonic_meaning) p.appendChild(el("div", "sec-h", "Meaning mnemonic"));
      if (mc.mnemonic_meaning) renderText(p, mc.mnemonic_meaning, termsFor(rid, "meaning"));
      if (mc.hint) addHint(p, mc.hint, termsFor(rid, "meaning"));
    }
    if (rc && (rc.mnemonic_reading || rc.hint)) {
      if (rc.mnemonic_reading) p.appendChild(el("div", "sec-h", "Reading mnemonic"));
      if (rc.mnemonic_reading) renderText(p, rc.mnemonic_reading, termsFor(rid, "reading"));
      if (rc.hint) addHint(p, rc.hint, termsFor(rid, "reading"));
    }
  }

  // Sentences
  if (rec.sentences && rec.sentences.length) {
    p.appendChild(el("div", "sec-h", "Context"));
    renderSentences(p, rec.sentences, 9);
  }

  // Composition
  if (rec.type !== "radical") {
    partChips(p, rec.type === "kanji" ? "Built from these radicals" : "Built from these kanji", rec, true, true);
  } else {
    const found = DB.index.filter((r) => r.type === "kanji" && (r.requires || []).includes(rid)).slice(0, 20).map((r) => r.id);
    if (found.length) partChips(p, "Found in kanji", found, false, true);
  }
  if (rec.type === "kanji") {
    const foundVocab = DB.index.filter((r) => r.type === "vocabulary" && (r.requires || []).includes(rid)).slice(0, 20).map((r) => r.id);
    if (foundVocab.length) partChips(p, "Found in vocabulary", foundVocab, false, true);
  }
  // Resurrect, only when burned.
  if (st && st.stage >= 9) {
    const row = el("div", "btn-row");
    const un = el("button", "btn btn-ghost btn-sm", "Resurrect this item");
    un.type = "button";
    un.addEventListener("click", () => {
      // Read at click time: a pull may have replaced DB.store since render.
      const cur = DB.store.items[rid];
      if (!cur || cur.stage < 9) return render();
      const now = Date.now();
      DB.store.items[rid] = { ...resurrect(cur, now), at: now };
      saveStore();
      updateBadge();
      render();
    });
    row.appendChild(un);
    p.appendChild(row);
  }
  v.appendChild(p);
}

// ---------- progress ----------
function renderProgress(v) {
  setNav("progress");
  document.body.classList.remove("focus");
  const items = DB.store.items;
  const days = DB.store.days;
  const today = todayKey();
  const s = DB.store.settings;
  v.appendChild(el("h1", null, "Progress"));
  // Where you are, what comes next, where the pace leads: in that order.
  levelBar(v, DB.store.level, kanjiProgress(DB.index, items, DB.store.level));
  const f = forecast(items, Date.now());
  const coming = el("p", "next-review", `${f.now} review${f.now === 1 ? "" : "s"} ready now · ${f.day} within 24 hours · ${f.week} this week`);
  v.appendChild(coming);
  if (!f.now) {
    const nr = nextReviewLine();
    if (nr) v.appendChild(el("p", "small muted", nr));
  }
  const pr = projection();
  const exam = pr.toExam >= 0 ? `Exam in ${pr.toExam} day${pr.toExam === 1 ? "" : "s"}.` : "Exam date passed.";
  v.appendChild(el("p", "sub", pr.pace > 0
    ? `${exam} At ${pr.pace.toFixed(1)} lessons a day (your two-week average) you'd reach level ${pr.level} by then${pr.level60 ? ` and level 60 around ${pr.level60}` : ""}.`
    : `${exam} Do a few lessons and this shows where your pace leads.`));
  const left = cumulative()[maxLevel()] - Object.keys(items).length;
  if (pr.toExam > 0 && left > 0 && pr.level < maxLevel()) {
    v.appendChild(el("p", "small muted", `All ${maxLevel()} levels by then takes about ${Math.ceil(left / pr.toExam)} lessons a day. Lessons per day is in Settings.`));
  }
  // Year heatmap ending on the exam date, clamped so at least a month of
  // history and today stay in view (today once the exam has passed).
  const toExam = daysBetween(today, s.examDate);
  const end = toExam > 0 ? (toExam > 334 ? shiftKey(today, 334) : s.examDate) : today;
  const start = shiftKey(end, -364);
  const grid = el("div", "heatmap");
  grid.setAttribute("role", "img");
  grid.setAttribute("aria-label", `Study days from ${start} to ${end}`);
  const [y, m, d] = start.split("-").map(Number);
  for (let i = 0; i < new Date(y, m - 1, d).getDay(); i++) grid.appendChild(el("span", "hm hm-pad"));
  for (let k = start; k <= end; k = shiftKey(k, 1)) {
    const r = days[k];
    const c = el("span", "hm");
    if (k > today) c.classList.add("hm-future");
    else if (r && r.done) c.classList.add("hm-done");
    else if (r && r.r + r.l > 0) c.classList.add("hm-part");
    else if (r && r.freeze) c.classList.add("hm-freeze");
    if (k === today) c.classList.add("hm-today");
    c.title = r ? `${k}: ${r.r} reviews, ${r.l} lessons${r.done ? ", done" : r.freeze ? ", frozen" : ""}` : k;
    grid.appendChild(c);
  }
  v.appendChild(grid);
  const legend = el("p", "small muted hm-legend");
  for (const [cls, lbl] of [["hm-done", "done"], ["hm-part", "some"], ["hm-freeze", "frozen"], ["hm-future", "ahead"]]) {
    legend.append(el("span", `hm ${cls}`), document.createTextNode(` ${lbl}  `));
  }
  v.appendChild(legend);
  streakStrip(v);
  v.appendChild(el("h2", null, "Items"));
  const counts = stageCounts(items);
  const all = Object.values(items);
  const grid2 = el("div", "stat-grid");
  for (const [n, lbl] of [
    [counts.apprentice, "Apprentice"], [counts.guru, "Guru"], [counts.master, "Master"], [counts.enlightened, "Enlightened"], [counts.burned, "Burned"],
    [all.length, "started"], [all.filter((x) => x.passed > 0).length, "passed Guru"],
    [DB.index.filter((r) => r.type === "kanji" && items[r.id] && items[r.id].passed > 0).length, "kanji passed"],
  ]) {
    const srs = ["Apprentice", "Guru", "Master", "Enlightened", "Burned"].includes(lbl);
    const st = el("div", srs ? `stat stat-${lbl.toLowerCase()}` : "stat");
    st.append(el("b", null, String(n)), el("span", null, lbl));
    grid2.appendChild(st);
  }
  v.appendChild(grid2);
}

// ---------- settings ----------
function renderSettings(v) {
  setNav("today");
  document.body.classList.remove("focus");
  const s = DB.store.settings;
  const p = el("div", "panel narrow settings");
  p.appendChild(el("h1", null, "Settings"));
  const inputs = {};
  const field = (key, label, make) => {
    const l = el("label", null, label);
    l.htmlFor = `set-${key}`;
    const i = make();
    i.id = `set-${key}`;
    inputs[key] = i;
    p.append(l, i);
  };
  const number = (key, label, min, max) => field(key, label, () => {
    const i = document.createElement("input");
    i.type = "number";
    i.min = String(min);
    i.max = String(max);
    i.value = String(s[key]);
    return i;
  });
  const check = (key, label) => field(key, label, () => {
    const i = document.createElement("input");
    i.type = "checkbox";
    i.checked = !!s[key];
    return i;
  });
  const R = Store.RANGES;
  number("reviewsPerDay", "Reviews a day", ...R.reviewsPerDay);
  number("lessonsPerDay", "Lessons a day", ...R.lessonsPerDay);
  number("batch", "Lesson batch size (3 to 10)", ...R.batch);
  number("apprenticeCap", "Pause lessons above this many Apprentice items (0 never pauses)", ...R.apprenticeCap);
  field("order", "Review order", () => {
    const sel = document.createElement("select");
    for (const [val, lbl] of [["lowStage", "Lowest stage first"], ["shuffled", "Shuffled (WaniKani default)"], ["apprenticeFirst", "Apprentice first"], ["lowLevel", "Lower levels first"]]) {
      const o = document.createElement("option");
      o.value = val;
      o.textContent = lbl;
      if (s.order === val) o.selected = true;
      sel.appendChild(o);
    }
    return sel;
  });
  check("backToBack", "Ask an item's meaning and reading back to back");
  check("autostart", "Open straight into the session");
  field("examDate", "Exam date", () => {
    const i = document.createElement("input");
    i.type = "date";
    i.value = s.examDate;
    return i;
  });
  const row = el("div", "btn-row");
  const save = el("button", "btn btn-primary", "Save");
  save.type = "button";
  save.addEventListener("click", () => {
    const s = DB.store.settings; // not the render-time object: a pull may have replaced the store
    const clamp = (key) => {
      const i = inputs[key];
      const n = parseInt(i.value, 10);
      if (!Number.isNaN(n)) s[key] = Math.max(Number(i.min), Math.min(Number(i.max), n));
    };
    for (const key of ["reviewsPerDay", "lessonsPerDay", "batch", "apprenticeCap"]) clamp(key);
    s.order = inputs.order.value;
    s.backToBack = inputs.backToBack.checked;
    s.autostart = inputs.autostart.checked;
    if (/^\d{4}-\d{2}-\d{2}$/.test(inputs.examDate.value)) s.examDate = inputs.examDate.value;
    DB.store.settingsAt = Date.now();
    saveStore();
    location.hash = "#/today";
  });
  row.append(save, link("#/today", "Cancel", "btn btn-ghost"));
  p.appendChild(row);
  const lic = el("p", "small muted");
  lic.appendChild(link("#/licenses", "Licences", "linklike"));
  p.appendChild(lic);
  v.appendChild(p);
}

// ---------- account ----------
// Email → eight-digit code → signed-in panel. Every call goes through sync.js;
// this file renders and maps the API's error codes to sentences.
let syncNotice = ""; // one line from sync.js, shown on the next Today or Account paint
let syncStart = Promise.resolve(); // the boot probe; Account waits for it
const API_TEXT = {
  invalid_email: "Enter a valid email address.",
  invalid_code: "That code didn't work. Check it, or send a new one.",
  too_many_requests: "Too many attempts. Wait a few minutes and try again.",
  csrf: "The request was blocked. Reload the page and try again.",
  network: "Couldn't reach the server. Check your connection.",
  login_required: "Sign in first.",
  google_failed: "Google sign-in didn't finish. Try again, or use the email code.",
  google_cancelled: "Google sign-in was cancelled.",
  google_email: "That Google account's address can't be confirmed by Google. Use the email code instead.",
  google_unavailable: "Google sign-in isn't available here. Use the email code.",
  not_invited: "Kanjimo is invite-only, and this address has no invite.",
  forbidden: "Admins only.",
  already_member: "That address already has an account.",
  already_invited: "That address is already invited.",
  self: "You can't do that to your own account.",
};
// The online version is invite-only: signed out, only Account and Licences open.
const signedOutOnline = () => Sync.status().mode === "anon";
function apiText(e) {
  if (e && e.status === 401) return API_TEXT.login_required;
  return API_TEXT[e && e.error] || "Something went wrong. Try again.";
}
const onToday = () => ["", "#/", "#/today"].includes(location.hash);
function button(label, cls, onClick) {
  const b = el("button", cls, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}
function textInput(parent, id, type, label) {
  const l = el("label", null, label);
  l.htmlFor = id;
  const i = document.createElement("input");
  i.type = type;
  i.id = id;
  parent.append(l, i);
  return i;
}
// Runs an API call behind a button: disabled while it runs, the mapped
// error under it when it fails.
async function guarded(btn, msg, fn) {
  btn.disabled = true;
  msg.textContent = "";
  try {
    await fn();
  } catch (e) {
    msg.textContent = apiText(e);
    btn.disabled = false;
  }
}
function panelReset(p) {
  p.textContent = "";
  p.appendChild(el("h1", null, "Account"));
}
async function renderAccount(v, query) {
  setNav("account");
  document.body.classList.remove("focus");
  const token = paneToken;
  await syncStart;
  if (token !== paneToken) return; // navigated away while the probe ran
  const p = el("div", "panel narrow account");
  panelReset(p);
  v.appendChild(p);
  const mode = Sync.status().mode;
  if (mode === "off") {
    p.appendChild(el("p", "muted", "Sync and accounts need the online version. This copy runs from your own files, and progress stays in this browser."));
    return;
  }
  if (mode === "down") {
    p.appendChild(el("p", "muted", `${API_TEXT.network} Progress keeps saving in this browser.`));
    return;
  }
  if (syncNotice) {
    toast(v, syncNotice);
    syncNotice = "";
  }
  if (mode === "on") await renderSignedIn(p);
  else renderSignIn(p, "", API_TEXT[query.get("login")] || "");
  const legal = el("p", "small muted");
  legal.append(link("../legal/terms.html", "Terms", "linklike"), " · ",
    link("../legal/privacy.html", "Privacy", "linklike"));
  p.appendChild(legal);
}
function renderSignIn(p, addr = "", notice = "") {
  const google = el("div", "btn-row");
  google.appendChild(link("/api/auth/google/start", "Continue with Google", "btn btn-primary"));
  p.append(google, el("p", "muted", "Or use your email. An eight-digit code arrives by mail; there is no password. Kanjimo is invite-only."));
  const email = textInput(p, "acc-email", "email", "Email");
  email.autocomplete = "email";
  email.value = addr;
  const msg = el("p", "small muted", notice);
  const send = button("Send code", "btn btn-primary", () => {
    const a = email.value.trim();
    if (!a || !email.checkValidity()) {
      msg.textContent = API_TEXT.invalid_email;
      return;
    }
    guarded(send, msg, async () => {
      await Sync.api.code(a);
      panelReset(p);
      renderCode(p, a);
    });
  });
  email.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      send.click();
    }
  });
  const row = el("div", "btn-row");
  row.appendChild(send);
  p.append(row, msg);
}
function renderCode(p, addr) {
  p.appendChild(el("p", "muted", `If ${addr} has an invite, a code is on its way. It works for ten minutes.`));
  const code = textInput(p, "acc-code", "text", "Code");
  code.className = "code";
  code.inputMode = "numeric";
  code.autocomplete = "one-time-code";
  code.maxLength = 8;
  const msg = el("p", "small muted");
  const verify = button("Sign in", "btn btn-primary", () => {
    const c = code.value.trim();
    if (!/^\d{8}$/.test(c)) {
      msg.textContent = "Enter the eight digits from the mail.";
      return;
    }
    guarded(verify, msg, async () => {
      await Sync.api.verify(addr, c);
      if (DB.loadError) await reloadData(); // the data waited behind the login
      render();
    });
  });
  code.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      verify.click();
    }
  });
  const again = button("Use another email", "btn btn-ghost", () => {
    panelReset(p);
    renderSignIn(p, addr);
  });
  const row = el("div", "btn-row");
  row.append(verify, again);
  p.append(row, msg);
  code.focus();
}
async function renderSignedIn(p) {
  let acct;
  try {
    acct = await Sync.api.me();
  } catch (e) {
    if (!p.isConnected) return; // a newer render cleared the view
    if (e.status === 401) return renderSignIn(p);
    p.appendChild(el("div", "feedback bad", apiText(e)));
    return;
  }
  if (!p.isConnected) return;
  p.appendChild(el("p", null, `Signed in as ${acct.user.email}`));
  if (acct.user.admin) p.appendChild(link("#/admin", "Admin: invites and accounts", "linklike"));
  const msg = el("p", "small muted");
  const out = el("div", "btn-row");
  const lo = button("Log out", "btn btn-ghost btn-sm", () => guarded(lo, msg, async () => {
    await Sync.api.logout(false);
    render();
  }));
  const la = button("Log out everywhere", "btn btn-ghost btn-sm", () => guarded(la, msg, async () => {
    await Sync.api.logout(true);
    render();
  }));
  out.append(lo, la);
  p.append(out, msg);
  const del = el("div", "danger");
  del.appendChild(el("div", "sec-h", "Delete account"));
  del.appendChild(el("p", "small muted", "Removes your account and the progress stored on the server. Progress saved in this browser stays. Type delete to confirm."));
  const confirm = textInput(del, "acc-delete", "text", "Confirmation");
  confirm.autocomplete = "off";
  const dmsg = el("p", "small muted");
  const db = button("Delete account", "btn btn-ghost btn-sm btn-danger", () => {
    if (confirm.value.trim() !== "delete") {
      dmsg.textContent = "Type delete to confirm.";
      return;
    }
    guarded(db, dmsg, async () => {
      await Sync.api.remove();
      syncNotice = "Account deleted. Progress on this device is kept.";
      render();
    });
  });
  const drow = el("div", "btn-row");
  drow.appendChild(db);
  del.append(drow, dmsg);
  p.appendChild(del);
}
// ---------- admin ----------
function when(iso) {
  return iso ? new Date(iso).toLocaleDateString() : "never";
}
async function renderAdmin(v) {
  setNav("account");
  document.body.classList.remove("focus");
  const token = paneToken;
  const p = el("div", "panel narrow account");
  v.appendChild(p);
  p.appendChild(el("h1", null, "Admin"));
  let data;
  try {
    data = await Sync.api.admin.list();
  } catch (e) {
    if (token !== paneToken) return;
    p.appendChild(el("div", "feedback bad", apiText(e)));
    p.appendChild(link("#/account", "← Account", "linklike"));
    return;
  }
  if (token !== paneToken) return;
  const refresh = () => render();

  p.appendChild(el("div", "sec-h", "Invite"));
  p.appendChild(el("p", "small muted", "The address gets a mail with the sign-in link. Its first sign-in creates the account."));
  const email = textInput(p, "adm-email", "email", "Email");
  email.autocomplete = "off";
  const msg = el("p", "small muted");
  const send = button("Send invite", "btn btn-primary", () => {
    if (!email.value.trim() || !email.checkValidity()) {
      msg.textContent = API_TEXT.invalid_email;
      return;
    }
    guarded(send, msg, async () => {
      const r = await Sync.api.admin.invite(email.value.trim());
      syncNotice = r.mailed ? `Invited ${r.email}.` : `Invited ${r.email}, but the mail failed. Tell them directly.`;
      refresh();
    });
  });
  email.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      send.click();
    }
  });
  const row = el("div", "btn-row");
  row.appendChild(send);
  p.append(row, msg);
  if (syncNotice) {
    toast(v, syncNotice);
    syncNotice = "";
  }

  p.appendChild(el("div", "sec-h", `Pending invites (${data.invites.length})`));
  for (const inv of data.invites) {
    const line = el("div", "btn-row");
    const imsg = el("span", "small muted");
    const rv = button("Revoke", "btn btn-ghost btn-sm", () => guarded(rv, imsg, async () => {
      await Sync.api.admin.revoke(inv.email);
      refresh();
    }));
    line.append(el("span", null, `${inv.email} · ${when(inv.created_at)}`), rv, imsg);
    p.appendChild(line);
  }

  p.appendChild(el("div", "sec-h", `Accounts (${data.users.length})`));
  const me = Sync.user();
  for (const u of data.users) {
    const box = el("div", "hint");
    const tags = [u.admin ? "admin" : "", u.disabled_at ? "disabled" : ""].filter(Boolean).join(", ");
    box.appendChild(el("p", null, u.email + (tags ? ` (${tags})` : "")));
    box.appendChild(el("p", "small muted", `Joined ${when(u.created_at)} · last seen ${when(u.last_seen_at)}`));
    if (!me || me.user.id !== u.id) {
      const umsg = el("span", "small muted");
      const tg = button(u.disabled_at ? "Enable" : "Disable", "btn btn-ghost btn-sm", () => guarded(tg, umsg, async () => {
        await Sync.api.admin.setDisabled(u.id, !u.disabled_at);
        refresh();
      }));
      // Two clicks: the first arms the button, the second deletes.
      const dl = button("Delete", "btn btn-ghost btn-sm btn-danger", () => {
        if (dl.textContent === "Delete") {
          dl.textContent = "Confirm delete";
          return;
        }
        guarded(dl, umsg, async () => {
          await Sync.api.admin.remove(u.id);
          refresh();
        });
      });
      const ur = el("div", "btn-row");
      ur.append(tg, dl, umsg);
      box.appendChild(ur);
    }
    p.appendChild(box);
  }
  p.appendChild(link("#/account", "← Account", "linklike"));
}

// Data that waited behind a login: fetched again once the session exists.
async function reloadData() {
  DB.loadError = null;
  await bootData();
  autostarted = true;
  updateBadge();
}

// ---------- licences ----------
async function renderLicenses(v) {
  setNav("");
  document.body.classList.remove("focus");
  const p = el("div", "panel narrow");
  p.appendChild(el("h1", null, "Licences"));
  let data = null;
  try {
    data = await fetchJson("../data/ATTRIBUTION.json", "ATTRIBUTION.json");
  } catch {
    // 404 or fetch failure: personal copy
  }
  if (!data) {
    p.appendChild(el("p", "prose", "Personal copy built from your own data. Not for distribution."));
    p.appendChild(link("#/today", "← Today", "linklike"));
    v.appendChild(p);
    return;
  }
  if (Array.isArray(data.attribution)) {
    p.appendChild(el("div", "sec-h", "Attribution"));
    for (const line of data.attribution) {
      const para = el("p", "prose");
      const parts = line.split(/(https?:\/\/[^\s,)]+)/);
      for (const pt of parts) {
        if (/^https?:\/\//.test(pt)) para.appendChild(link(pt, pt, "linklike"));
        else para.appendChild(document.createTextNode(pt));
      }
      p.appendChild(para);
    }
  }
  if (data.sources && typeof data.sources === "object") {
    p.appendChild(el("div", "sec-h", "Sources"));
    for (const [key, s] of Object.entries(data.sources)) {
      const box = el("div", "hint");
      box.appendChild(el("div", "sec-h", key));
      if (s.holder) box.appendChild(el("p", "small muted", `Holder: ${s.holder}`));
      if (s.license) box.appendChild(el("p", "small muted", `Licence: ${s.license}`));
      if (s.version) box.appendChild(el("p", "small muted", `Version: ${s.version}`));
      if (s.url) {
        const lp = el("p", "small");
        lp.appendChild(link(s.url, s.url, "linklike"));
        box.appendChild(lp);
      }
      p.appendChild(box);
    }
  }
  p.appendChild(link("#/today", "← Today", "linklike"));
  v.appendChild(p);
}

// ---------- router + boot ----------
let autostarted = false; // once per page load, so Today stays reachable
async function render() {
  document.onkeydown = null;
  // Leaving mid-session ends it like End early: completed items are saved,
  // the day's done flag is settled, the wrap-up is skipped.
  if (session && !location.hash.startsWith("#/review")) closeSession();
  const token = ++paneToken;
  await syncStart;
  if (token !== paneToken) return; // a newer render took over while the probe ran
  if (signedOutOnline() && !/^#\/(account|licenses)\b/.test(location.hash)) {
    location.hash = "#/account";
    return;
  }
  const v = clearView();
  const hash = location.hash || "#/today";
  if (hash === "#/licenses") return renderLicenses(v);
  if (hash === "#/admin") return renderAdmin(v);
  const mAccount = hash.match(/^#\/account(?:\?(.*))?$/);
  if (!DB.ready) {
    // Account works before the data does: on the online version the data
    // itself may be waiting behind the login.
    if (mAccount) return renderAccount(v, new URLSearchParams(mAccount[1] || ""));
    const s = el("div", "panel narrow");
    if (DB.loadError && DB.loadError.kind === "login") {
      s.appendChild(el("p", "prose", "Sign in to load the study data."));
      s.appendChild(link("#/account", "Account", "btn btn-primary"));
    } else s.appendChild(el("div", "skeleton", null));
    v.appendChild(s);
    return;
  }
  updateBadge();
  if ((hash === "#/today" || hash === "#/") && !autostarted) {
    autostarted = true;
    if (DB.store.settings.autostart && Object.keys(DB.store.items).length
        && (storeStatus === "ok" || storeStatus === "fresh") && !saveFailed
        && !(DB.store.days[todayKey()] && DB.store.days[todayKey()].done)
        && (dueItems(DB.store.items, Date.now()).length || lessonsReady().length)) {
      location.hash = "#/review";
      return;
    }
  }
  const mBand = hash.match(/^#\/browse\/(\d+)-(\d+)$/);
  const mItem = hash.match(/^#\/item\/(.+)$/);
  const mSearch = hash.match(/^#\/search(?:\?(.*))?$/);
  try {
    if (hash === "#/today" || hash === "#/") renderToday(v);
    else if (hash === "#/review") {
      if (session) renderPrompt(v);
      else await startSession(v);
    } else if (hash === "#/progress") renderProgress(v);
    else if (hash === "#/settings") renderSettings(v);
    else if (hash === "#/licenses") await renderLicenses(v);
    else if (mAccount) await renderAccount(v, new URLSearchParams(mAccount[1] || ""));
    else if (hash === "#/browse") renderBrowse(v);
    else if (mBand) renderBand(v, parseInt(mBand[1], 10), parseInt(mBand[2], 10));
    else if (mSearch) {
      const q = new URLSearchParams(mSearch[1] || "").get("q") || "";
      renderSearch(v, q);
    } else if (mItem) await renderItem(v, decodeURIComponent(mItem[1]));
    else {
      const p = el("div", "panel narrow");
      p.appendChild(el("p", "prose", "That page doesn't exist."));
      p.appendChild(link("#/today", "← Today", "linklike"));
      v.appendChild(p);
    }
  } catch (e) {
    if (e && e.kind) errorPanel(v, e, () => render()); // fetch, parse, login, limit
    else throw e;
  }
  // Move focus to the new content unless a view already placed it (answer
  // box, search field): typing must work without a click.
  if (!view().contains(document.activeElement)) view().focus({ preventScroll: true });
}

function initTheme() {
  let theme = "light";
  try {
    theme = localStorage.getItem(THEME_KEY) || "light";
  } catch { /* ignore */ }
  const btn = document.getElementById("themeBtn");
  const paint = () => {
    if (theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
    btn.textContent = theme === "dark" ? "Light" : "Dark";
  };
  btn.addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch { /* ignore */ }
    paint();
  });
  paint();
}

async function boot() {
  try {
    storage = window.localStorage;
  } catch {
    storage = null;
  }
  const got = Store.load(storage, Date.now());
  DB.store = got.store;
  storeStatus = got.status === "migrated-v3" ? "ok" : got.status; // v4 only adds change stamps: nothing to tell
  settle(DB.store.days, todayKey());
  if (storeStatus !== "readonly") saveStore();
  initTheme();
  initImport();
  // Resilient routing: hashchange + popstate cover real navigations; a cheap
  // same-hash poll self-heals when the browser fails to deliver those events
  // (observed in a long-lived Edge tab). Triggers coalesce into one render.
  let lastHash = location.hash;
  let renderQueued = false;
  const requestRender = () => {
    lastHash = location.hash;
    if (renderQueued) return;
    renderQueued = true;
    Promise.resolve().then(() => {
      renderQueued = false;
      render();
    });
  };
  // One hash navigation fires popstate and hashchange in separate tasks, so
  // the microtask above can't merge them; a second pass would let an async
  // view (licences, item, account) append its panel twice.
  const onNavigate = () => {
    if (location.hash !== lastHash) requestRender();
  };
  window.addEventListener("hashchange", onNavigate);
  window.addEventListener("popstate", onNavigate);
  setInterval(() => {
    if (location.hash !== lastHash) requestRender();
  }, 250);
  // Sync wiring: store.js keeps the only hands on localStorage, sync.js the
  // only ones on /api/*; a pulled copy is saved without queueing a push.
  Sync.init({
    getStore: () => DB.store,
    setStore: (s) => {
      DB.store = s;
      settle(DB.store.days, todayKey());
      persist();
      updateBadge();
    },
    backup: (s) => Store.backup(storage, s),
    loadSync: () => Store.loadSync(storage),
    saveSync: (s) => Store.saveSync(storage, s),
    notify: (text) => {
      syncNotice = text;
      if (!session && onToday()) requestRender();
    },
  });
  syncStart = Sync.start();
  // A probe that met an outage tries again on wake and on reconnect.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) Sync.flush();
    else {
      syncStart = Sync.retry();
      syncStart.then(() => Sync.pull());
    }
  });
  window.addEventListener("online", () => { syncStart = Sync.retry(); });
  window.addEventListener("pagehide", () => Sync.flush());
  try {
    await bootData();
  } catch (e) {
    DB.loadError = e;
    const v = clearView();
    errorPanel(v, e, () => location.reload());
    return;
  }
  // Autostart belongs to opening the app, not to a later click on Today.
  autostarted = !["", "#/", "#/today"].includes(location.hash);
  updateBadge();
  await render();
}
boot();
