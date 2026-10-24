// Write-behind mirror of the store to the server, and the only module that
// calls /api/*. No DOM and no storage of its own: the host injects fetch,
// timers, the store accessors and the sync-state accessors, so tests run it
// against fakes. localStorage stays the source of truth on the device; the
// server keeps one copy per user with a revision the client must match.
import { dayKey } from "./ledger.js";
import { fresh, merge, parseImport } from "./store.js";

const DEBOUNCE_MS = 1500;
const PULL_MAX_AGE_MS = 5 * 60 * 1000;
const BACKOFF_FIRST_MS = 5000;
const BACKOFF_STEP_MAX_MS = 60000;
const BACKOFF_TOTAL_MS = 10 * 60 * 1000;
// ponytail: browsers cap keepalive bodies at 64 KiB; a bigger store pushes
// plain and leans on the persisted dirty flag to push again at next boot.
const KEEPALIVE_MAX_BYTES = 60 * 1024;

let h = null;
let mode = "unknown"; // unknown | off (no backend) | down (backend unreachable for now) | anon (not signed in) | on
let me = null; // last /api/me body
let state = { rev: 0, dirty: false, lastPullAt: 0, user: null };
let gen = 0; // bumped per schedule(); a push clears dirty only when no save came after it
let timer = null; // debounce or backoff timer
let failures = 0;
let backoffTotal = 0;
let inflight = null;
let lastError = null;

// hooks: fetch, setTimeout, clearTimeout, now (optional, default to globals);
// getStore, setStore(store), backup(store), loadSync, saveSync(state), notify(text).
export function init(hooks) {
  h = {
    fetch: (...a) => fetch(...a), setTimeout: (...a) => setTimeout(...a), clearTimeout: (...a) => clearTimeout(...a),
    now: () => Date.now(), ...hooks,
  };
  state = h.loadSync();
  mode = "unknown";
  me = null;
  gen = 0;
  timer = null;
  failures = 0;
  backoffTotal = 0;
  inflight = null;
  lastError = null;
}

export function status() {
  return { mode, dirty: state.dirty, lastPullAt: state.lastPullAt, error: lastError };
}
export const user = () => me;
export const backoffDelay = (n) => Math.min(BACKOFF_STEP_MAX_MS, BACKOFF_FIRST_MS * 2 ** n);
const num = (x) => (typeof x === "number" && Number.isFinite(x) ? x : 0);
const today = () => dayKey(new Date(h.now()));

// Content equality that ignores key order and the session (never synced).
const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x)
  ? Object.fromEntries(Object.keys(x).sort().map((key) => [key, x[key]])) : x));
const same = (x, y) => canon({ ...x, session: null }) === canon({ ...y, session: null });
const hasProgress = (s) => Object.keys(s.items).length > 0 || Object.keys(s.days).length > 0 || s.settingsAt > 0;

// Every request carries the CSRF header; mutating ones carry a JSON body.
async function call(method, path, body, extra = {}) {
  const init = {
    method, credentials: "same-origin", cache: "no-store",
    headers: { "X-Requested-With": "jstudy", Accept: "application/json", ...(extra.headers || {}) },
  };
  if (method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body === undefined ? {} : body);
    if (extra.keepalive && init.body.length <= KEEPALIVE_MAX_BYTES) init.keepalive = true;
  }
  let res;
  try {
    res = await h.fetch(path, init);
  } catch {
    throw { error: "network", status: 0 };
  }
  let data = null;
  if (res.status !== 204) {
    try {
      data = await res.json();
    } catch { /* HTML or empty body: a static server's 404, or nginx's error page */ }
  }
  return { status: res.status, ok: res.status >= 200 && res.status < 300, body: data };
}

async function expect(method, path, body) {
  const r = await call(method, path, body);
  if (!r.ok) throw { error: (r.body && r.body.error) || `http_${r.status}`, status: r.status, retryAfter: r.body && r.body.retry_after };
  return r.body;
}

