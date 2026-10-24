// Sync tests: backend detection, first login, debounce, 409 merge, backoff, keepalive. Run: node --test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import * as Sync from "../app/sync.js";
import { fresh } from "../app/store.js";

const NOW = new Date(2026, 9, 9, 9).getTime();
const TODAY_SESSION = { startedAt: NOW - 1000, prompts: [], pos: 0, progress: {}, completed: 0 };

function store(items = {}, extra = {}) {
  const s = { ...fresh(), ...extra };
  for (const [rid, [stage, at]] of Object.entries(items)) s.items[rid] = { stage, due: at + 10, lapses: 0, started: at, passed: 0, burned: 0, at };
  return s;
}
// A scripted fetch: each entry answers one request in order; an Error throws,
// and so does any request past the end of the script (a network failure).
// A function entry runs when the request goes out, then answers with its result.
function fakeFetch(script) {
  const calls = [];
  const f = async (url, init) => {
    calls.push({ url, init, body: init.body ? JSON.parse(init.body) : null });
    let r = script.length ? script.shift() : new TypeError("Failed to fetch");
    if (typeof r === "function") r = r();
    if (r instanceof Error) throw r;
    return { status: r.status, json: async () => { if (r.body === undefined) throw new Error("no body"); return r.body; } };
  };
  f.calls = calls;
  return f;
}
function timers() {
  const pending = [];
  let id = 0;
  return {
    delays: [], pending,
    setTimeout(fn, ms) { this.delays.push(ms); pending.push({ id: ++id, fn }); return id; },
    clearTimeout(i) { const k = pending.findIndex((p) => p.id === i); if (k >= 0) pending.splice(k, 1); },
    async fire() { const p = pending.shift(); if (p) await p.fn(); },
  };
}
function host(fetch, local, sync = { rev: 0, dirty: false, lastPullAt: 0, user: null }) {
  const t = timers();
  const log = { sets: [], notes: [], backups: [], sync: null, cur: local };
  Sync.init({
    fetch, setTimeout: t.setTimeout.bind(t), clearTimeout: t.clearTimeout.bind(t), now: () => NOW,
    getStore: () => log.cur, setStore: (s) => { log.cur = s; log.sets.push(s); }, backup: (s) => log.backups.push(s),
    loadSync: () => sync, saveSync: (s) => { log.sync = { ...s }; }, notify: (text) => log.notes.push(text),
  });
  return { t, log };
}
const ME = { status: 200, body: { user: { id: 1, email: "a@b.c" } } };
const puts = (f) => f.calls.filter((c) => c.init.method === "PUT");

describe("backend detection", () => {
  it("turns itself off on a 404 from /api/me and never calls the API again", async () => {
    const f = fakeFetch([{ status: 404 }]);
    const { t } = host(f, store({ x: [2, 5] }));
    assert.equal(await Sync.start(), "off");
    Sync.schedule();
    await Sync.flush();
    await Sync.pull(0);
    assert.equal(f.calls.length, 1);
    assert.equal(t.delays.length, 0);
    assert.equal(Sync.status().mode, "off");
  });

  it("treats a network error or a 5xx as an outage and probes again on retry", async () => {
    const f = fakeFetch([new TypeError("Failed to fetch"), { status: 503 }, ME, { status: 204 }]);
    host(f, store());
    assert.equal(await Sync.start(), "down");
    assert.equal(await Sync.retry(), "down");
    assert.equal(await Sync.retry(), "on");
    assert.equal(f.calls[3].url, "/api/progress", "a recovered probe pulls");
    assert.equal(await Sync.retry(), "on");
    assert.equal(f.calls.length, 4, "retry is a no-op once the probe has an answer");
  });

  it("does not retry after a 404", async () => {
    const f = fakeFetch([{ status: 404 }]);
    host(f, store());
    await Sync.start();
    assert.equal(await Sync.retry(), "off");
    assert.equal(f.calls.length, 1);
  });

  it("is anonymous on a 401 and signed in on a 200", async () => {
    host(fakeFetch([{ status: 401, body: { error: "login_required" } }]), store());
    assert.equal(await Sync.start(), "anon");
    const f = fakeFetch([ME, { status: 204 }]);
    host(f, store());
    assert.equal(await Sync.start(), "on");
    assert.equal(Sync.user().user.email, "a@b.c");
    assert.equal(f.calls[1].url, "/api/progress");
    assert.equal(f.calls[1].init.credentials, "same-origin");
    assert.equal(f.calls[1].init.headers["X-Requested-With"], "jstudy");
  });
});

