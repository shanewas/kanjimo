// Cross-tab convergence over the store key. No DOM and no storage of its
// own: the host injects the store accessors, the clock, whether a review
// session is in progress, and how to repaint, so tests run it against
// fakes. The other tab's write is folded into the local store with the
// same merge() server sync uses — never adopted wholesale, since this tab
// may hold grades the writer had not seen, and never a reload-or-clobber.
//
// Mid-session policy: a session works from its own prompt list and grades
// the item under the current card from DB.store at grade time, so swapping
// the store mid-answer could move that item first or repaint the card.
// While a session runs, incoming stores are therefore only accumulated
// (each folded into the pending one) and applied whole when the session
// ends; the in-flight grade is written locally first and then wins or
// loses per item by its own `at` stamp, like any other merge.
import { dayKey } from "./ledger.js";
import { KEY, merge, parseImport } from "./store.js";

let h = null;
let pending = null;

// hooks: getStore, setStore(store), now (optional), inSession, refresh.
export function init(hooks) {
  h = { now: () => Date.now(), inSession: () => false, refresh: () => {}, ...hooks };
  pending = null;
}

const today = () => dayKey(new Date(h.now()));

// Content equality that ignores key order and the session: a session is
// per-tab working state, merge() never takes the incoming one, and a
// difference in it alone must not trigger a write back.
const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x)
  ? Object.fromEntries(Object.keys(x).sort().map((key) => [key, x[key]])) : x));
const same = (x, y) => canon({ ...x, session: null }) === canon({ ...y, session: null });

// Fold `incoming` into the local store and persist through the host when
// anything changed. Merging is idempotent, so the write this makes lands
// in the other tab as a merge that changes nothing and writes nothing:
// the exchange settles instead of echoing.
function apply(incoming, refresh) {
  const local = h.getStore();
  const merged = merge(local, incoming, today());
  if (same(merged, local)) return false;
  h.setStore(merged);
  if (refresh) h.refresh();
  return true;
}

// A `storage` event ({ key, newValue }) from another tab. The event never
// fires in the tab that wrote, but a merged write-back reaches every other
// tab the same way, so no-op merges above are the loop guard. Returns true
// when a change was applied or queued for the end of the session.
export function onStorage(ev) {
  if (!h || !ev || ev.key !== KEY || !ev.newValue) return false;
  let incoming;
  try {
    incoming = parseImport(ev.newValue, h.now());
  } catch {
    return false; // damaged or foreign payload: the writing tab's load quarantines it
  }
  if (h.inSession()) {
    pending = pending ? merge(pending, incoming, today()) : incoming;
    return true;
  }
  return apply(incoming, true);
}

// Apply what arrived during a session. Called by the host once the
// session has ended and its last grades are saved; the caller paints the
// next view itself, so this never repaints.
export function applyPending() {
  if (!h || !pending || h.inSession()) return false;
  const incoming = pending;
  pending = null;
  return apply(incoming, false);
}

export const hasPending = () => pending !== null;