// `user` survives a sign-out: it says whose progress the local store holds,
// so the next sign-in can tell a returning user from a different one. A
// deleted account forgets it, since the progress kept here is nobody's now.
function signedOut(forget = false) {
  mode = "anon";
  me = null;
  state = { rev: 0, dirty: false, lastPullAt: 0, user: forget ? null : state.user };
  h.saveSync(state);
  if (timer) h.clearTimeout(timer);
  timer = null;
}

// Backend present and session valid? A 404 means no backend (py -m
// http.server): sync stays off and the app runs as before. A network error
// or a 5xx is an outage, not a missing backend, so retry() probes again.
async function probe() {
  try {
    const r = await call("GET", "/api/me");
    if (r.status === 200 && r.body && r.body.user) {
      me = r.body;
      mode = "on";
    } else if (r.status === 401) {
      me = null;
      mode = "anon";
    } else mode = r.status >= 500 ? "down" : "off";
  } catch {
    mode = "down";
  }
  return mode;
}

// Before the first pull of a sign-in: a store last synced to another account
// is set aside and replaced by this account's copy, so one user's progress
// never merges into another's. A browser that never synced keeps pull()'s
// migration rule and takes its local progress up.
function claim() {
  const id = me && me.user ? me.user.id : null;
  if (id == null || id === state.user) return;
  if (state.user != null) {
    h.backup(h.getStore());
    h.setStore(fresh());
    h.notify("Progress from the previous account was set aside on this device.");
    state = { rev: 0, dirty: false, lastPullAt: 0, user: id };
  } else state.user = id;
  h.saveSync(state);
}

export async function start() {
  if (await probe() === "on") {
    claim();
    await pull(0);
  }
  return mode;
}

// On wake or when the browser comes back online: probe again after an outage.
export function retry() {
  return mode === "down" ? start() : Promise.resolve(mode);
}

export const api = {
  async me() {
    try {
      me = await expect("GET", "/api/me");
      mode = "on";
      return me;
    } catch (e) {
      if (e.status === 401) signedOut();
      throw e;
    }
  },
  code: (email) => expect("POST", "/api/auth/code", { email }),
  // First login in this browser: pull(0) applies the migration rules (server
  // empty → push local; local fresh → take server; both → merge and push).
  async verify(email, code) {
    me = await expect("POST", "/api/auth/verify", { email, code });
    mode = "on";
    claim();
    await pull(0);
    return me;
  },
  async logout(all) {
    await flush();
    await expect("POST", "/api/auth/logout", all ? { all: true } : {});
    signedOut();
  },
  async remove() {
    await expect("DELETE", "/api/me", { confirm: "delete" });
    signedOut(true);
  },
  admin: {
    list: () => expect("GET", "/api/admin/users"),
    invite: (email) => expect("POST", "/api/admin/invites", { email }),
    revoke: (email) => expect("DELETE", "/api/admin/invites", { email }),
    setDisabled: (id, disabled) => expect("PATCH", `/api/admin/users/${id}`, { disabled }),
    remove: (id) => expect("DELETE", `/api/admin/users/${id}`, { confirm: "delete" }),
  },
};

function arm(ms) {
  if (timer) h.clearTimeout(timer);
  timer = h.setTimeout(() => {
    timer = null;
    return push();
  }, ms);
}

// Called after every local save: pushes 1.5 s after the last one.
export function schedule() {
  gen += 1;
  if (mode !== "on") return;
  state.dirty = true;
  h.saveSync(state);
  arm(DEBOUNCE_MS);
}

// Immediate push for visibilitychange → hidden and pagehide.
export function flush() {
  if (mode !== "on" || !state.dirty) return Promise.resolve();
  if (timer) h.clearTimeout(timer);
  timer = null;
  return push(true);
}