describe("first login", () => {
  it("server empty and local has progress: pushes with If-Match 0", async () => {
    const f = fakeFetch([ME, { status: 204 }, { status: 200, body: { rev: 1 } }]);
    const { log } = host(f, store({ x: [2, 5] }));
    await Sync.start();
    const p = puts(f);
    assert.equal(p.length, 1);
    assert.equal(p[0].init.headers["If-Match"], '"0"');
    assert.equal(p[0].init.headers["Content-Type"], "application/json");
    assert.equal(p[0].body.store.items.x.stage, 2);
    assert.deepEqual(log.sync, { rev: 1, dirty: false, lastPullAt: NOW, user: 1 });
    assert.deepEqual(log.notes, ["Progress saved to your account."]);
  });

  it("server empty and local fresh: nothing to push", async () => {
    const f = fakeFetch([ME, { status: 204 }]);
    host(f, store());
    await Sync.start();
    assert.equal(puts(f).length, 0);
  });

  it("local fresh: takes the server copy without pushing", async () => {
    const server = store({ y: [4, 50] }, { level: 7 });
    const f = fakeFetch([ME, { status: 200, body: { rev: 3, store: server } }]);
    const { log } = host(f, store());
    await Sync.start();
    assert.equal(puts(f).length, 0);
    assert.equal(log.sets.length, 1);
    assert.equal(log.cur.items.y.stage, 4);
    assert.equal(log.cur.level, 7);
    assert.deepEqual(log.notes, ["Progress loaded from your account."]);
    assert.deepEqual(log.sync, { rev: 3, dirty: false, lastPullAt: NOW, user: 1 });
  });

  it("both sides have progress: merges, saves, pushes with the server rev", async () => {
    const server = store({ y: [4, 50] });
    const f = fakeFetch([ME, { status: 200, body: { rev: 3, store: server } }, { status: 200, body: { rev: 4 } }]);
    const { log } = host(f, store({ x: [2, 5] }));
    await Sync.start();
    const p = puts(f);
    assert.equal(p.length, 1);
    assert.equal(p[0].init.headers["If-Match"], '"3"');
    assert.deepEqual(Object.keys(p[0].body.store.items).sort(), ["x", "y"]);
    assert.deepEqual(log.notes, ["Progress merged with your account."]);
    assert.deepEqual(log.sync, { rev: 4, dirty: false, lastPullAt: NOW, user: 1 });
  });

  it("verify signs in and runs the same rules", async () => {
    const g = fakeFetch([{ status: 401 }, ME, { status: 204 }, { status: 200, body: { rev: 1 } }]);
    host(g, store({ x: [2, 5] }));
    await Sync.start();
    assert.equal(Sync.status().mode, "anon");
    await Sync.api.verify("a@b.c", "123456");
    assert.deepEqual(g.calls[1].body, { email: "a@b.c", code: "123456" });
    assert.equal(Sync.status().mode, "on");
    assert.equal(puts(g).length, 1);
    assert.equal(puts(g)[0].init.headers["If-Match"], '"0"');
  });
});

