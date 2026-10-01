// Balance Tracker engine for the iPhone web app.
// A faithful port of balance_tracker/forecast.py, debts.py and sync.py so the phone
// and the PC compute identical numbers. tests/test_web_engine.py cross-checks them.
//
// Data is the same JSON as the desktop backup file. Dates are ISO strings in the data
// and integer "day numbers" (days since 1970-01-01, UTC) inside the engine.

// ---------------------------------------------------------------- dates
const MS = 86400000;
export const toDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d) / MS; };
export const toISO = (n) => new Date(n * MS).toISOString().slice(0, 10);
export const ymd = (n) => { const t = new Date(n * MS); return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() }; };
export const fromYMD = (y, m, d) => Date.UTC(y, m - 1, d) / MS;
export const daysInMonth = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
export const weekday = (n) => (new Date(n * MS).getUTCDay() + 6) % 7; // Mon=0 … Sun=6
export const todayDay = () => { const t = new Date(); return fromYMD(t.getFullYear(), t.getMonth() + 1, t.getDate()); };
const floorDiv = (a, b) => Math.floor(a / b);
const mod = (a, b) => ((a % b) + b) % b;

export function clampDay(y, m, day) { return fromYMD(y, m, Math.min(day, daysInMonth(y, m))); }
export function addMonths(n, months, day = null) {
  const { y, m, d } = ymd(n);
  const mm = m - 1 + months;
  return clampDay(y + floorDiv(mm, 12), mod(mm, 12) + 1, day || d);
}
const monthsBetween = (a, b) => { const A = ymd(a), B = ymd(b); return (B.y - A.y) * 12 + (B.m - A.m); };
const firstOfMonth = (n) => { const { y, m } = ymd(n); return fromYMD(y, m, 1); };