function backoff() {
  const delay = backoffDelay(failures);
  failures += 1;
  backoffTotal += delay;
  lastError = "network";
  if (backoffTotal > BACKOFF_TOTAL_MS) {
    // Ten minutes of failures: stop until the next save or wake.
    failures = 0;
    backoffTotal = 0;
    return;
  }
  arm(delay);
}

function put(store, keepalive) {
  return call("PUT", "/api/progress", { store }, { headers: { "If-Match": `"${state.rev}"` }, keepalive });
}

function push(keepalive = false) {
  if (mode !== "on") return Promise.resolve();
  if (inflight) return inflight;
  const g = gen;
  inflight = doPush(keepalive).finally(() => {
    inflight = null;
    // A save during the push spent its timer on this inflight push; arm
    // again so it goes out, unless a backoff timer already will.
    if (gen !== g && state.dirty && mode === "on" && !timer) arm(DEBOUNCE_MS);
  });
  return inflight;
}

async function doPush(keepalive) {
  const g = gen;
  let local = h.getStore();
  let r;
  try {
    r = await put(local, keepalive);
  } catch {
    return backoff();
  }
  if (r.status === 409 && r.body && r.body.store) {
    // Another device pushed first: fold its copy in, save, try once more.
    // A second 409 waits for the next save; its rev is left alone so the
    // unmerged server copy comes back on that retry.
    let server;
    try {
      server = parseImport(r.body.store, h.now());
    } catch {
      lastError = "bad_store";
      return;
    }
    // Re-read: grades, an import or a pull may have replaced the store while
    // the PUT was out, and merging the copy sent would drop them.
    local = h.getStore();
    const merged = merge(local, server, today());
    if (!same(merged, local)) {
      h.setStore(merged);
      h.notify("Progress merged from another device.");
    }
    local = merged;
    state.rev = num(r.body.rev);
    h.saveSync(state);
    try {
      r = await put(local, keepalive);
    } catch {
      return backoff();
    }
    if (r.status === 409) {
      lastError = "conflict";
      return;
    }
  }
  if (r.status === 200 && r.body) {
    state.rev = num(r.body.rev);
    if (gen === g) state.dirty = false;
    failures = 0;
    backoffTotal = 0;
    lastError = null;
    h.saveSync(state);
    return;
  }
  if (r.status === 401) return signedOut();
  if (r.status >= 500) return backoff();
  lastError = (r.body && r.body.error) || `http_${r.status}`; // 400, 413, 428: nothing to retry until the store changes
}

// Server copy into the local one. On boot and on login maxAgeMs is 0; on
// becoming visible the default skips a pull younger than five minutes.
export async function pull(maxAgeMs = PULL_MAX_AGE_MS) {
  if (mode !== "on" || inflight) return;
  if (maxAgeMs && h.now() - state.lastPullAt < maxAgeMs) return;
  const first = state.rev === 0;
  let r;
  try {
    r = await call("GET", "/api/progress");
  } catch {
    lastError = "network";
    return;
  }
  if (r.status === 401) return signedOut();
  const local = h.getStore();
  if (r.status === 204) {
    state.rev = 0;
    state.lastPullAt = h.now();
    state.dirty = hasProgress(local);
    h.saveSync(state);
    if (!state.dirty) return;
    await push();
    if (first && !state.dirty) h.notify("Progress saved to your account.");
    return;
  }
  if (r.status !== 200 || !r.body || !r.body.store) {
    lastError = (r.body && r.body.error) || `http_${r.status}`;
    return;
  }
  let server;
  try {
    server = parseImport(r.body.store, h.now());
  } catch {
    lastError = "bad_store";
    return;
  }
  const merged = merge(local, server, today());
  state.rev = num(r.body.rev);
  state.lastPullAt = h.now();
  state.dirty = !same(merged, server);
  h.saveSync(state);
  if (!same(merged, local)) {
    h.setStore(merged);
    h.notify(!first ? "Progress merged from another device."
      : hasProgress(local) ? "Progress merged with your account." : "Progress loaded from your account.");
  }
  if (state.dirty) await push();
}