describe("push", () => {
  it("debounces 1.5 s after the last save and clears dirty on 200", async () => {
    const f = fakeFetch([ME, { status: 204 }, { status: 200, body: { rev: 1 } }]);
    const { t, log } = host(f, store());
    await Sync.start();
    Sync.schedule();
    Sync.schedule();
    assert.deepEqual(t.delays, [1500, 1500]);
    assert.equal(t.pending.length, 1, "the earlier timer was cleared");
    assert.equal(log.sync.dirty, true);
    await t.fire();
    assert.equal(puts(f).length, 1);
    assert.deepEqual(log.sync, { rev: 1, dirty: false, lastPullAt: NOW, user: 1 });
  });

  it("409: merges the returned copy, saves, retries once with the new rev", async () => {
    const server = store({ y: [4, 50], x: [1, 1] });
    const f = fakeFetch([ME, { status: 204 }, { status: 409, body: { rev: 7, store: server } }, { status: 200, body: { rev: 8 } }]);
    const { t, log } = host(f, store());
    await Sync.start();
    log.cur = store({ x: [2, 5] }, { session: TODAY_SESSION }); // the first local change after boot
    Sync.schedule();
    await t.fire();
    const p = puts(f);
    assert.equal(p.length, 2);
    assert.equal(p[0].init.headers["If-Match"], '"0"');
    assert.equal(p[1].init.headers["If-Match"], '"7"');
    assert.deepEqual(Object.keys(p[1].body.store.items).sort(), ["x", "y"]);
    assert.equal(p[1].body.store.items.x.stage, 2, "local x is newer");
    assert.equal(log.sets.length, 1);
    assert.equal(log.cur.items.y.stage, 4);
    assert.equal(log.cur.session, TODAY_SESSION, "today's session survives the merge");
    assert.deepEqual(log.notes, ["Progress merged from another device."]);
    assert.deepEqual(log.sync, { rev: 8, dirty: false, lastPullAt: NOW, user: 1 });
  });

  it("a second 409 gives up until the next save and keeps the first rev", async () => {
    const server = store({ y: [4, 50] });
    const f = fakeFetch([ME, { status: 204 }, { status: 409, body: { rev: 7, store: server } }, { status: 409, body: { rev: 9, store: server } }]);
    const { t, log } = host(f, store());
    await Sync.start();
    log.cur = store({ x: [2, 5] });
    Sync.schedule();
    await t.fire();
    assert.equal(puts(f).length, 2);
    assert.equal(t.pending.length, 0);
    assert.equal(log.sync.rev, 7);
    assert.equal(log.sync.dirty, true);
    assert.equal(Sync.status().error, "conflict");
  });

  it("backs off 5 s doubling to 60 s and stops after ten minutes", async () => {
    const f = fakeFetch([ME, { status: 204 }]);
    const { t } = host(f, store());
    await Sync.start();
    Sync.schedule();
    await t.fire();
    const delays = [];
    while (t.pending.length) {
      delays.push(t.delays[t.delays.length - 1]);
      await t.fire();
    }
    assert.deepEqual(delays.slice(0, 6), [5000, 10000, 20000, 40000, 60000, 60000]);
    assert.equal(delays.length, 12, "5+10+20+40+60 s, then 60 s steps, stops once ten minutes of waiting are used");
    assert.equal(delays.reduce((a, b) => a + b, 0), 555000);
    assert.equal(Sync.status().error, "network");
    assert.equal(Sync.status().dirty, true);
    assert.equal(puts(f).length, delays.length + 1);
  });

  it("flush pushes at once with keepalive and the CSRF headers", async () => {
    const f = fakeFetch([ME, { status: 204 }, { status: 200, body: { rev: 1 } }]);
    const { t } = host(f, store());
    await Sync.start();
    Sync.schedule();
    await Sync.flush();
    assert.equal(t.pending.length, 0, "the debounce timer is dropped");
    const p = puts(f);
    assert.equal(p.length, 1);
    assert.equal(p[0].init.keepalive, true);
    assert.equal(p[0].init.headers["X-Requested-With"], "jstudy");
    assert.equal(p[0].init.headers["Content-Type"], "application/json");
    assert.equal(p[0].init.credentials, "same-origin");
    await Sync.flush();
    assert.equal(puts(f).length, 1, "nothing dirty, nothing sent");
  });

  it("a 401 on push signs out and resets the sync state", async () => {
    const f = fakeFetch([ME, { status: 204 }, { status: 401 }]);
    const { t, log } = host(f, store());
    await Sync.start();
    Sync.schedule();
    await t.fire();
    assert.equal(Sync.status().mode, "anon");
    assert.deepEqual(log.sync, { rev: 0, dirty: false, lastPullAt: 0, user: 1 });
  });

  it("409: merges into the store as it is now, not the copy that went out", async () => {
    const server = store({ y: [4, 50] });
    let log = null;
    const during = () => {
      log.cur = store({ x: [2, 5], z: [3, 9] }); // graded while the PUT was out
      return { status: 409, body: { rev: 7, store: server } };
    };
    const f = fakeFetch([ME, { status: 204 }, during, { status: 200, body: { rev: 8 } }]);
    const h = host(f, store());
    log = h.log;
    await Sync.start();
    log.cur = store({ x: [2, 5] });
    Sync.schedule();
    await h.t.fire();
    const p = puts(f);
    assert.equal(p.length, 2);
    assert.deepEqual(Object.keys(p[1].body.store.items).sort(), ["x", "y", "z"]);
    assert.deepEqual(Object.keys(log.cur.items).sort(), ["x", "y", "z"]);
  });

  it("a save during a push goes out after it", async () => {
    const f = fakeFetch([ME, { status: 204 }, { status: 200, body: { rev: 1 } }, { status: 200, body: { rev: 2 } }]);
    const { t, log } = host(f, store());
    await Sync.start();
    Sync.schedule();
    const first = t.fire(); // the PUT is out
    log.cur = store({ x: [2, 5] });
    Sync.schedule();
    await t.fire(); // its timer finds the push inflight
    await first;
    assert.equal(log.sync.dirty, true);
    assert.equal(t.pending.length, 1, "armed again");
    await t.fire();
    const p = puts(f);
    assert.equal(p.length, 2);
    assert.equal(p[1].body.store.items.x.stage, 2);
    assert.deepEqual(log.sync, { rev: 2, dirty: false, lastPullAt: NOW, user: 1 });
  });
});

