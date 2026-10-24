// Day ledger: one row per study day. Streak, freezes and activity derive
// from the rows; nothing else is stored. Pure; keys are local YYYY-MM-DD.

export function dayKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function shiftKey(key, days) {
  const [y, m, d] = key.split("-").map(Number);
  return dayKey(new Date(y, m - 1, d + days));
}

export function row(days, key) {
  return days[key] || (days[key] = { r: 0, l: 0, miss: 0, up: 0, done: false, freeze: false });
}

export function recordReview(days, key, incorrect, rose) {
  const d = row(days, key);
  d.r += 1;
  d.miss += incorrect;
  if (rose) d.up += 1;
}

export function recordLessons(days, key, n) {
  row(days, key).l += n;
}

// Done = both quotas met or nothing left to do on either. Never undone:
// more work later in the day can't cost the day.
export function markDone(days, key, reviewsLeft, lessonsLeft, settings) {
  const d = row(days, key);
  d.done = d.done || ((d.r >= settings.reviewsPerDay || reviewsLeft === 0)
    && (d.l >= settings.lessonsPerDay || lessonsLeft === 0));
  return d.done;
}

// Freeze each undone day after the last done or frozen one, up to yesterday,
// as long as no freeze sits in the six days before it; a second miss stops.
export function settle(days, today) {
  const marked = Object.keys(days).filter((k) => days[k].done || days[k].freeze).sort();
  if (!marked.length) return;
  for (let k = shiftKey(marked[marked.length - 1], 1); k < today; k = shiftKey(k, 1)) {
    for (let i = 1; i <= 6; i++) {
      const p = days[shiftKey(k, -i)];
      if (p && p.freeze) return;
    }
    row(days, k).freeze = true;
  }
}

// Consecutive done days ending today (when done) or yesterday; frozen days
// bridge the chain without counting.
export function streak(days, today) {
  let n = 0;
  let k = days[today] && days[today].done ? today : shiftKey(today, -1);
  for (; days[k] && (days[k].done || days[k].freeze); k = shiftKey(k, -1)) if (days[k].done) n += 1;
  return n;
}

export function daysActive(days, monthPrefix) {
  return Object.keys(days).filter((k) => k.startsWith(monthPrefix) && days[k].r + days[k].l > 0).length;
}

// Lessons a day over the last `span` days, today included. A ledger younger
// than the span averages over its own age, so day one reads as that day's pace.
export function pace(days, today, span = 14) {
  const first = Object.keys(days).sort()[0];
  if (!first) return 0;
  const n = Math.max(1, Math.min(span, daysBetween(first, today) + 1));
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const d = days[shiftKey(today, -i)];
    if (d) sum += d.l;
  }
  return sum / n;
}

export function daysBetween(fromKey, toKey) {
  const utc = (k) => {
    const [y, m, d] = k.split("-").map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((utc(toKey) - utc(fromKey)) / 86400000);
}

// Highest level whose cumulative item count fits `items` (cumulative[L] is
// the number of items on levels 1..L). Never below 1 or above 60.
export function projectLevel(cumulative, items) {
  let level = 1;
  for (let l = 1; l <= 60 && l < cumulative.length; l++) {
    if (cumulative[l] <= items) level = l;
    else break;
  }
  return level;
}

export function level60Date(today, remaining, pace) {
  return pace > 0 ? shiftKey(today, Math.ceil(Math.max(0, remaining) / pace)) : null;
}
