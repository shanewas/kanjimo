// Cross-tab tests: two tabs over one shared storage, convergence, settings,
// echo safety, mid-session deferral. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import * as Tabs from "../app/tabs.js";
import { DEFAULT_SETTINGS, KEY, fresh } from "../app/store.js";

const NOW = new Date(2026, 9, 9, 9).getTime();

function store(items = {}, extra = {}) {
  const s = { ...fresh(), ...extra };
  for (const [rid, [stage, at]] of Object.entries(items)) {
    s.items[rid] = { stage, due: at + 10, lapses: 0, started: at, passed: 0, burned: 0, at };
  }
  return s;
}
const clone = (s) => JSON.parse(JSON.stringify(s));

// One shared storage behind two tabs. tabs.js is a singleton per tab in the
// browser (one module instance per realm), so delivering an event here
// re-inits it with the receiving tab's hooks, as sync.test.js does.
function world() {
  const m = new Map();
  const shared = {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
  };
  const make = (local) => {
    const tab = { local, sets: [], refreshes: 0, inSession: false };
    // setStore stands in for app.js: adopt the store and persist it, which
    // is the write the other tab's listener then sees.
    tab.hooks = {
      getStore: () => tab.local,
      setStore: (s) => { tab.local = s; tab.sets.push(s); shared.setItem(KEY, JSON.stringify(s)); },
      now: () => NOW,
      inSession: () => tab.inSession,
      refresh: () => { tab.refreshes += 1; },
    };
    return tab;
  };
  const save = (tab) => { shared.setItem(KEY, JSON.stringify(tab.local)); return shared.getItem(KEY); };
  let active = null; // the tab whose realm the singleton currently stands in for
  const deliver = (tab, raw) => {
    if (active !== tab) { Tabs.init(tab.hooks); active = tab; }
    return Tabs.onStorage({ key: KEY, newValue: raw });
  };
  return { shared, make, save, deliver };
}

// A grade as gradeCurrent writes it: a new stage under a fresh `at` stamp.
function grade(tab, rid, stage, at) {
  tab.local.items[rid] = { ...tab.local.items[rid], stage, due: at + 10, at };
}

describe("two tabs", () => {
  it("converge with both grades kept when a stale tab saves over the other", () => {
    const { shared, make, save, deliver } = world();
    const base = store({ a: [2, 10], b: [2, 10], c: [2, 10] });
    const A = make(clone(base));
    const B = make(clone(base));

    grade(A, "a", 3, 100);
    const aWrite = save(A);
    grade(B, "b", 4, 200); // B never saw A's write; its save clobbers it
    save(B);
    assert.equal(JSON.parse(shared.getItem(KEY)).items.a.stage, 2, "the stale save really did clobber");

    assert.equal(deliver(B, aWrite), true);
    assert.equal(B.local.items.a.stage, 3, "A's grade merged in");
    assert.equal(B.local.items.b.stage, 4, "B's own grade kept");
    assert.equal(B.local.items.c.stage, 2);
    assert.equal(B.sets.length, 1, "the merged result is written back once");
    assert.equal(B.refreshes, 1);

    assert.equal(deliver(A, shared.getItem(KEY)), true);
    assert.equal(A.local.items.a.stage, 3);
    assert.equal(A.local.items.b.stage, 4, "B's grade reached A");
    assert.deepEqual(A.local.items, B.local.items);
    assert.deepEqual(JSON.parse(shared.getItem(KEY)).items, B.local.items);
  });

  it("a settings change in one tab reaches the other", () => {
    const { make, save, deliver } = world();
    const A = make(store({}));
    const B = make(store({}));
    A.local.settings = { ...DEFAULT_SETTINGS, reviewsPerDay: 99 };
    A.local.settingsAt = 300;
    assert.equal(deliver(B, save(A)), true);
    assert.equal(B.local.settings.reviewsPerDay, 99);
    assert.equal(B.local.settingsAt, 300);
    assert.equal(B.refreshes, 1);
  });

  it("an echo of a tab's own converged write rewrites nothing", () => {
    const { shared, make, save, deliver } = world();
    const A = make(store({ a: [2, 10] }));
    const B = make(store({ a: [2, 10] }));
    grade(A, "a", 3, 100);
    deliver(B, save(A));
    const merged = shared.getItem(KEY);
    const sets = B.sets.length;
    assert.equal(deliver(B, merged), false, "merging the state it already has is a no-op");
    assert.equal(deliver(A, merged), false);
    assert.equal(B.sets.length, sets, "no write, so the other tab is not woken again");
    assert.equal(B.refreshes, 1, "only the real change repainted");
    assert.equal(shared.getItem(KEY), merged);
  });

  it("ignores other keys, removals and damaged payloads", () => {
    const { make } = world();
    const B = make(store({ a: [2, 10] }));
    Tabs.init(B.hooks);
    assert.equal(Tabs.onStorage({ key: "jstudy.theme", newValue: "dark" }), false);
    assert.equal(Tabs.onStorage({ key: KEY, newValue: null }), false);
    assert.equal(Tabs.onStorage({ key: KEY, newValue: "{not json" }), false);
    assert.equal(Tabs.onStorage(null), false);
    assert.equal(B.sets.length, 0);
    assert.equal(B.refreshes, 0);
    assert.equal(Tabs.hasPending(), false);
  });

  it("holds an external write during a session, then merges around the local grade", () => {
    const { make, save, deliver } = world();
    const session = {
      startedAt: NOW - 1000, prompts: [{ rid: "x", part: "meaning" }], pos: 0,
      progress: { x: { need: 1, done: 0, missM: 1, missR: 0 } }, completed: 0,
    };
    const B = make(store({ x: [2, 10], y: [2, 10] }, { session }));
    B.inSession = true;
    const A = make(store({ x: [5, 500], y: [3, 500], z: [1, 500] }));
    const before = clone(B.local);

    assert.equal(deliver(B, save(A)), true, "accepted, but deferred");
    assert.deepEqual(B.local, before, "nothing under the current card moved");
    assert.equal(B.sets.length, 0);
    assert.equal(B.refreshes, 0);
    assert.equal(Tabs.hasPending(), true);
    assert.equal(Tabs.applyPending(), false, "still in session: nothing applies early");

    grade(B, "x", 3, 600); // the in-flight item is graded from the pre-merge state
    B.inSession = false;
    assert.equal(Tabs.applyPending(), true);
    assert.equal(Tabs.hasPending(), false);
    assert.equal(B.local.items.x.stage, 3, "the local grade stands, not the other tab's stage 5");
    assert.equal(B.local.items.x.at, 600);
    assert.equal(B.local.items.y.stage, 3, "the rest of the external write merged in");
    assert.equal(B.local.items.z.stage, 1);
    assert.equal(B.local.session.progress.x.missM, 1, "session progress was never rewritten");
    assert.equal(B.sets.length, 1);
    assert.equal(B.refreshes, 0, "applying at session end does not repaint; the caller does");
    assert.equal(Tabs.applyPending(), false, "nothing left pending");
  });

  it("folds several writes that land during one session into the pending merge", () => {
    const { make, save, deliver } = world();
    const B = make(store({ x: [2, 10] }));
    B.inSession = true;
    deliver(B, save(make(store({ y: [3, 500] }))));
    deliver(B, save(make(store({ z: [4, 600] }))));
    assert.deepEqual(Object.keys(B.local.items), ["x"]);
    B.inSession = false;
    assert.equal(Tabs.applyPending(), true);
    assert.deepEqual(Object.keys(B.local.items).sort(), ["x", "y", "z"]);
  });
});