describe("switching accounts", () => {
  const B = { status: 200, body: { user: { id: 2, email: "d@e.f" } } };
  const synced = (user) => ({ rev: 0, dirty: false, lastPullAt: 0, user });

  it("another user's sign-in sets the local store aside and takes the server copy", async () => {
    const a = store({ x: [2, 5] });
    const f = fakeFetch([{ status: 401 }, B, { status: 200, body: { rev: 3, store: store({ y: [4, 50] }) } }]);
    const { log } = host(f, a, synced(1));
    await Sync.start();
    await Sync.api.verify("d@e.f", "123456");
    assert.deepEqual(log.backups, [a]);
    assert.equal(puts(f).length, 0, "nothing of user 1 reaches user 2's account");
    assert.deepEqual(Object.keys(log.cur.items), ["y"]);
    assert.deepEqual(log.sync, { rev: 3, dirty: false, lastPullAt: NOW, user: 2 });
  });

  it("a boot already signed in as another user does the same", async () => {
    const f = fakeFetch([B, { status: 204 }]);
    const { log } = host(f, store({ x: [2, 5] }), { rev: 4, dirty: true, lastPullAt: 0, user: 1 });
    await Sync.start();
    assert.equal(log.backups.length, 1);
    assert.equal(puts(f).length, 0);
    assert.deepEqual(log.cur.items, {});
    assert.deepEqual(log.sync, { rev: 0, dirty: false, lastPullAt: NOW, user: 2 });
  });

  it("the same user signing back in merges as before", async () => {
    const f = fakeFetch([{ status: 401 }, ME, { status: 200, body: { rev: 3, store: store({ y: [4, 50] }) } },
      { status: 200, body: { rev: 4 } }]);
    const { log } = host(f, store({ x: [2, 5] }), synced(1));
    await Sync.start();
    await Sync.api.verify("a@b.c", "123456");
    assert.equal(log.backups.length, 0);
    assert.deepEqual(Object.keys(puts(f)[0].body.store.items).sort(), ["x", "y"]);
  });

  it("deleting the account forgets whose progress this was", async () => {
    const f = fakeFetch([ME, { status: 204 }, { status: 204 }]);
    const { log } = host(f, store());
    await Sync.start();
    await Sync.api.remove();
    assert.deepEqual(log.sync, synced(null));
  });
});

describe("pull", () => {
  it("skips a pull younger than five minutes unless forced", async () => {
    const f = fakeFetch([ME, { status: 200, body: { rev: 2, store: store() } }, { status: 200, body: { rev: 2, store: store() } }]);
    host(f, store(), { rev: 2, dirty: false, lastPullAt: NOW - 60000 });
    await Sync.start();
    assert.equal(f.calls.length, 2, "boot pulls regardless of age");
    await Sync.pull();
    assert.equal(f.calls.length, 2);
    await Sync.pull(0);
    assert.equal(f.calls.length, 3);
  });

  it("merges a newer server copy and pushes only when local had something new", async () => {
    const server = store({ y: [4, 50] });
    const f = fakeFetch([ME, { status: 200, body: { rev: 5, store: server } }]);
    const { log } = host(f, store(), { rev: 2, dirty: false, lastPullAt: 0 });
    await Sync.start();
    assert.equal(puts(f).length, 0);
    assert.deepEqual(log.notes, ["Progress merged from another device."]);
    assert.equal(log.sync.rev, 5);
  });
});

describe("account api", () => {
  it("maps error bodies to codes and logs out through a flush", async () => {
    const f = fakeFetch([ME, { status: 204 }, { status: 429, body: { error: "too_many_requests", retry_after: 30 } },
      { status: 200, body: { rev: 1 } }, { status: 204 }]);
    const { log } = host(f, store());
    await Sync.start();
    await assert.rejects(Sync.api.code("a@b.c"), { error: "too_many_requests", status: 429, retryAfter: 30 });
    Sync.schedule();
    await Sync.api.logout(true);
    assert.equal(puts(f).length, 1, "pending progress goes out before the session ends");
    assert.deepEqual(f.calls[4].body, { all: true });
    assert.equal(Sync.status().mode, "anon");
    assert.deepEqual(log.sync, { rev: 0, dirty: false, lastPullAt: 0, user: 1 });
  });
});