// Python's round(): half to even
export function pyRound(x) {
  const f = Math.floor(x);
  const diff = x - f;
  if (diff > 0.5) return f + 1;
  if (diff < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}
const lower = (s) => s.toLowerCase();
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const cmpTuple = (a, b) => { for (let i = 0; i < a.length; i++) { const c = cmp(a[i], b[i]); if (c) return c; } return 0; };

// ---------------------------------------------------------------- model
export const FREQUENCIES = {
  once: "One time", weekly: "Weekly", biweekly: "Every 2 weeks", fourweekly: "Every 4 weeks",
  semimonthly: "Twice a month", monthly: "Monthly", bimonthly: "Every 2 months",
  quarterly: "Every 3 months", semiannual: "Every 6 months", yearly: "Yearly",
};
export const WEEKEND_RULES = { none: "Keep the date", before: "Move to the Friday before", after: "Move to the Monday after" };
export const DEBT_KINDS = { credit_card: "Credit card", line_of_credit: "Line of credit", loan: "Loan" };
export const DEBT_STRATEGIES = { avalanche: "Highest interest first", snowball: "Smallest balance first" };
const STEP_DAYS = { weekly: 7, biweekly: 14, fourweekly: 28 };
const STEP_MONTHS = { monthly: 1, bimonthly: 2, quarterly: 3, semiannual: 6, yearly: 12 };
const PER_YEAR = { once: 0, weekly: 52, biweekly: 26, fourweekly: 13, semimonthly: 24, monthly: 12, bimonthly: 6, quarterly: 4, semiannual: 2, yearly: 1 };
export const SHARED_SETTINGS = ["currency_symbol", "low_balance_threshold", "forecast_months", "account_name",
  "debt_strategy", "debt_mode", "debt_fixed_extra", "debt_in_forecast"];

export const newId = () => Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(16).padStart(2, "0")).join("");
export const nowUTC = () => new Date().toISOString();
export const nowLocal = () => { const t = new Date(); const p = (x) => String(x).padStart(2, "0");
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}T${p(t.getHours())}:${p(t.getMinutes())}:${p(t.getSeconds())}`; };

const DEFAULT_SETTINGS = {
  theme: "system", currency_symbol: "$", low_balance_threshold: 10000, forecast_months: 6, prompt_on_open: true,
  account_name: "Chequing", debt_strategy: "avalanche", debt_mode: "auto", debt_fixed_extra: 0, debt_in_forecast: false,
};

export function normItem(d) {
  const freq = FREQUENCIES[d.frequency] ? d.frequency : "monthly";
  const overrides = {};
  for (const [k, v] of Object.entries(d.overrides || {})) overrides[k] = v === null ? null : Math.trunc(Number(v));
  return {
    name: String(d.name ?? ""), amount: Math.abs(Math.trunc(Number(d.amount) || 0)), kind: d.kind === "income" ? "income" : "bill",
    frequency: freq, start_date: d.start_date || toISO(todayDay()), end_date: d.end_date || null,
    second_day: Math.trunc(Number(d.second_day ?? 31)), weekend_rule: WEEKEND_RULES[d.weekend_rule] ? d.weekend_rule : "none",
    category: String(d.category ?? ""), notes: String(d.notes ?? ""), active: d.active !== false, overrides,
    paid_with: String(d.paid_with || ""), updated: String(d.updated || ""), id: String(d.id || newId()),
  };
}
export function normDebt(d) {
  return {
    name: String(d.name ?? ""), balance: Math.max(0, Math.trunc(Number(d.balance) || 0)), apr: Math.max(0, Number(d.apr) || 0),
    kind: DEBT_KINDS[d.kind] ? d.kind : "credit_card", due_day: Math.min(31, Math.max(1, Math.trunc(Number(d.due_day) || 1))),
    min_amount: Math.max(0, Math.trunc(Number(d.min_amount) || 0)), min_percent: Math.max(0, Number(d.min_percent) || 0),
    min_plus_interest: d.min_plus_interest !== false, credit_limit: Math.max(0, Math.trunc(Number(d.credit_limit) || 0)),
    linked_bill_id: String(d.linked_bill_id || ""), updated_on: d.updated_on || toISO(todayDay()), notes: String(d.notes ?? ""),
    updated: String(d.updated || ""), id: String(d.id || newId()),
  };
}
export function normCheckpoint(d) {
  return { date: d.date, balance: Math.trunc(Number(d.balance) || 0), includes_today: d.includes_today !== false,
    note: String(d.note ?? ""), created_at: String(d.created_at ?? ""), id: String(d.id || newId()) };
}
export function normData(d) {
  if (!d || typeof d !== "object" || !Array.isArray(d.items)) throw new Error("This file is not a Balance Tracker backup.");
  return {
    app: "BalanceTracker", schema: 1,
    settings: { ...DEFAULT_SETTINGS, ...(d.settings || {}) },
    items: d.items.map(normItem),
    checkpoints: (d.checkpoints || []).map(normCheckpoint),
    debts: (d.debts || []).map(normDebt),
    card_paid: (d.card_paid || []).map(String),
    deleted: { ...(d.deleted || {}) },
    settings_updated: String(d.settings_updated || ""),
  };
}
export const emptyData = () => normData({ items: [] });

export const sortedCheckpoints = (data) => [...data.checkpoints].sort((a, b) => cmpTuple([a.date, a.created_at], [b.date, b.created_at]));
export const startCheckpoint = (data) => sortedCheckpoints(data)[0] || null;
export const latestCheckpoint = (data) => { const c = sortedCheckpoints(data); return c[c.length - 1] || null; };
export const findItem = (data, id) => data.items.find((i) => i.id === id) || null;
export const findDebt = (data, id) => data.debts.find((d) => d.id === id) || null;
export const signedAmount = (item) => (item.kind === "income" ? item.amount : -item.amount);
export function addCheckpoint(data, cp) {
  data.checkpoints = data.checkpoints.filter((c) => c.date !== cp.date);
  data.checkpoints.push(cp);
}

// ---------------------------------------------------------------- schedule
export function shiftWeekend(n, rule) {
  const wd = weekday(n);
  if (wd < 5 || rule === "none") return n;
  if (rule === "before") return n - (wd - 4);
  return n + (7 - wd);
}

export function* scheduledDates(item, until, since = null) {
  const start = toDay(item.start_date);
  const end = item.end_date ? Math.min(until, toDay(item.end_date)) : until;
  since = since ?? start;
  if (end < start) return;
  const f = item.frequency;
  if (f === "once") { yield start; return; }
  if (STEP_DAYS[f]) {
    const step = STEP_DAYS[f];
    const k = Math.max(0, floorDiv(since - start, step) - 1);
    for (let d = start + step * k; d <= end; d += step) yield d;
    return;
  }
  const sd = ymd(start);
  if (STEP_MONTHS[f]) {
    const step = STEP_MONTHS[f];
    let k = Math.max(0, floorDiv(monthsBetween(start, since), step) - 1);
    for (;;) {
      const d = addMonths(start, step * k, sd.d);
      if (d > end) break;
      yield d;
      k += 1;
    }
    return;
  }
  if (f === "semimonthly") {
    const days = [...new Set([sd.d, item.second_day || 31])].sort((a, b) => a - b);
    let k = Math.max(0, monthsBetween(start, since) - 1);
    for (;;) {
      const first = addMonths(firstOfMonth(start), k, 1);
      if (first > end) break;
      const F = ymd(first);
      for (const dd of days) { const d = clampDay(F.y, F.m, dd); if (start <= d && d <= end) yield d; }
      k += 1;
    }
  }
}

export function occurrences(item, start, end) {
  const out = [];
  if (!item.active) return out;
  for (const sd of scheduledDates(item, end + 3, start - 3)) {
    const post = shiftWeekend(sd, item.weekend_rule);
    if (post < start || post > end) continue;
    const key = toISO(sd);
    if (Object.prototype.hasOwnProperty.call(item.overrides, key)) {
      const ov = item.overrides[key];
      if (ov === null) continue;
      out.push({ date: post, scheduled: sd, amount: item.kind === "income" ? Math.abs(ov) : -Math.abs(ov), item, overridden: true });
    } else {
      out.push({ date: post, scheduled: sd, amount: signedAmount(item), item, overridden: false });
    }
  }
  return out;
}

export function nextOccurrence(item, today) {
  for (const h of [400, 4000]) {
    const occ = occurrences(item, today, today + h);
    if (occ.length) return occ.reduce((a, b) => (b.date < a.date ? b : a));
  }
  return null;
}
export const monthlyEquivalent = (item) => pyRound((signedAmount(item) * PER_YEAR[item.frequency]) / 12);

// ---------------------------------------------------------------- forecast
const occKey = (o) => [o.amount < 0 ? 1 : 0, lower(o.item.name)];
const sortOccs = (list) => [...list].sort((a, b) => cmpTuple(occKey(a), occKey(b)));

export class Forecast {
  constructor(data, end, today, extra = [], suppress = {}) {
    this.data = data; this.today = today; this.end = end; this.extra = extra; this.suppress = suppress;
    this.entries = []; this.daily = new Map(); this.start = null;
    this._build();
  }
  _build() {
    const cps = sortedCheckpoints(this.data);
    if (!cps.length) return;
    const first = cps[0];
    const firstDay = toDay(first.date);
    this.start = firstDay;
    if (this.end < firstDay) this.end = firstDay;
    const cpByDate = new Map(cps.map((c) => [toDay(c.date), c]));
    const occByDate = new Map();
    const push = (o) => { if (!occByDate.has(o.date)) occByDate.set(o.date, []); occByDate.get(o.date).push(o); };
    for (const item of this.data.items) {
      const cut = this.suppress[item.id];
      for (const o of occurrences(item, firstDay, this.end)) if (cut === undefined || o.date < cut) push(o);
    }
    const startExtras = [];
    for (const o of this.extra) {
      if (o.date === firstDay) startExtras.push(o);
      else if (firstDay < o.date && o.date <= this.end) push(o);
    }
    let running = first.balance;
    for (let d = firstDay; d <= this.end; d++) {
      let todays = sortOccs(occByDate.get(d) || []);
      if (d === firstDay) {
        this.entries.push(this._entry(d, "start", "Starting balance", 0, running, { checkpoint_id: first.id }));
        if (!first.includes_today) running = this._apply(sortOccs([...todays, ...startExtras]), running);
        else running = this._apply(startExtras, running);
      } else {
        const cp = cpByDate.get(d);
        if (cp && !cp.includes_today) { running = this._checkin(cp, running, d); running = this._apply(todays, running); }
        else if (cp) { running = this._apply(todays, running); running = this._checkin(cp, running, d); }
        else running = this._apply(todays, running);
      }
      this.daily.set(d, running);
    }
  }
  _entry(date, kind, description, amount, balance, extra = {}) {
    return { date, kind, description, amount, balance, category: "", item_id: null, scheduled: null, checkpoint_id: null,
      overridden: false, projected: null, ...extra };
  }
  _apply(occs, running) {
    for (const o of occs) {
      running += o.amount;
      let desc = o.item.name;
      const card = o.item.paid_with ? findDebt(this.data, o.item.paid_with) : null;
      if (card) desc = `Pay ${card.name}: ${o.item.name}`;
      this.entries.push(this._entry(o.date, o.amount >= 0 ? "income" : "bill", desc, o.amount, running, {
        category: o.item.category || "", item_id: o.item.id || null, scheduled: o.scheduled, overridden: o.overridden }));
    }
    return running;
  }
  _checkin(cp, running, d) {
    const diff = cp.balance - running;
    let desc = diff < 0 ? "Check-in: unplanned spending" : diff > 0 ? "Check-in: unplanned income" : "Check-in: right on plan";
    if (cp.note) desc += ` — ${cp.note}`;
    this.entries.push(this._entry(d, "checkin", desc, diff, cp.balance, { checkpoint_id: cp.id, projected: running }));
    return cp.balance;
  }
  get empty() { return this.daily.size === 0; }
  balanceOn(d) { return this.daily.has(d) ? this.daily.get(d) : null; }
  balanceBefore(d) {
    if (this.start === null || d < this.start) return null;
    if (d === this.start) return startCheckpoint(this.data).balance;
    return this.balanceOn(d - 1);
  }
  entriesBetween(a, b) { return this.entries.filter((e) => a <= e.date && e.date <= b); }
  lowest(a, b) {
    let best = null;
    for (let d = this.start !== null ? Math.max(a, this.start) : a; d <= b; d++) {
      const bal = this.daily.get(d);
      if (bal !== undefined && (best === null || bal < best[1])) best = [d, bal];
    }
    return best;
  }
  firstBelow(threshold, a, b = null) {
    for (const [d, bal] of this.daily) if (d >= a && (b === null || d <= b) && bal < threshold) return [d, bal];
    return null;
  }
  nextIncome(after) { return this.entries.find((e) => e.kind === "income" && e.date > after) || null; }
  safeToSpend(today, days = 30, cushion = 0) { const low = this.lowest(today, today + days); return low ? low[1] - cushion : null; }
  unplannedByMonth() {
    const out = new Map();
    for (const e of this.entries) if (e.kind === "checkin") { const { y, m } = ymd(e.date); const k = `${y}-${m}`; out.set(k, (out.get(k) || 0) + e.amount); }
    return out;
  }
  checkins() { return this.entries.filter((e) => e.kind === "checkin"); }
}

export const horizonEnd = (data, today) => addMonths(today, data.settings.forecast_months);
export const projectionEnd = (data, today) => addMonths(today, Math.max(12, data.settings.forecast_months));

// ---------------------------------------------------------------- debts
const MONTHS = 120;
export function minimumPayment(debt, balance, interest) {
  let pct = (balance * debt.min_percent) / 100;
  if (debt.min_plus_interest) pct += interest;
  return Math.min(balance, Math.max(debt.min_amount, pct));
}
function orderDebts(debts, bals, strategy) {
  const live = debts.filter((d) => bals.get(d.id) > 0.5);
  const key = strategy === "snowball" ? (d) => [bals.get(d.id), -d.apr, lower(d.name)] : (d) => [-d.apr, bals.get(d.id), lower(d.name)];
  return [...live].sort((a, b) => cmpTuple(key(a), key(b)));
}

export class Plan {
  constructor(strategy) {
    this.strategy = strategy; this.payments = []; this.payoff = new Map(); this.interest = new Map();
    this.totals = []; this.extraDates = new Map(); this.remainingAfterMin = new Map(); this.extras = new Map(); this.order = [];
  }
  get totalInterest() { let s = 0; for (const v of this.interest.values()) s += v; return s; }
  get debtFree() {
    if (!this.payoff.size || this.payoff.size < this.interest.size) return null;
    return Math.max(...this.payoff.values());
  }
  nextExtra(today) { return this.payments.find((p) => p.extra && p.date >= today) || null; }
  occurrences(debts, includeExtra = true) {
    const names = new Map(debts.map((d) => [d.id, d.name]));
    const out = [];
    for (const p of this.payments) {
      if (p.extra && !includeExtra) continue;
      const label = `${names.get(p.debt_id) || "Debt"} — ${p.extra ? "extra payment (plan)" : "minimum payment"}`;
      const item = { name: label, amount: p.amount, kind: "bill", category: "Debt", id: "", paid_with: "" };
      out.push({ date: p.date, scheduled: p.date, amount: -p.amount, item, overridden: false });
    }
    return out;
  }
  monthRows(today, months = 12) {
    const start = firstOfMonth(today);
    const last = this.payments.length ? Math.max(...this.payments.map((p) => p.date)) : null;
    const rows = [];
    for (let m = 0; m < months; m++) {
      const first = addMonths(start, m, 1);
      const nxt = addMonths(start, m + 1, 1);
      const per = new Map();
      let extra = 0;
      for (const p of this.payments) {
        if (first <= p.date && p.date < nxt) { per.set(p.debt_id, (per.get(p.debt_id) || 0) + p.amount); if (p.extra) extra += p.amount; }
      }
      if (last === null || first > last) break;
      rows.push([first, per, extra]);
    }
    return rows;
  }
}

export function simulate(debts, today, strategy, extras, months = MONTHS, rollover = false) {
  const plan = new Plan(strategy);
  plan.extras = new Map(extras);
  const bals = new Map(debts.map((d) => [d.id, d.balance]));
  for (const d of debts) plan.interest.set(d.id, 0);
  let freed = 0;
  const month0 = firstOfMonth(today);
  plan.order = orderDebts(debts, bals, strategy).map((d) => d.id);
  for (const d of debts) if (bals.get(d.id) <= 0.5) plan.payoff.set(d.id, today);
  const sumBals = () => { let s = 0; for (const v of bals.values()) s += v; return s; };
  for (let m = 0; m < months; m++) {
    if ([...bals.values()].every((b) => b <= 0.5)) break;
    const first = addMonths(month0, m, 1);
    const F = ymd(first);
    const due = new Map(debts.map((d) => [d.id, clampDay(F.y, F.m, d.due_day)]));
    const lastMin = new Map();
    const byDue = [...debts].sort((a, b) => due.get(a.id) - due.get(b.id));
    for (const d of byDue) {
      let bal = bals.get(d.id);
      if (bal <= 0.5 || due.get(d.id) < today) continue;
      const interest = (bal * d.apr) / 1200;
      bal += interest;
      plan.interest.set(d.id, plan.interest.get(d.id) + pyRound(interest));
      let pay = pyRound(minimumPayment(d, bal, interest));
      pay = Math.min(pay, pyRound(bal));
      if (pay > 0) plan.payments.push({ date: due.get(d.id), debt_id: d.id, amount: pay, extra: false });
      bal -= pay;
      lastMin.set(d.id, pay);
      if (bal <= 0.5) { bal = 0; plan.payoff.set(d.id, due.get(d.id)); freed += pay; }
      bals.set(d.id, bal);
    }
    const order = orderDebts(debts, bals, strategy);
    if (order.length) {
      const when = Math.max(today, due.get(order[0].id));
      plan.extraDates.set(m, when);
      plan.remainingAfterMin.set(m, pyRound(sumBals()));
      let extra = (extras.get(m) || 0) + (rollover ? pyRound(freed) : 0);
      for (const d of order) {
        if (extra <= 0) break;
        const pay = Math.min(extra, pyRound(bals.get(d.id)));
        if (pay <= 0) continue;
        plan.payments.push({ date: when, debt_id: d.id, amount: pay, extra: true });
        bals.set(d.id, bals.get(d.id) - pay);
        extra -= pay;
        if (bals.get(d.id) <= 0.5) { bals.set(d.id, 0); plan.payoff.set(d.id, when); if (rollover) freed += lastMin.get(d.id) || 0; }
      }
    }
    plan.totals.push([addMonths(month0, m + 1, 1) - 1, pyRound(sumBals())]);
  }
  plan.payments.sort((a, b) => cmpTuple([a.date, a.extra ? 1 : 0], [b.date, b.extra ? 1 : 0]));
  return plan;
}

const roundDown = (c) => (c >= 10000 ? floorDiv(c, 1000) * 1000 : floorDiv(c, 100) * 100);

export function planStart(data, today) {
  const lc = latestCheckpoint(data);
  if (lc && toDay(lc.date) >= today && lc.includes_today) return toDay(lc.date) + 1;
  return today;
}
export function baseForecast(data, today, years = 10) {
  const start = planStart(data, today);
  const suppress = {};
  for (const d of data.debts) if (d.linked_bill_id) suppress[d.linked_bill_id] = start;
  return new Forecast(data, addMonths(today, years * 12), today, [], suppress);
}

export function makePlan(data, today, strategy = null, mode = null) {
  const s = data.settings;
  const baseToday = today;
  today = planStart(data, today);
  strategy = strategy || s.debt_strategy;
  mode = mode || s.debt_mode;
  const debts = data.debts.filter((d) => d.balance > 0);
  if (!debts.length) return new Plan(strategy);
  if (mode === "minimum") return simulate(debts, today, strategy, new Map());
  if (mode === "fixed") {
    const extras = new Map();
    if (s.debt_fixed_extra > 0) for (let m = 0; m < MONTHS; m++) extras.set(m, s.debt_fixed_extra);
    return simulate(debts, today, strategy, extras, MONTHS, true);
  }
  const base = baseForecast(data, baseToday);
  const days = [];
  for (let d = today; d <= base.end; d++) { const v = base.daily.get(d); if (v !== undefined) days.push([d, v]); }
  if (!days.length) return simulate(debts, today, strategy, new Map());
  const index = new Map(days.map(([d], i) => [d, i]));
  const n = days.length;
  const cushion = s.low_balance_threshold;
  const extras = new Map();
  let plan = simulate(debts, today, strategy, extras);
  for (let m = 0; m < MONTHS; m++) {
    const when = plan.extraDates.get(m);
    if (when === undefined || when > days[n - 1][0]) break;
    const spent = new Array(n).fill(0);
    for (const p of plan.payments) { const i = index.get(p.date); if (i !== undefined) spent[i] += p.amount; }
    let run = 0, low = null;
    const startI = index.get(when);
    for (let i = 0; i < n; i++) {
      run += spent[i];
      if (i >= startI) { const v = days[i][1] - run; if (low === null || v < low) low = v; }
    }
    const avail = low - cushion;
    const owed = plan.remainingAfterMin.get(m) || 0;
    const room = avail >= owed ? owed : roundDown(avail);
    if (room > 0) { extras.set(m, room); plan = simulate(debts, today, strategy, extras); }
  }
  return plan;
}

export function fullForecast(data, plan, today, end, extra = [], debtExtras = true, source = null) {
  extra = [...extra];
  const suppress = {};
  if (plan && data.settings.debt_in_forecast) {
    extra.push(...plan.occurrences(data.debts, debtExtras));
    const start = planStart(data, today);
    for (const d of data.debts) if (d.linked_bill_id) suppress[d.linked_bill_id] = start;
  }
  return new Forecast(source || data, end, today, extra, suppress);
}

// ---------------------------------------------------------------- sync
function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
const body = (r) => { const { updated, ...rest } = r; return canon(rest); };
const clone = (x) => JSON.parse(JSON.stringify(x));

// Mark what changed in `cur` since `prev` (the last saved copy). Mirrors sync.stamp().
export function stamp(prev, cur, now = nowUTC()) {
  for (const attr of ["items", "debts"]) {
    const old = new Map(prev ? prev[attr].map((x) => [x.id, body(x)]) : []);
    for (const x of cur[attr]) if (!x.updated || old.get(x.id) !== body(x)) { x.updated = now; delete cur.deleted[x.id]; }
    if (prev) {
      const live = new Set(cur[attr].map((x) => x.id));
      for (const id of old.keys()) if (!live.has(id) && !cur.deleted[id]) cur.deleted[id] = now;
    }
  }
  if (prev) {
    const before = new Set(prev.checkpoints.map((c) => c.id));
    for (const c of cur.checkpoints) if (!before.has(c.id)) delete cur.deleted[c.id];
    const live = new Set(cur.checkpoints.map((c) => c.id));
    for (const c of prev.checkpoints) if (!live.has(c.id) && !cur.deleted[c.id]) cur.deleted[c.id] = now;
    if (SHARED_SETTINGS.some((k) => canon(prev.settings[k]) !== canon(cur.settings[k]))) cur.settings_updated = now;
  }
  if (!cur.settings_updated) cur.settings_updated = now;
  const cutoff = new Date(Date.now() - 365 * MS).toISOString().slice(0, 11);
  for (const [k, v] of Object.entries(cur.deleted)) if (v < cutoff) delete cur.deleted[k];
}

// Combine two copies; the newest version of each record wins. Mirrors sync.merge().
export function merge(local, remote) {
  const out = clone(local);
  const deleted = { ...local.deleted };
  for (const [k, v] of Object.entries(remote.deleted || {})) if (v > (deleted[k] || "")) deleted[k] = v;
  const pick = (mine, theirs) => {
    const byId = new Map(mine.map((x) => [x.id, x]));
    for (const x of theirs) { const cur = byId.get(x.id); if (!cur || x.updated > cur.updated) byId.set(x.id, clone(x)); }
    return [...byId.values()].filter((x) => !(x.id in deleted) || deleted[x.id] < x.updated);
  };
  out.items = pick(out.items, remote.items);
  out.debts = pick(out.debts, remote.debts);
  const cps = new Map(out.checkpoints.map((c) => [c.id, c]));
  for (const c of remote.checkpoints) if (!cps.has(c.id)) cps.set(c.id, clone(c));
  const byDate = new Map();
  for (const c of cps.values()) {
    if (c.id in deleted) continue;
    const cur = byDate.get(c.date);
    if (!cur || c.created_at > cur.created_at) byDate.set(c.date, c);
  }
  out.checkpoints = [...byDate.values()];
  out.card_paid = [...new Set([...local.card_paid, ...remote.card_paid])].sort();
  out.deleted = deleted;
  if (remote.settings_updated > local.settings_updated) {
    for (const k of SHARED_SETTINGS) if (k in remote.settings) out.settings[k] = remote.settings[k];
    out.settings_updated = remote.settings_updated;
  }
  return out;
}

export function sameData(a, b) {
  const strip = (d) => { const { saved_at, device, ...rest } = d; return canon(rest); };
  return strip(a) === strip(b);
}

// ---------------------------------------------------------------- reminders (.ics)
// Port of balance_tracker/reminders.py — cross-checked in tests/test_web_engine.py.
export function fmtMoney(cents, symbol = "$", signed = false) {
  const body = symbol + (Math.abs(cents) / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return cents < 0 ? "−" + body : signed && cents > 0 ? "+" + body : body;
}
const cpCmp = (a, b) => { const A = Array.from(a), B = Array.from(b);
  for (let i = 0; i < Math.min(A.length, B.length); i++) { const d = A[i].codePointAt(0) - B[i].codePointAt(0); if (d) return d; }
  return A.length - B.length; };

export function collectReminders(data, plan, today, { months = 6, cardCharges = true, debtPayments = true, bills = false,
  paydays = false, daysBefore = 1 } = {}) {
  const sym = data.settings.currency_symbol || "$";
  const end = addMonths(today, months);
  const out = [];
  for (const item of data.items) {
    const card = item.paid_with ? findDebt(data, item.paid_with) : null;
    const want = (card && cardCharges) || (!card && item.kind !== "income" && bills) || (item.kind === "income" && paydays);
    if (!want) continue;
    for (const o of occurrences(item, today, end)) {
      const amt = fmtMoney(Math.abs(o.amount), sym);
      const iso = toISO(o.date);
      if (card) out.push({ uid: `card-${item.id}-${iso}`, day: o.date, title: `💳 Pay ${card.name} ${amt} (${item.name})`,
        detail: `${item.name} is charged to ${card.name} today. Pay ${amt} from chequing right away so no interest builds up.`, daysBefore: 0 });
      else if (item.kind === "income") out.push({ uid: `pay-${item.id}-${iso}`, day: o.date, title: `💰 ${item.name} ${amt}`,
        detail: `${item.name} should land today.`, daysBefore: 0 });
      else out.push({ uid: `bill-${item.id}-${iso}`, day: o.date, title: `🧾 ${item.name} ${amt}`,
        detail: `${item.name} comes out of chequing today.`, daysBefore });
    }
  }
  if (debtPayments && plan) {
    const names = new Map(data.debts.map((d) => [d.id, d.name]));
    const byKey = new Map();
    for (const p of plan.payments) {
      if (p.date < today || p.date > end) continue;
      const k = `${p.debt_id}|${p.date}`;
      const cur = byKey.get(k) || { id: p.debt_id, d: p.date, mins: 0, extra: 0 };
      if (p.extra) cur.extra += p.amount; else cur.mins += p.amount;
      byKey.set(k, cur);
    }
    for (const { id, d, mins, extra } of [...byKey.values()].sort((a, b) => a.d - b.d)) {
      const name = names.get(id) || "Debt";
      const total = fmtMoney(mins + extra, sym);
      const parts = [mins ? `minimum ${fmtMoney(mins, sym)}` : "", extra ? `extra ${fmtMoney(extra, sym)}` : ""].filter(Boolean);
      out.push({ uid: `debt-${id}-${toISO(d)}`, day: d, title: `💳 ${name} payment ${total}`,
        detail: `Payoff plan: pay ${total} to ${name} (${parts.join(" + ")}).`, daysBefore });
    }
  }
  return out.sort((a, b) => (a.day - b.day) || cpCmp(a.title, b.title));
}

const icsEsc = (t) => t.replace(/\\/g, "\\\\").replace(/;/g, "\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
function icsFold(line) {
  const enc = new TextEncoder();
  const out = [];
  let cur = "", size = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (size + n > 74) { out.push(cur); cur = " "; size = 1; }
    cur += ch; size += n;
  }
  out.push(cur);
  return out.join("\r\n");
}
export function toICS(reminders, at = "09:00", calendarName = "Balance Tracker", now = new Date()) {
  const [hh, mm] = at.split(":").map(Number);
  const p2 = (x) => String(x).padStart(2, "0");
  const stamp = now.toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  const local = (day, minutes) => {
    const t = hh * 60 + mm + minutes;
    const { y, m, d } = ymd(day + Math.floor(t / 1440)); // past midnight rolls to the next day
    const tt = t % 1440;
    return `${y}${p2(m)}${p2(d)}T${p2(Math.floor(tt / 60))}${p2(tt % 60)}00`;
  };
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Balance Tracker//Reminders//EN", "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH", `X-WR-CALNAME:${icsEsc(calendarName)}`];
  for (const r of reminders) {
    lines.push("BEGIN:VEVENT", `UID:${r.uid}@balance-tracker`, `DTSTAMP:${stamp}`, `DTSTART:${local(r.day, 0)}`,
      `DTEND:${local(r.day, 15)}`, `SUMMARY:${icsEsc(r.title)}`, `DESCRIPTION:${icsEsc(r.detail)}`, "TRANSP:TRANSPARENT",
      "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${icsEsc(r.title)}`, "TRIGGER:PT0M", "END:VALARM");
    if (r.daysBefore) lines.push("BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${icsEsc("Coming up: " + r.title)}`,
      `TRIGGER:-P${r.daysBefore}D`, "END:VALARM");
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.map(icsFold).join("\r\n") + "\r\n";
}

// CSV of forecast entries (same columns as the desktop export)
export function ledgerCSV(entries) {
  const q = (v) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = [["Date", "Description", "Category", "Type", "Amount", "Balance"]];
  for (const e of entries) rows.push([toISO(e.date), e.description, e.category, e.kind, (e.amount / 100).toFixed(2), (e.balance / 100).toFixed(2)]);
  return "\ufeff" + rows.map((r) => r.map(q).join(",")).join("\r\n") + "\r\n";
}
