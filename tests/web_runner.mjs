// Runs web/engine.js over scenarios from tests/test_web_engine.py and prints results as JSON.
import { readFileSync } from "node:fs";
import * as E from "../web/engine.js";

const scenarios = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = scenarios.map((sc) => {
  if (sc.reminders) {
    const data = E.normData(sc.data);
    const today = E.toDay(sc.today);
    const plan = data.debts.length ? E.makePlan(data, today) : null;
    const r = E.collectReminders(data, plan, today, sc.reminders);
    return { reminders: r.map((x) => [x.uid, E.toISO(x.day), x.title, x.detail, x.daysBefore]),
      ics: E.toICS(r, sc.at).replace(/DTSTAMP:\S+/g, "DTSTAMP:X") };
  }
  if (sc.merge) {
    const a = E.normData(sc.merge[0]), b = E.normData(sc.merge[1]);
    return { merged: E.merge(a, b) };
  }
  const data = E.normData(sc.data);
  const today = E.toDay(sc.today);
  const plan = data.debts.length ? E.makePlan(data, today) : null;
  const f = E.fullForecast(data, plan, today, E.projectionEnd(data, today));
  const res = {
    daily: [...f.daily].map(([d, v]) => [E.toISO(d), v]),
    entries: f.entries.map((e) => [E.toISO(e.date), e.kind, e.description, e.amount, e.balance]),
    monthly: data.items.map(E.monthlyEquivalent),
    next: data.items.map((i) => { const o = E.nextOccurrence(i, today); return o ? E.toISO(o.date) : null; }),
  };
  const t = E.monthlyTotals(data.items, today);
  res.totals = [t.income, t.bills, t.net];
  res.categories = E.billsByCategory(data.items, today).map((c) => [c.category, c.monthly, c.share]);
  res.cards = E.unpaidCardCharges(data, today, 14).map((c) => [E.toISO(c.occurrence.date), c.key, c.amount]);
  const u = E.unplannedSummary(f, today);
  res.unplanned = [u.thisMonth, u.average, u.monthsTracked, u.total, u.checkins];
  const o = E.paydayOutlook(f, today, data.settings.low_balance_threshold);
  res.payday = o === null ? null : [o.payday === null ? null : E.toISO(o.payday), o.pay, o.days, o.bills, o.billCount,
    o.lowest ? [E.toISO(o.lowest[0]), o.lowest[1]] : null, o.daily];
  res.changes = (sc.changes || []).map(([i, when]) => [i, when, ...E.changeAmountFrom(data.items[i], E.toDay(when), 4321, "cont")]);
  if (plan) {
    res.payments = plan.payments.map((p) => [E.toISO(p.date), p.debt_id, p.amount, p.extra]);
    res.interest = plan.totalInterest;
    res.debt_free = plan.debtFree === null ? null : E.toISO(plan.debtFree);
    res.rows = plan.monthRows(today, 12).map(([m, per, x]) => [E.toISO(m), Object.fromEntries(per), x]);
    for (const strat of ["avalanche", "snowball"]) for (const mode of ["minimum", "fixed", "auto"]) {
      const p = E.makePlan(data, today, strat, mode);
      res[`${strat}-${mode}`] = [p.totalInterest, p.payments.length, p.debtFree === null ? null : E.toISO(p.debtFree)];
    }
  }
  return res;
});
process.stdout.write(JSON.stringify(out));
