// Balance Tracker — iPhone web app. All data stays on the phone (localStorage);
// syncing with the PC happens through a file in iCloud Drive.
import * as E from "./engine.js";
import * as L from "./lock.js";

const KEY = "bt-data-v1";
const META = "bt-meta-v1";
const SYNC_NAME = "BalanceTracker-sync.json";
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (x) => JSON.parse(JSON.stringify(x));

let data, saved, meta, today, plan, fc;
let tab = "home";
let locked = L.enabled();
let hiddenAt = null;
const ui = { range: 3, everyDay: false, daysAhead: 60, billFilter: "all" };

// ------------------------------------------------------------------ storage
function load() {
  try { data = E.normData(JSON.parse(localStorage.getItem(KEY))); } catch { data = E.emptyData(); }
  try { meta = { unsent: false, lastSync: null, lastPrompt: null, ...JSON.parse(localStorage.getItem(META) || "{}") }; }
  catch { meta = { unsent: false, lastSync: null, lastPrompt: null }; }
  saved = clone(data);
}
function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(data)); localStorage.setItem(META, JSON.stringify(meta)); }
  catch (e) { toast("Couldn't save on this phone: " + e.message); }
}
let undoSnap = null;
function save(msg, undoable = false) {
  if (undoable) undoSnap = clone(saved);
  E.stamp(saved, data);
  saved = clone(data);
  meta.unsent = true;
  persist();
  refresh();
  if (msg) toast(msg, undoable ? undo : null);
}
function undo() {
  if (!undoSnap) return;
  data = E.normData(undoSnap);
  undoSnap = null;
  save("Undone");
}

// ------------------------------------------------------------------ compute
function recompute() {
  today = E.todayDay();
  plan = data.debts.length && E.startCheckpoint(data) ? E.makePlan(data, today) : null;
  fc = E.fullForecast(data, plan, today, E.projectionEnd(data, today));
}
function refresh() { recompute(); render(); }
const build = (extra = [], debtExtras = true, source = null, end = null) =>
  E.fullForecast(data, plan, today, end ?? E.projectionEnd(data, today), extra, debtExtras, source);

// ------------------------------------------------------------------ format
function money(c, signed = false) {
  if (c === null || c === undefined) return "—";
  const body = (data.settings.currency_symbol || "$") +
    (Math.abs(c) / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return c < 0 ? "−" + body : signed && c > 0 ? "+" + body : body;
}
function moneyShort(c) {
  const sym = data.settings.currency_symbol || "$";
  const v = Math.abs(c / 100), sign = c < 0 ? "−" : "";
  if (v >= 10000) return `${sign}${sym}${Math.round(v / 1000)}k`;
  if (v >= 1000) return `${sign}${sym}${(v / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${sign}${sym}${Math.round(v)}`;
}
const parseMoney = (s) => { const v = parseFloat(String(s).replace(/[^0-9.\-]/g, "")); return isNaN(v) ? 0 : Math.round(v * 100); };
const moneyInput = (c) => (c ? (c / 100).toFixed(2) : "");
const fmtDate = (n, opts) => new Date(n * 86400000).toLocaleDateString("en-US", { timeZone: "UTC", ...opts });
function niceDate(n) {
  if (n === today) return "Today";
  if (n === today + 1) return "Tomorrow";
  if (n === today - 1) return "Yesterday";
  const sameYear = E.ymd(n).y === E.ymd(today).y;
  return fmtDate(n, sameYear ? { weekday: "short", month: "short", day: "numeric" } : { month: "short", day: "numeric", year: "numeric" });
}
const longDate = (n) => fmtDate(n, { weekday: "long", month: "long", day: "numeric" });
const tone = (bal) => (bal === null ? "" : bal < 0 ? "neg" : bal < data.settings.low_balance_threshold ? "warn" : "");
const ordinal = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
function monthsAway(d) {
  const A = E.ymd(today), B = E.ymd(d);
  const m = (B.y - A.y) * 12 + B.m - A.m;
  if (m <= 0) return "this month";
  const y = Math.floor(m / 12), mm = m % 12;
  return "in " + [y ? `${y} yr` : "", mm ? `${mm} mo` : ""].filter(Boolean).join(" ");
}

// ------------------------------------------------------------------ toast
let toastTimer;
function toast(text, action = null, label = "Undo") {
  const t = $("#toast");
  t.innerHTML = `<span>${esc(text)}</span>` + (action ? `<button>${label}</button>` : "");
  if (action) t.querySelector("button").onclick = () => { t.classList.remove("show"); action(); };
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), action ? 5000 : 2600);
}

// ------------------------------------------------------------------ render
function topbar(title) {
  return `<div class="topbar"><h1>${esc(title)}</h1>
    <button class="iconbtn" data-act="sync" aria-label="Sync with PC">⟳${meta.unsent ? '<span class="dot"></span>' : ""}</button></div>`;
}
function render() {
  if (locked) { renderLock(); return; }
  $("#tabs").classList.remove("hidden");
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  const views = { home: viewHome, days: viewDays, bills: viewBills, debts: viewDebts, more: viewMore };
  $("#app").innerHTML = views[tab]();
  if (tab === "home") mountChart();
}

// ---------- home
function viewHome() {
  const s = data.settings;
  if (!E.startCheckpoint(data)) return viewWelcome();
  const bal = fc.balanceOn(today);
  const last = E.latestCheckpoint(data);
  const ago = today - E.toDay(last.date);
  const agoText = ago <= 0 ? "today" : ago === 1 ? "yesterday" : `${ago} days ago`;
  const horizon = E.horizonEnd(data, today);
  let html = topbar(s.account_name);

  html += `<div class="card hero"><div class="label">Balance today</div>
    <div class="big num ${tone(bal)}">${money(bal)}</div>
    <div class="muted small">Last checked in ${agoText}</div>
    <div class="actions"><button class="btn primary grow" data-act="checkin">Check in balance</button>
    <button class="btn grow" data-act="afford">Can I afford it?</button></div></div>`;

  const neg = fc.firstBelow(0, today, horizon);
  const below = fc.firstBelow(s.low_balance_threshold, today, horizon);
  const when = (d) => (d === today ? "today" : d === today + 1 ? "tomorrow" : "on " + longDate(d));
  if (neg) html += `<div class="banner negative">⚠ You're projected to be in overdraft (${money(neg[1])}) ${when(neg[0])}.</div>`;
  else if (below && s.low_balance_threshold > 0) html += `<div class="banner warning">Balance dips below your ${money(s.low_balance_threshold)} cushion ${when(below[0])} (${money(below[1])}).</div>`;
  else if (ago >= 7) html += `<div class="banner warning">It's been ${ago} days since your last check-in.</div>`;

  const safe = fc.safeToSpend(today, 30, s.low_balance_threshold);
  const low = fc.lowest(today, horizon);
  const um = fc.unplannedByMonth().get(`${E.ymd(today).y}-${E.ymd(today).m}`) || 0;
  html += `<div class="stats">
    <div class="stat"><div class="t">Safe to spend</div><div class="v num ${safe < 0 ? "neg" : "pos"}">${money(Math.max(0, safe ?? 0))}</div><div class="s">next 30 days</div></div>
    <div class="stat"><div class="t">Lowest ahead</div><div class="v num ${tone(low?.[1] ?? null)}">${low ? moneyShort(low[1]) : "—"}</div><div class="s">${low ? niceDate(low[0]) : ""}</div></div>
    <div class="stat"><div class="t">Unplanned</div><div class="v num ${um < 0 ? "neg" : "pos"}">${moneyShort(Math.abs(um))}</div><div class="s">this month</div></div></div>`;

  const cards = cardCharges();
  if (cards.length) {
    html += `<div class="card"><h2>💳 Pay your card</h2>`;
    for (const c of cards) {
      html += `<div class="row" style="padding:8px 0;border:0"><div class="main"><div class="title">${money(Math.abs(c.o.amount))} to ${esc(c.card.name)}</div>
        <div class="sub ${c.o.date < today ? "neg" : ""}">${esc(c.o.item.name)} · ${niceDate(c.o.date)}</div></div>
        <button class="chip" data-act="cardpaid" data-key="${esc(c.key)}">✓ Paid</button></div>`;
    }
    html += `</div>`;
  }

  html += `<div class="card"><h2>Forecast<span class="right chips">${[[1, "1M"], [3, "3M"], [6, "6M"], [12, "1Y"]]
    .map(([m, t]) => `<button class="chip ${ui.range === m ? "on" : ""}" data-act="range" data-m="${m}">${t}</button>`).join("")}</span></h2>
    <div class="chart" id="chart"></div><div class="tiny muted">Touch and drag to see any day</div></div>`;

  const up = fc.entriesBetween(today, today + 14).filter((e) => e.kind === "income" || e.kind === "bill");
  html += `<div class="card" style="padding:16px 16px 6px"><h2>Coming up · 14 days</h2>`;
  html += up.length ? up.map((e) => `<div class="row" style="padding:8px 0"><div class="main"><div class="title">${esc(e.description)}</div>
    <div class="sub">${niceDate(e.date)}</div></div><div class="end"><div class="num ${e.amount > 0 ? "pos" : ""}">${money(e.amount, true)}</div>
    <div class="sub num ${tone(e.balance)}">${money(e.balance)}</div></div></div>`).join("") : `<div class="empty">Nothing scheduled</div>`;
  html += `</div>`;

  const inc = data.items.filter((i) => i.active && i.kind === "income").reduce((a, i) => a + E.monthlyEquivalent(i), 0);
  const bills = -data.items.filter((i) => i.active && i.kind === "bill").reduce((a, i) => a + E.monthlyEquivalent(i), 0);
  html += `<div class="card"><h2>Monthly snapshot</h2>
    <div class="kv"><span class="muted">Income</span><span class="num pos bold">${money(inc)}</span></div>
    <div class="kv"><span class="muted">Bills</span><span class="num bold">${money(bills)}</span></div>
    <div class="kv"><span class="muted">Left over</span><span class="num bold ${inc - bills >= 0 ? "pos" : "neg"}">${money(inc - bills)}</span></div>
    ${plan ? `<div class="kv"><span class="muted">Debt-free by</span><span class="bold ${plan.debtFree ? "pos" : "neg"}">${plan.debtFree ? fmtDate(plan.debtFree, { month: "long", year: "numeric" }) : "10+ years"}</span></div>` : ""}</div>`;
  return html;
}

function viewWelcome() {
  return `<div style="padding-top:40px;text-align:center"><img src="icons/icon-192.png" width="84" height="84" style="border-radius:20px" alt="">
    <h1 style="font-size:30px;margin:16px 0 6px">Balance Tracker</h1>
    <p class="muted">See your chequing balance day by day, plan your bills and pay down debt.</p></div>
    <div class="card"><h2>Use it with your PC</h2><p class="muted small" style="margin-top:0">Already using Balance Tracker on your PC with iPhone sync turned on?
    Pick the sync file from iCloud Drive → Balance Tracker.</p>
    <button class="btn primary block" data-act="pullsync">Choose ${SYNC_NAME}</button></div>
    <div class="card"><h2>Start fresh on this phone</h2><button class="btn block" data-act="start">Enter my current balance</button></div>
    <p class="hint" style="text-align:center">Tip: tap Share → Add to Home Screen so it opens like an app and keeps your data.</p>`;
}

function cardCharges() {
  const out = [];
  for (const item of data.items) {
    const card = item.paid_with ? E.findDebt(data, item.paid_with) : null;
    if (!card) continue;
    for (const o of E.occurrences(item, today - 14, today)) {
      const key = `${item.id}|${E.toISO(o.date)}`;
      if (!data.card_paid.includes(key)) out.push({ o, card, key });
    }
  }
  return out.sort((a, b) => a.o.date - b.o.date);
}

// ---------- chart
function mountChart() {
  const el = $("#chart");
  if (!el) return;
  const s = data.settings;
  const end = Math.min(E.addMonths(today, ui.range), fc.end);
  const begin = Math.max(fc.start, today - Math.max(7, ui.range * 5));
  const pts = [];
  for (let d = begin; d <= end; d++) if (fc.daily.has(d)) pts.push([d, fc.daily.get(d)]);
  if (!pts.length) return;
  const vals = pts.map((p) => p[1]).concat([0, s.low_balance_threshold]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.1 || 1000; lo -= pad; hi += pad;
  const W = 1000, H = 170, n = pts.length;
  const x = (i) => (i / n) * W, y = (v) => H - ((v - lo) / (hi - lo)) * H;
  let path = "";
  pts.forEach(([, v], i) => { path += (i ? `L${x(i)},${y(v)}` : `M0,${y(v)}`) + `L${x(i + 1)},${y(v)}`; });
  const ti = pts.findIndex((p) => p[0] >= today);
  const zero = y(0);
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue("--accent").trim(), negc = css.getPropertyValue("--negative").trim(),
    warn = css.getPropertyValue("--warning").trim(), muted = css.getPropertyValue("--muted").trim(), border = css.getPropertyValue("--border").trim();
  const months = pts.map((p, i) => [p[0], i]).filter(([d]) => E.ymd(d).d === 1);
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H + 20}" preserveAspectRatio="none">
    <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${accent}" stop-opacity=".28"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></linearGradient>
    <clipPath id="above"><rect x="0" y="-5" width="${W}" height="${Math.max(0, zero + 5)}"/></clipPath>
    <clipPath id="below"><rect x="0" y="${zero}" width="${W}" height="${H + 10}"/></clipPath></defs>
    ${months.map(([, i]) => `<line x1="${x(i)}" x2="${x(i)}" y1="0" y2="${H}" stroke="${border}" stroke-dasharray="4 6" vector-effect="non-scaling-stroke"/>`).join("")}
    <path d="${path}L${W},${H}L0,${H}Z" fill="url(#g)" clip-path="url(#above)"/>
    <path d="${path}" fill="none" stroke="${accent}" stroke-width="2.4" vector-effect="non-scaling-stroke" clip-path="url(#above)" stroke-linejoin="round"/>
    <path d="${path}" fill="none" stroke="${negc}" stroke-width="2.4" vector-effect="non-scaling-stroke" clip-path="url(#below)" stroke-linejoin="round"/>
    ${lo < 0 && hi > 0 ? `<line x1="0" x2="${W}" y1="${zero}" y2="${zero}" stroke="${negc}" stroke-width="1" vector-effect="non-scaling-stroke" opacity=".6"/>` : ""}
    ${s.low_balance_threshold > 0 ? `<line x1="0" x2="${W}" y1="${y(s.low_balance_threshold)}" y2="${y(s.low_balance_threshold)}" stroke="${warn}" stroke-dasharray="6 6" vector-effect="non-scaling-stroke"/>` : ""}
    ${ti >= 0 ? `<line x1="${x(ti)}" x2="${x(ti)}" y1="0" y2="${H}" stroke="${muted}" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"/>` : ""}
    <line id="cursor" x1="0" x2="0" y1="0" y2="${H}" stroke="${muted}" vector-effect="non-scaling-stroke" visibility="hidden"/>
  </svg>${months.map(([d, i]) => `<span class="tiny muted" style="position:absolute;bottom:0;left:calc(${(i / n) * 100}% + 3px)">${fmtDate(d, { month: "short" })}</span>`).join("")}
  <span class="tiny muted" style="position:absolute;top:-2px;left:4px">${moneyShort(hi)}</span>
  <div class="tip hidden" id="tip"></div>`;
  const tip = $("#tip", el), cursor = $("#cursor", el);
  const show = (ev) => {
    const r = el.getBoundingClientRect();
    const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
    const i = Math.max(0, Math.min(n - 1, Math.floor((px / r.width) * n)));
    const [d, v] = pts[i];
    tip.classList.remove("hidden");
    tip.innerHTML = `<span class="muted">${niceDate(d)}</span> <b class="num ${tone(v)}">${money(v)}</b>`;
    tip.style.left = Math.min(r.width - 80, Math.max(80, px)) + "px";
    cursor.setAttribute("x1", x(i + 0.5)); cursor.setAttribute("x2", x(i + 0.5)); cursor.setAttribute("visibility", "visible");
  };
  const hide = () => { tip.classList.add("hidden"); cursor.setAttribute("visibility", "hidden"); };
  el.addEventListener("touchstart", show, { passive: true });
  el.addEventListener("touchmove", show, { passive: true });
  el.addEventListener("touchend", hide);
  el.addEventListener("mousemove", show);
  el.addEventListener("mouseleave", hide);
}

// ---------- day by day
function viewDays() {
  let html = topbar("Day by day");
  if (fc.empty) return html + `<div class="empty">Enter a starting balance first.</div>`;
  html += `<div class="chips" style="margin-bottom:6px">${[30, 60, 90, 180].map((d) => `<button class="chip ${ui.daysAhead === d ? "on" : ""}" data-act="ahead" data-d="${d}">${d} days</button>`).join("")}
    <button class="chip ${ui.everyDay ? "on" : ""}" data-act="everyday">Every day</button></div>`;
  const a = Math.max(fc.start, today - 7), b = Math.min(today + ui.daysAhead, fc.end);
  const byDay = new Map();
  for (const e of fc.entriesBetween(a, b)) { if (!byDay.has(e.date)) byDay.set(e.date, []); byDay.get(e.date).push(e); }
  let inc = 0, out = 0;
  for (let d = a; d <= b; d++) {
    const es = byDay.get(d);
    if (!es && !ui.everyDay) continue;
    const bal = fc.balanceOn(d);
    html += `<div class="dayhead ${d === today ? "today" : ""}"><span>${niceDate(d)}</span><span class="num ${tone(bal)}">${money(bal)}</span></div>`;
    if (!es) { html += `<div class="list"><div class="quiet"><span>Nothing scheduled</span></div></div>`; continue; }
    html += `<div class="list">`;
    for (const e of es) {
      const icon = e.kind === "income" ? ["in", "▲"] : e.kind === "checkin" || e.kind === "start" ? ["ci", "✓"] : ["out", "▼"];
      if (e.kind === "income") inc += e.amount; else if (e.kind === "bill") out += e.amount;
      const tappable = e.item_id || e.kind === "checkin";
      html += `<div class="row ${tappable ? "tap" : ""}" ${tappable ? `data-act="entry" data-item="${esc(e.item_id || "")}" data-sched="${e.scheduled ?? ""}" data-cp="${esc(e.checkpoint_id || "")}" data-amt="${e.amount}" data-date="${e.date}"` : ""}>
        <div class="badge ${icon[0]}">${icon[1]}</div><div class="main"><div class="title">${esc(e.description)}${e.overridden ? ' <span class="muted small">(changed)</span>' : ""}</div>
        <div class="sub">${esc(e.category || (e.kind === "checkin" ? "Check-in" : e.kind === "start" ? "Starting balance" : ""))}</div></div>
        <div class="end"><div class="num ${e.kind === "income" ? "pos" : e.kind === "checkin" && e.amount < 0 ? "neg" : ""}">${e.kind === "start" ? "" : money(e.amount, true)}</div>
        <div class="sub num ${tone(e.balance)}">${money(e.balance)}</div></div></div>`;
    }
    html += `</div>`;
  }
  html += `<p class="hint">In this range: income ${money(inc)} · bills ${money(-out)}. Tap a line to skip it or change the amount just once.</p>`;
  return html;
}

// ---------- bills
function viewBills() {
  let html = topbar("Income & Bills");
  const inc = data.items.filter((i) => i.active && i.kind === "income").reduce((a, i) => a + E.monthlyEquivalent(i), 0);
  const bills = -data.items.filter((i) => i.active && i.kind === "bill").reduce((a, i) => a + E.monthlyEquivalent(i), 0);
  html += `<div class="stats"><div class="stat"><div class="t">Income/mo</div><div class="v num pos">${moneyShort(inc)}</div></div>
    <div class="stat"><div class="t">Bills/mo</div><div class="v num">${moneyShort(bills)}</div></div>
    <div class="stat"><div class="t">Left over</div><div class="v num ${inc >= bills ? "pos" : "neg"}">${moneyShort(inc - bills)}</div></div></div>`;
  html += `<div class="seg" style="margin-bottom:14px">${[["all", "All"], ["income", "Income"], ["bill", "Bills"]]
    .map(([k, t]) => `<button class="${ui.billFilter === k ? "on" : ""}" data-act="billfilter" data-k="${k}">${t}</button>`).join("")}</div>`;
  const items = data.items.filter((i) => ui.billFilter === "all" || i.kind === ui.billFilter);
  const nexts = new Map(items.map((i) => [i.id, E.nextOccurrence(i, today)]));
  items.sort((a, b) => (!a.active - !b.active) || ((a.kind !== "income") - (b.kind !== "income")) ||
    ((nexts.get(a.id)?.date ?? 1e9) - (nexts.get(b.id)?.date ?? 1e9)) || a.name.localeCompare(b.name));
  if (!items.length) html += `<div class="empty">Nothing here yet — tap + to add your paycheque and bills.</div>`;
  else {
    html += `<div class="list">`;
    for (const i of items) {
      const n = nexts.get(i.id);
      const card = i.paid_with ? E.findDebt(data, i.paid_with) : null;
      let freq = E.FREQUENCIES[i.frequency];
      if (i.frequency === "semimonthly") freq += ` (${ordinal(E.ymd(E.toDay(i.start_date)).d)} & ${i.second_day >= 31 ? "last day" : ordinal(i.second_day)})`;
      const dim = !i.active || !n;
      html += `<div class="row tap" data-act="edititem" data-id="${esc(i.id)}" style="${dim ? "opacity:.55" : ""}">
        <div class="badge ${i.kind === "income" ? "in" : "out"}">${i.kind === "income" ? "▲" : card ? "💳" : "▼"}</div>
        <div class="main"><div class="title">${esc(i.name)}</div><div class="sub">${freq}${card ? " · on " + esc(card.name) : ""}${i.category ? " · " + esc(i.category) : ""}</div></div>
        <div class="end"><div class="num bold ${i.kind === "income" ? "pos" : ""}">${money(E.signedAmount(i), true)}</div>
        <div class="sub">${!i.active ? "Paused" : n ? niceDate(n.date) : "Finished"}</div></div></div>`;
    }
    html += `</div>`;
  }
  html += `<button class="fab" data-act="additem" aria-label="Add">+</button>`;
  return html;
}

// ---------- debts
function viewDebts() {
  let html = topbar("Debts");
  const s = data.settings;
  if (!data.debts.length) {
    return html + `<div class="empty"><p>Add your credit cards, lines of credit and loans to get a payoff plan that keeps you above your cushion.</p>
      <button class="btn primary" data-act="adddebt">+ Add a debt</button></div>`;
  }
  const total = data.debts.reduce((a, d) => a + d.balance, 0);
  const interest = data.debts.reduce((a, d) => a + E.pyRound((d.balance * d.apr) / 1200), 0);
  if (!plan) return html + `<div class="empty">Enter a starting balance on Home first.</div>`;
  const mins = E.makePlan(data, today, null, "minimum");
  html += `<div class="stats"><div class="stat"><div class="t">Total owed</div><div class="v num neg">${moneyShort(total)}</div><div class="s">${moneyShort(interest)}/mo interest</div></div>
    <div class="stat"><div class="t">Debt-free</div><div class="v ${plan.debtFree ? "pos" : "neg"}">${plan.debtFree ? fmtDate(plan.debtFree, { month: "short", year: "2-digit" }) : "10+ yrs"}</div><div class="s">${plan.debtFree ? monthsAway(plan.debtFree) : "not on track"}</div></div>
    <div class="stat"><div class="t">Saved</div><div class="v num pos">${moneyShort(Math.max(0, mins.totalInterest - plan.totalInterest))}</div><div class="s">interest vs mins</div></div></div>`;
  const nxt = plan.nextExtra(today);
  html += `<div class="banner info">${nxt ? `👉 Next: pay <b>${money(nxt.amount)}</b> extra to <b>${esc(E.findDebt(data, nxt.debt_id)?.name)}</b> on ${longDate(nxt.date)} (on top of the minimum).`
    : s.debt_mode === "auto" ? "No spare money right now — keep paying the minimums. Extra kicks in as soon as your forecast has room above your cushion." : "Set a fixed extra amount below to speed things up."}</div>`;

  html += `<div class="card"><h2>Your plan</h2>
    <div class="seg" style="margin-bottom:10px">${Object.entries(E.DEBT_STRATEGIES).map(([k, t]) => `<button class="${s.debt_strategy === k ? "on" : ""}" data-act="strategy" data-k="${k}">${t}</button>`).join("")}</div>
    <div class="form" style="margin:0">
      <div class="field"><label>Extra money</label><select id="dmode" data-change="dmode"><option value="auto" ${s.debt_mode === "auto" ? "selected" : ""}>Max my cushion allows</option><option value="fixed" ${s.debt_mode === "fixed" ? "selected" : ""}>Fixed per month</option></select></div>
      ${s.debt_mode === "fixed" ? `<div class="field"><label>Per month</label><input id="dfixed" inputmode="decimal" placeholder="0.00" value="${moneyInput(s.debt_fixed_extra)}" data-change="dfixed"></div>` : ""}
      <div class="field toggle-row"><label>Show payments in Day by day</label><label class="switch"><input type="checkbox" data-change="dinfc" ${s.debt_in_forecast ? "checked" : ""}><span></span></label></div>
    </div></div>`;

  const order = new Map(plan.order.map((id, i) => [id, i + 1]));
  html += `<div class="dayhead"><span>Pay off in this order</span></div><div class="list">`;
  for (const d of [...data.debts].sort((a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99))) {
    const im = (d.balance * d.apr) / 1200;
    const mp = E.pyRound(E.minimumPayment(d, d.balance + im, im));
    const po = plan.payoff.get(d.id);
    const used = d.credit_limit ? Math.round((d.balance / d.credit_limit) * 100) : null;
    html += `<div class="row tap" data-act="editdebt" data-id="${esc(d.id)}"><div class="badge ci">${order.get(d.id) ?? "✓"}</div>
      <div class="main"><div class="title">${esc(d.name)}</div><div class="sub">${d.apr.toFixed(2)}% · min ${money(mp)}${used !== null ? ` · ${used}% used` : ""}</div></div>
      <div class="end"><div class="num bold">${money(d.balance)}</div><div class="sub ${po ? "" : "neg"}">${po ? "paid " + fmtDate(po, { month: "short", year: "2-digit" }) : "10+ years"}</div></div></div>`;
  }
  html += `</div>`;

  const rows = plan.monthRows(today, 12);
  html += `<div class="dayhead"><span>Payment schedule</span><span>12 months</span></div><div class="list">`;
  for (const [m, per, extra] of rows) {
    let tot = 0; per.forEach((v) => (tot += v));
    const parts = [...per].map(([id, v]) => `${esc(E.findDebt(data, id)?.name || "")} ${money(v)}`).join(" · ");
    html += `<div class="row"><div class="main"><div class="title">${fmtDate(m, { month: "long", year: "numeric" })}</div>
      <div class="sub" style="white-space:normal">${parts || "Nothing left to pay this month"}</div></div>
      <div class="end"><div class="num bold">${tot ? money(tot) : "—"}</div>${extra ? `<div class="sub pos num">+${money(extra)} extra</div>` : ""}</div></div>`;
  }
  html += `</div>`;

  html += `<div class="dayhead"><span>Compare</span></div><div class="list">`;
  const cmpRows = [["Minimums only", mins], ...Object.entries(E.DEBT_STRATEGIES).map(([k, t]) => [t, k === s.debt_strategy ? plan : E.makePlan(data, today, k)])];
  for (const [name, p] of cmpRows) {
    html += `<div class="row"><div class="main"><div class="title ${p === plan ? "accent" : ""}">${name}${p === plan ? " ✓" : ""}</div>
      <div class="sub">${p.debtFree ? "Debt-free " + fmtDate(p.debtFree, { month: "short", year: "numeric" }) : "10+ years"}</div></div>
      <div class="end"><div class="num">${money(p.totalInterest)}</div><div class="sub">interest</div></div></div>`;
  }
  html += `</div><button class="fab" data-act="adddebt" aria-label="Add debt">+</button>`;
  return html;
}

// ---------- more
function viewMore() {
  let html = topbar("More");
  const checkins = fc.checkins();
  const um = fc.unplannedByMonth();
  const thisM = um.get(`${E.ymd(today).y}-${E.ymd(today).m}`) || 0;
  html += `<div class="list">
    <div class="row tap" data-act="sync"><div class="badge ci">⟳</div><div class="main"><div class="title">Sync with my PC</div><div class="sub">${meta.lastSync ? "Last synced " + new Date(meta.lastSync).toLocaleString() : "Through iCloud Drive"}${meta.unsent ? " · changes to send" : ""}</div></div><div class="muted">›</div></div>
    <div class="row tap" data-act="history"><div class="badge ci">✓</div><div class="main"><div class="title">Check-in history</div><div class="sub">${checkins.length} check-ins · ${money(Math.abs(thisM))} ${thisM < 0 ? "unplanned" : "ahead"} this month</div></div><div class="muted">›</div></div>
    <div class="row tap" data-act="afford"><div class="badge">?</div><div class="main"><div class="title">Can I afford it?</div></div><div class="muted">›</div></div>
    <div class="row tap" data-act="settings"><div class="badge">⚙</div><div class="main"><div class="title">Settings</div><div class="sub">Cushion, theme, account name</div></div><div class="muted">›</div></div>
  </div><div class="list">
    <div class="row tap" data-act="export"><div class="badge">⇪</div><div class="main"><div class="title">Export a backup</div></div></div>
    <div class="row tap" data-act="import"><div class="badge">⇩</div><div class="main"><div class="title">Import a backup</div></div></div>
  </div><p class="hint">Your data is stored only on this phone (and in your iCloud Drive when you sync). Balance Tracker never sends it anywhere else.</p>`;
  return html;
}

// ------------------------------------------------------------------ sheets
const sheet = () => $("#sheet");
function openSheet(title, body, onMount) {
  const s = sheet();
  s.innerHTML = `<div class="grab"></div><header><h3>${esc(title)}</h3><button class="x" data-act="close" aria-label="Close">✕</button></header><div class="body">${body}</div>`;
  if (!s.open) s.showModal();
  s.querySelector(".body").scrollTop = 0;
  onMount?.(s);
}
function closeSheet() { if (sheet().open) sheet().close(); }
sheet().addEventListener("click", (e) => { if (e.target === sheet()) closeSheet(); });
const field = (label, input, cls = "") => `<div class="field ${cls}"><label>${label}</label>${input}</div>`;
const toggle = (label, id, on) => `<div class="field toggle-row"><label for="${id}">${label}</label><label class="switch"><input type="checkbox" id="${id}" ${on ? "checked" : ""}><span></span></label></div>`;
const opts = (obj, sel) => Object.entries(obj).map(([k, v]) => `<option value="${esc(k)}" ${k === sel ? "selected" : ""}>${esc(v)}</option>`).join("");
const val = (id) => $("#" + id, sheet())?.value ?? "";
const checked = (id) => !!$("#" + id, sheet())?.checked;

// ---------- check-in
function sheetCheckin() {
  const start = E.startCheckpoint(data);
  if (!start) return sheetStart();
  const body = `<p class="hint" style="padding-top:0">What does your bank app show right now? Any difference from the plan is logged as unplanned spending (or income).</p>
    <div class="form">${field("Date", `<input type="date" id="ci_date" value="${E.toISO(today)}" min="${start.date}" max="${E.toISO(today)}">`)}
    ${field("Actual balance", `<input id="ci_bal" inputmode="decimal" placeholder="0.00">`)}
    <div id="ci_inc_row">${toggle("Today's scheduled items already landed", "ci_inc", true)}</div>
    ${field("Note", `<input id="ci_note" placeholder="Optional — groceries, gas…" style="text-align:left">`)}</div>
    <div class="hint" id="ci_items"></div>
    <div class="result" id="ci_result"></div>
    <button class="btn primary block" data-act="savecheckin">Save check-in</button>`;
  openSheet("Balance check-in", body, (s) => {
    const upd = (first) => {
      const d = E.toDay(val("ci_date") || E.toISO(today));
      const temp = { ...data, checkpoints: data.checkpoints.filter((c) => c.date !== E.toISO(d)) };
      const todays = data.items.flatMap((i) => E.occurrences(i, d, d));
      $("#ci_inc_row", s).classList.toggle("hidden", !todays.length);
      $("#ci_items", s).textContent = todays.length ? "Scheduled that day: " + todays.map((o) => `${o.item.name} ${money(o.amount, true)}`).join(", ") : "";
      let projected = null;
      if (temp.checkpoints.length) {
        const f = build([], true, temp, d);
        projected = checked("ci_inc") || !todays.length ? f.balanceOn(d) : f.balanceBefore(d);
      }
      if (first && projected !== null) $("#ci_bal", s).value = (projected / 100).toFixed(2);
      const r = $("#ci_result", s);
      if (projected === null) { r.innerHTML = `<div class="muted">This replaces your starting balance.</div>`; return; }
      const diff = parseMoney(val("ci_bal")) - projected;
      r.innerHTML = `<div class="muted small">The plan expected ${money(projected)}</div>` + (diff < 0
        ? `<div class="big neg">${money(-diff)} unplanned spending</div>`
        : diff > 0 ? `<div class="big pos">${money(diff)} more than planned</div>` : `<div class="big pos">Right on plan ✓</div>`);
    };
    s.querySelectorAll("#ci_date,#ci_bal,#ci_inc").forEach((el) => el.addEventListener("input", () => upd(false)));
    upd(true);
  });
}
function saveCheckin() {
  const d = val("ci_date") || E.toISO(today);
  const cp = { date: d, balance: parseMoney(val("ci_bal")), includes_today: checked("ci_inc"), note: val("ci_note").trim(), created_at: E.nowLocal(), id: E.newId() };
  const start = E.startCheckpoint(data);
  if (start && d === start.date) { cp.includes_today = start.includes_today; cp.note = "Starting balance"; }
  E.addCheckpoint(data, cp);
  closeSheet();
  save("Check-in saved — forecast updated", true);
}

function sheetStart() {
  openSheet("Starting balance", `<p class="hint" style="padding-top:0">Enter what's in your chequing account today. You'll add paycheques and bills next.</p>
    <div class="form">${field("Account name", `<input id="st_name" value="${esc(data.settings.account_name)}">`)}
    ${field("Current balance", `<input id="st_bal" inputmode="decimal" placeholder="0.00">`)}
    ${field("As of", `<input type="date" id="st_date" value="${E.toISO(today)}">`)}
    ${toggle("Today's items already landed", "st_inc", true)}</div>
    <button class="btn primary block" data-act="savestart">Get started</button>`);
}

// ---------- items
function sheetItem(id = null, kind = "bill") {
  const it = id ? E.findItem(data, id) : null;
  const i = it || E.normItem({ name: "", amount: 0, kind, frequency: "monthly", start_date: E.toISO(today) });
  const cards = data.debts.filter((d) => d.kind !== "loan");
  const cats = [...new Set(data.items.map((x) => x.category).filter(Boolean))].sort();
  const body = `<div class="seg" style="margin-bottom:14px"><button class="${i.kind === "income" ? "on" : ""}" data-act="itkind" data-k="income">Income</button><button class="${i.kind === "bill" ? "on" : ""}" data-act="itkind" data-k="bill">Bill / expense</button></div>
    <input type="hidden" id="it_kind" value="${i.kind}">
    <div class="form">${field("Name", `<input id="it_name" value="${esc(i.name)}" placeholder="Paycheque, Rent…">`)}
    ${field("Amount", `<input id="it_amt" inputmode="decimal" placeholder="0.00" value="${moneyInput(i.amount)}">`)}
    ${cards.length ? field("Paid with", `<select id="it_card"><option value="">Chequing</option>${cards.map((c) => `<option value="${esc(c.id)}" ${i.paid_with === c.id ? "selected" : ""}>💳 ${esc(c.name)}</option>`).join("")}</select>`, "it-billonly") : ""}
    ${field("How often", `<select id="it_freq">${opts(E.FREQUENCIES, i.frequency)}</select>`)}
    ${field("First / next date", `<input type="date" id="it_start" value="${i.start_date}">`)}
    ${field("Second day", `<select id="it_second">${Array.from({ length: 31 }, (_, k) => `<option value="${k + 1}" ${i.second_day === k + 1 ? "selected" : ""}>${k + 1 === 31 ? "Last day" : ordinal(k + 1)}</option>`).join("")}</select>`, "it-semi")}
    ${toggle("Stops on a date", "it_hasend", !!i.end_date)}
    ${field("Ends", `<input type="date" id="it_end" value="${i.end_date || E.toISO(today + 365)}">`, "it-end")}
    ${field("On weekends", `<select id="it_wk">${opts(E.WEEKEND_RULES, i.weekend_rule)}</select>`)}
    ${field("Category", `<input id="it_cat" list="cats" value="${esc(i.category)}" placeholder="Optional"><datalist id="cats">${cats.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>`)}
    ${toggle("Include in forecast", "it_active", i.active)}</div>
    <div class="hint" id="it_preview"></div>
    <button class="btn primary block" data-act="saveitem" data-id="${esc(id || "")}">${id ? "Save" : "Add"}</button>
    ${id ? `<button class="btn danger block" style="margin-top:10px" data-act="delitem" data-id="${esc(id)}">Delete</button>` : ""}`;
  openSheet(id ? "Edit" : kind === "income" ? "Add income" : "Add bill", body, (s) => {
    const upd = () => {
      const f = val("it_freq");
      s.querySelectorAll(".it-semi").forEach((el) => el.classList.toggle("hidden", f !== "semimonthly"));
      s.querySelectorAll(".it-end").forEach((el) => el.classList.toggle("hidden", f === "once" || !checked("it_hasend")));
      $("#it_hasend", s).closest(".field").classList.toggle("hidden", f === "once");
      s.querySelectorAll(".it-billonly").forEach((el) => el.classList.toggle("hidden", val("it_kind") !== "bill"));
      const tmp = readItem(null);
      const dates = [];
      for (const sd of E.scheduledDates(tmp, today + 800, today)) {
        const p = E.shiftWeekend(sd, tmp.weekend_rule);
        if (p >= today) dates.push(fmtDate(p, { weekday: "short", month: "short", day: "numeric" }));
        if (dates.length === 5) break;
      }
      $("#it_preview", s).textContent = dates.length ? "Upcoming: " + dates.join(" · ") : "No upcoming dates.";
    };
    s.querySelectorAll("input,select").forEach((el) => el.addEventListener("input", upd));
    s.querySelectorAll("input,select").forEach((el) => el.addEventListener("change", upd));
    s._upd = upd;
    upd();
  });
}
function readItem(id) {
  const old = id ? E.findItem(data, id) : null;
  const kind = val("it_kind");
  return E.normItem({
    ...(old || {}), id: id || undefined, name: val("it_name").trim(), amount: parseMoney(val("it_amt")), kind,
    frequency: val("it_freq"), start_date: val("it_start") || E.toISO(today),
    end_date: checked("it_hasend") && val("it_freq") !== "once" ? val("it_end") : null,
    second_day: Number(val("it_second") || 31), weekend_rule: val("it_wk"), category: val("it_cat").trim(),
    active: checked("it_active"), paid_with: kind === "bill" ? val("it_card") : "", overrides: old?.overrides || {},
  });
}

// ---------- debts
function sheetDebt(id = null) {
  const d = id ? E.findDebt(data, id) : E.normDebt({ name: "", balance: 0, apr: 0, kind: "credit_card", due_day: E.ymd(today).d, min_amount: 1000, min_percent: 1, min_plus_interest: true });
  const bills = data.items.filter((i) => i.kind === "bill");
  const body = `<div class="form">${field("Type", `<select id="db_kind">${opts(E.DEBT_KINDS, d.kind)}</select>`)}
    ${field("Name", `<input id="db_name" value="${esc(d.name)}" placeholder="Visa, Line of credit…">`)}
    ${field("Balance owed", `<input id="db_bal" inputmode="decimal" placeholder="0.00" value="${moneyInput(d.balance)}">`)}
    ${field("Interest (APR %)", `<input id="db_apr" inputmode="decimal" placeholder="19.99" value="${d.apr || ""}">`)}
    ${field("Credit limit", `<input id="db_limit" inputmode="decimal" placeholder="Optional" value="${moneyInput(d.credit_limit)}">`)}
    ${field("Due day", `<select id="db_due">${Array.from({ length: 31 }, (_, k) => `<option value="${k + 1}" ${d.due_day === k + 1 ? "selected" : ""}>${k + 1 === 31 ? "Last day" : ordinal(k + 1)}</option>`).join("")}</select>`)}
    ${field("Minimum $", `<input id="db_minamt" inputmode="decimal" value="${moneyInput(d.min_amount)}" placeholder="0.00">`)}
    ${field("or % of balance", `<input id="db_minpct" inputmode="decimal" value="${d.min_percent || ""}" placeholder="0">`)}
    ${toggle("Plus that month's interest", "db_plus", d.min_plus_interest)}
    ${field("Already a bill?", `<select id="db_link"><option value="">No</option>${bills.map((b) => `<option value="${esc(b.id)}" ${d.linked_bill_id === b.id ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>`)}</div>
    <p class="hint">If you already added this payment under Bills, pick it in “Already a bill?” so it isn't counted twice.</p>
    <button class="btn primary block" data-act="savedebt" data-id="${esc(id || "")}">${id ? "Save" : "Add debt"}</button>
    ${id ? `<button class="btn danger block" style="margin-top:10px" data-act="deldebt" data-id="${esc(id)}">Delete</button>` : ""}`;
  openSheet(id ? "Edit debt" : "Add a debt", body);
}
function saveDebt(id) {
  const old = id ? E.findDebt(data, id) : null;
  const bal = parseMoney(val("db_bal"));
  const d = E.normDebt({
    ...(old || {}), id: id || undefined, name: val("db_name").trim() || "Debt", kind: val("db_kind"), balance: bal,
    apr: parseFloat(val("db_apr")) || 0, credit_limit: parseMoney(val("db_limit")), due_day: Number(val("db_due")),
    min_amount: parseMoney(val("db_minamt")), min_percent: parseFloat(val("db_minpct")) || 0, min_plus_interest: checked("db_plus"),
    linked_bill_id: val("db_link"), updated_on: old && old.balance === bal ? old.updated_on : E.toISO(today),
  });
  if (old) data.debts[data.debts.indexOf(old)] = d; else data.debts.push(d);
  closeSheet();
  save(old ? "Debt updated — plan recalculated" : `Added ${d.name}`, !!old);
}

// ---------- afford
function sheetAfford() {
  if (!E.startCheckpoint(data)) return sheetStart();
  openSheet("Can I afford it?", `<div class="form">${field("What", `<input id="af_name" placeholder="New tires" style="text-align:left">`)}
    ${field("Amount", `<input id="af_amt" inputmode="decimal" placeholder="0.00">`)}
    ${field("On", `<input type="date" id="af_date" value="${E.toISO(today)}" min="${E.toISO(today)}">`)}</div>
    <div class="result" id="af_res"></div>
    <button class="btn primary block" data-act="affordadd">Add it as a one-time bill</button>`, (s) => {
    const upd = () => {
      const s2 = data.settings, cushion = s2.low_balance_threshold;
      const cents = parseMoney(val("af_amt"));
      const d = E.toDay(val("af_date") || E.toISO(today));
      const end = E.horizonEnd(data, today);
      const occ = (day) => ({ date: day, scheduled: day, amount: -cents, item: { name: "test", id: "", category: "", paid_with: "" }, overridden: false });
      const base = build([], false);
      const res = $("#af_res", s);
      if (!cents) { const low = base.lowest(d, end); res.innerHTML = `<div class="big accent">Up to ${money(Math.max(0, (low?.[1] ?? 0) - cushion))}</div><div class="muted small">can be spent on ${niceDate(d)} while keeping your ${money(cushion)} cushion.</div>`; return; }
      const low = build([occ(d)], false).lowest(d, end);
      if (low[1] >= cushion) { res.innerHTML = `<div class="big pos">Yes — you can afford it ✓</div><div class="muted small">Lowest balance afterwards: ${money(low[1])} on ${niceDate(low[0])}.</div>`; return; }
      let tip = "It doesn't fit within your forecast window.";
      for (let day = d + 1; day <= end; day++) {
        const bl = base.lowest(day, end);
        if (bl && bl[1] - cents >= cushion && build([occ(day)], false).lowest(day, end)[1] >= cushion) { tip = `💡 It would fit if you wait until ${longDate(day)}.`; break; }
      }
      res.innerHTML = low[1] >= 0
        ? `<div class="big warn">Tight — it dips into your cushion</div><div class="muted small">Balance would fall to ${money(low[1])} on ${niceDate(low[0])}.</div><div class="small" style="margin-top:6px">${tip}</div>`
        : `<div class="big neg">Not right now ✕</div><div class="muted small">You'd be overdrawn by ${money(-low[1])} on ${niceDate(low[0])}.</div><div class="small" style="margin-top:6px">${tip}</div>`;
    };
    s.querySelectorAll("input").forEach((el) => el.addEventListener("input", upd));
    upd();
  });
}

// ---------- history
function sheetHistory() {
  const um = fc.unplannedByMonth();
  const months = [];
  for (let k = 5; k >= 0; k--) { const m = E.ymd(E.addMonths(E.fromYMD(E.ymd(today).y, E.ymd(today).m, 1), -k, 1)); months.push([m, um.get(`${m.y}-${m.m}`) || 0]); }
  const top = Math.max(1, ...months.map(([, v]) => Math.abs(v)));
  let body = `<div class="card"><h2>Unplanned spending by month</h2><div class="bars">${months.map(([m, v]) =>
    `<div class="b"><span class="${v < 0 ? "neg" : v > 0 ? "pos" : ""}">${v ? moneyShort(Math.abs(v)) : "—"}</span><i style="height:${(Math.abs(v) / top) * 80}%;background:var(${v < 0 ? "--negative" : v > 0 ? "--positive" : "--border"})"></i><span>${fmtDate(E.fromYMD(m.y, m.m, 1), { month: "short" })}</span></div>`).join("")}</div></div><div class="list">`;
  for (const e of [...fc.checkins()].reverse()) {
    body += `<div class="row tap" data-act="delcheckin" data-cp="${esc(e.checkpoint_id)}"><div class="main"><div class="title">${niceDate(e.date)}</div>
      <div class="sub">Expected ${money(e.projected)} · actual ${money(e.balance)}</div></div><div class="num bold ${e.amount < 0 ? "neg" : "pos"}">${money(e.amount, true)}</div></div>`;
  }
  const st = E.startCheckpoint(data);
  body += `<div class="row"><div class="main"><div class="title">${niceDate(E.toDay(st.date))}</div><div class="sub">Starting balance</div></div><div class="num">${money(st.balance)}</div></div></div>
    <p class="hint">Tap a check-in to delete it.</p>`;
  openSheet("Check-in history", body);
}

// ---------- settings
function sheetSettings() {
  const s = data.settings;
  const theme = localStorage.getItem("bt-theme") || "system";
  openSheet("Settings", `<div class="form">${field("Account name", `<input id="se_name" value="${esc(s.account_name)}">`)}
    ${field("Low-balance cushion", `<input id="se_cushion" inputmode="decimal" value="${moneyInput(s.low_balance_threshold)}">`)}
    ${field("Watch ahead", `<select id="se_months">${[1, 2, 3, 6, 9, 12, 18, 24, 36].map((m) => `<option value="${m}" ${s.forecast_months === m ? "selected" : ""}>${m} months</option>`).join("")}</select>`)}
    ${field("Currency symbol", `<input id="se_cur" value="${esc(s.currency_symbol)}" maxlength="4">`)}
    ${field("Appearance", `<select id="se_theme">${opts({ system: "Match iPhone", light: "Light", dark: "Dark" }, theme)}</select>`)}
    ${toggle("Ask for my balance when I open the app", "se_prompt", localStorage.getItem("bt-prompt") !== "0")}</div>
    <div class="list"><div class="row tap" data-act="security"><div class="badge ci">🔒</div><div class="main"><div class="title">Face ID &amp; passcode</div>
      <div class="sub">${L.enabled() ? (L.faceIdOn() ? "On — Face ID with passcode backup" : "On — passcode") : "Off"}</div></div><div class="muted">›</div></div></div>
    <button class="btn primary block" data-act="savesettings">Save</button>
    <button class="btn danger block" style="margin-top:22px" data-act="reset">Erase all data on this phone</button>`);
}

// ---------- sync
function sheetSync() {
  const body = `${meta.unsent ? `<div class="banner warning">You have changes that haven't been sent to your PC yet.</div>` : ""}
    <div class="card"><h2>1 · Get the latest from your PC</h2>
      <p class="muted small" style="margin-top:0">In the Files picker go to <b>iCloud Drive → Balance Tracker</b> and choose <b>${SYNC_NAME}</b>.</p>
      <button class="btn primary block" data-act="pullsync">Choose sync file</button></div>
    <div class="card"><h2>2 · Send your changes to your PC</h2>
      <p class="muted small" style="margin-top:0">Tap below, choose <b>Save to Files</b> → <b>iCloud Drive → Balance Tracker</b> → <b>Save</b>, and tap <b>Replace</b> if asked. Your PC picks it up automatically.</p>
      <button class="btn block ${meta.unsent ? "primary" : ""}" data-act="pushsync">Send to PC</button></div>
    <p class="hint">${meta.lastSync ? "Last synced " + new Date(meta.lastSync).toLocaleString() + ". " : ""}Edits on both devices are merged — the newest change to each item wins, so nothing is lost if you sync in either order.</p>
    <details class="hint"><summary>First time setup</summary><ol class="steps">
      <li>On your PC, install <b>iCloud for Windows</b> (Microsoft Store), sign in with your Apple ID and turn on <b>iCloud Drive</b>.</li>
      <li>In Balance Tracker on the PC: <b>Settings → iPhone sync → Turn on iPhone sync</b>.</li>
      <li>Here, tap <b>Choose sync file</b>. Done!</li></ol></details>`;
  openSheet("Sync with your PC", body);
}
function pickFile() {
  return new Promise((resolve) => {
    const inp = $("#filepick");
    inp.value = "";
    inp.onchange = async () => { const f = inp.files[0]; resolve(f ? await f.text() : null); };
    inp.click();
  });
}
async function pullSync() {
  const text = await pickFile();
  if (text === null) return;
  let remote;
  try { remote = E.normData(JSON.parse(text)); } catch (e) { toast("That isn't a Balance Tracker file."); return; }
  const merged = E.merge(data, remote);
  const changed = !E.sameData(merged, data);
  data = merged;
  saved = clone(data); // adopt as-is: don't re-stamp the PC's changes as new phone edits
  meta.unsent = !E.sameData(merged, remote);
  meta.lastSync = Date.now();
  persist();
  refresh();
  if (sheet().open) sheetSync();
  toast(changed ? "Updated from your PC ✓" : "Already up to date ✓");
}
async function pushSync() {
  const payload = JSON.stringify({ ...data, saved_at: new Date().toISOString(), device: "phone" }, null, 1);
  const file = new File([payload], SYNC_NAME, { type: "application/json" });
  try {
    if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file] });
    else download(file);
    meta.unsent = false;
    meta.lastSync = Date.now();
    persist();
    render();
    if (sheet().open) sheetSync();
    toast("Sent — your PC will merge it in a moment");
  } catch (e) {
    if (e.name !== "AbortError") toast("Couldn't share: " + e.message);
  }
}
function download(file) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(file);
  a.download = file.name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// ---------- entry actions
function sheetEntry(ds) {
  if (ds.cp) {
    if (confirm("Delete this check-in?")) delCheckpoint(ds.cp);
    return;
  }
  const item = E.findItem(data, ds.item);
  if (!item) return;
  const key = E.toISO(Number(ds.sched));
  openSheet(item.name, `<p class="muted" style="margin-top:0">${longDate(Number(ds.date))} · ${money(Number(ds.amt), true)}</p>
    <div class="list">
      <div class="row tap" data-act="ovchange" data-id="${esc(item.id)}" data-key="${key}" data-amt="${Math.abs(Number(ds.amt))}"><div class="main title">Change amount this time…</div></div>
      <div class="row tap" data-act="ovskip" data-id="${esc(item.id)}" data-key="${key}"><div class="main title">Skip this time</div></div>
      ${key in item.overrides ? `<div class="row tap" data-act="ovclear" data-id="${esc(item.id)}" data-key="${key}"><div class="main title">Restore normal amount</div></div>` : ""}
      <div class="row tap" data-act="edititem" data-id="${esc(item.id)}"><div class="main title accent">Edit “${esc(item.name)}”…</div></div></div>`);
}
function delCheckpoint(id) {
  const st = E.startCheckpoint(data);
  if (st && st.id === id) { toast("That's your starting balance — change it with a new check-in on that date."); return; }
  data.checkpoints = data.checkpoints.filter((c) => c.id !== id);
  closeSheet();
  save("Check-in deleted", true);
}

// ------------------------------------------------------------------ app lock
function renderLock() {
  closeSheet();
  $("#tabs").classList.add("hidden");
  const wait = L.waitSeconds();
  $("#app").innerHTML = `<div class="lock"><img src="icons/icon-192.png" width="76" height="76" alt="">
    <h1>Balance Tracker</h1><p class="muted">Locked</p>
    ${L.faceIdOn() ? `<button class="btn primary block" data-act="faceid">Unlock with Face ID</button><div class="or">or enter your passcode</div>` : ""}
    <input id="lk_pin" type="password" inputmode="numeric" autocomplete="off" maxlength="12" placeholder="Passcode" ${wait ? "disabled" : ""}>
    <button class="btn block ${L.faceIdOn() ? "" : "primary"}" data-act="pinunlock" ${wait ? "disabled" : ""}>Unlock</button>
    <p class="small neg" id="lk_msg">${wait ? `Too many tries — wait ${wait}s` : ""}</p>
    <button class="linkbtn" data-act="forgot">Forgot passcode?</button></div>`;
  if (wait) setTimeout(() => locked && renderLock(), 1000);
}
async function tryFaceId(auto = false) {
  if (!L.faceIdOn()) return;
  try {
    if (await L.verifyFaceId()) unlock();
  } catch (e) {
    // iPhone may refuse an automatic prompt until the screen is tapped — the button handles that
    if (!auto && e.name !== "NotAllowedError") toast("Face ID: " + e.message);
  }
}
async function pinUnlock() {
  const pin = $("#lk_pin")?.value || "";
  if (!pin) return;
  if (await L.checkPin(pin)) { unlock(); return; }
  renderLock();
  if (!L.waitSeconds()) $("#lk_msg").textContent = "Wrong passcode";
}
function unlock() {
  locked = false;
  hiddenAt = null;
  refresh();
  startupPrompt();
}

function sheetSecurity() {
  if (!L.enabled()) {
    openSheet("Face ID & passcode", `<p class="hint" style="padding-top:0">Lock Balance Tracker so nobody else using your phone can see your finances.
      First choose a passcode (your backup if Face ID doesn't work), then turn on Face ID.</p>
      <div class="form">${field("New passcode", `<input id="sc_p1" type="password" inputmode="numeric" maxlength="12" placeholder="4–12 digits">`)}
      ${field("Confirm", `<input id="sc_p2" type="password" inputmode="numeric" maxlength="12">`)}</div>
      <button class="btn primary block" data-act="savepin">Continue</button>`);
    return;
  }
  L.faceIdAvailable().then((avail) => {
    openSheet("Face ID & passcode", `<div class="list">
      ${L.faceIdOn() ? `<div class="row"><div class="badge in">✓</div><div class="main"><div class="title">Face ID is on</div><div class="sub">Passcode works as a backup</div></div></div>`
        : avail ? `<div class="row tap" data-act="enablefaceid"><div class="badge ci">☺</div><div class="main"><div class="title accent">Turn on Face ID</div><div class="sub">Your iPhone will ask to save a passkey</div></div></div>`
        : `<div class="row"><div class="main"><div class="title">Face ID isn't available</div><div class="sub">Open the app from your Home Screen icon and make sure Face ID is set up in iPhone Settings.</div></div></div>`}
      </div>
      <div class="form">${field("Lock", `<select id="sc_after" data-change="lockafter">${[[0, "Every time I leave"], [1, "After 1 minute"], [5, "After 5 minutes"], [15, "After 15 minutes"]]
        .map(([m, t]) => `<option value="${m}" ${L.lockAfterMinutes() === m ? "selected" : ""}>${t}</option>`).join("")}</select>`)}</div>
      <div class="dayhead"><span>Change passcode</span></div>
      <div class="form">${field("New passcode", `<input id="sc_p1" type="password" inputmode="numeric" maxlength="12" placeholder="4–12 digits">`)}
      ${field("Confirm", `<input id="sc_p2" type="password" inputmode="numeric" maxlength="12">`)}</div>
      <button class="btn block" data-act="savepin">Change passcode</button>
      ${L.faceIdOn() ? `<button class="btn block" style="margin-top:10px" data-act="disablefaceid">Turn off Face ID (keep passcode)</button>` : ""}
      <div class="dayhead" style="margin-top:12px"><span>Turn off the lock</span></div>
      <div class="form">${field("Current passcode", `<input id="sc_cur" type="password" inputmode="numeric" maxlength="12">`)}</div>
      <button class="btn danger block" data-act="disablelock">Turn off app lock</button>`);
  });
}

// ------------------------------------------------------------------ events
document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("[data-act],[data-tab]");
  if (!t) return;
  if (t.dataset.tab) { tab = t.dataset.tab; render(); window.scrollTo(0, 0); return; }
  const ds = t.dataset;
  switch (ds.act) {
    case "close": closeSheet(); break;
    case "faceid": await tryFaceId(); break;
    case "pinunlock": await pinUnlock(); break;
    case "forgot": {
      if (!confirm("Forgot your passcode? This erases Balance Tracker's data on this phone only — your PC and the iCloud sync file are untouched, so you can sync everything back right after. Continue?")) break;
      L.disable(); localStorage.removeItem(KEY); localStorage.removeItem(META);
      load(); locked = false; tab = "home"; refresh(); break;
    }
    case "security": sheetSecurity(); break;
    case "savepin": {
      const p1 = val("sc_p1"), p2 = val("sc_p2");
      if (!/^\d{4,12}$/.test(p1)) { toast("Use 4 to 12 digits"); break; }
      if (p1 !== p2) { toast("The passcodes don't match"); break; }
      const first = !L.enabled();
      await L.setPin(p1);
      toast(first ? "Passcode set — now turn on Face ID" : "Passcode changed");
      sheetSecurity(); break;
    }
    case "enablefaceid": {
      try { await L.registerFaceId(); toast("Face ID is on 🔒"); }
      catch (e) { toast(e.name === "NotAllowedError" ? "Face ID setup was cancelled" : "Couldn't turn on Face ID: " + e.message); }
      sheetSecurity(); break;
    }
    case "disablefaceid": L.forgetFaceId(); toast("Face ID off — passcode still required"); sheetSecurity(); break;
    case "disablelock": {
      if (!(await L.checkPin(val("sc_cur")))) { toast(L.waitSeconds() ? "Too many tries — wait a moment" : "Wrong passcode"); break; }
      L.disable(); closeSheet(); toast("App lock turned off"); break;
    }
    case "sync": sheetSync(); break;
    case "pullsync": await pullSync(); break;
    case "pushsync": await pushSync(); break;
    case "checkin": sheetCheckin(); break;
    case "savecheckin": saveCheckin(); break;
    case "start": sheetStart(); break;
    case "savestart": {
      data.settings.account_name = val("st_name").trim() || "Chequing";
      E.addCheckpoint(data, { date: val("st_date") || E.toISO(today), balance: parseMoney(val("st_bal")), includes_today: checked("st_inc"), note: "Starting balance", created_at: E.nowLocal(), id: E.newId() });
      closeSheet(); tab = "bills"; save("You're set! Now add your paycheque and bills."); break;
    }
    case "afford": sheetAfford(); break;
    case "affordadd": {
      const cents = parseMoney(val("af_amt"));
      if (!cents) { toast("Enter an amount first"); break; }
      data.items.push(E.normItem({ name: val("af_name").trim() || "Planned purchase", amount: cents, kind: "bill", frequency: "once", start_date: val("af_date"), category: "Planned purchase" }));
      closeSheet(); save("Added as a one-time bill"); break;
    }
    case "range": ui.range = Number(ds.m); render(); break;
    case "ahead": ui.daysAhead = Number(ds.d); render(); break;
    case "everyday": ui.everyDay = !ui.everyDay; render(); break;
    case "billfilter": ui.billFilter = ds.k; render(); break;
    case "cardpaid": data.card_paid.push(ds.key); save("Marked as paid", true); break;
    case "additem":
      openSheet("Add", `<div class="list"><div class="row tap" data-act="newitem" data-k="income"><div class="badge in">▲</div><div class="main title">Income</div></div>
        <div class="row tap" data-act="newitem" data-k="bill"><div class="badge out">▼</div><div class="main title">Bill / expense</div></div></div>`); break;
    case "newitem": sheetItem(null, ds.k); break;
    case "edititem": sheetItem(ds.id); break;
    case "itkind": {
      $("#it_kind", sheet()).value = ds.k;
      sheet().querySelectorAll('[data-act="itkind"]').forEach((b) => b.classList.toggle("on", b === t));
      sheet()._upd?.(); break;
    }
    case "saveitem": {
      const it = readItem(ds.id || null);
      if (!it.name) { toast("Give it a name"); break; }
      if (it.amount <= 0) { toast("Enter an amount"); break; }
      const old = ds.id ? E.findItem(data, ds.id) : null;
      if (old) data.items[data.items.indexOf(old)] = it; else data.items.push(it);
      closeSheet(); save(old ? "Saved" : `Added “${it.name}”`, !!old); break;
    }
    case "delitem": {
      if (!confirm("Delete this entry?")) break;
      data.items = data.items.filter((i) => i.id !== ds.id);
      closeSheet(); save("Deleted", true); break;
    }
    case "entry": sheetEntry(ds); break;
    case "ovskip": case "ovchange": case "ovclear": {
      const item = E.findItem(data, ds.id);
      if (ds.act === "ovskip") item.overrides[ds.key] = null;
      else if (ds.act === "ovclear") delete item.overrides[ds.key];
      else {
        const v = prompt("Amount this time:", (Number(ds.amt) / 100).toFixed(2));
        if (v === null) break;
        item.overrides[ds.key] = parseMoney(v);
      }
      closeSheet(); save(ds.act === "ovskip" ? "Skipped this time" : ds.act === "ovclear" ? "Restored" : "Amount changed for this date", true); break;
    }
    case "adddebt": sheetDebt(); break;
    case "editdebt": sheetDebt(ds.id); break;
    case "savedebt": saveDebt(ds.id || null); break;
    case "deldebt": {
      if (!confirm("Delete this debt?")) break;
      data.debts = data.debts.filter((d) => d.id !== ds.id);
      data.items.forEach((i) => { if (i.paid_with === ds.id) i.paid_with = ""; });
      closeSheet(); save("Debt deleted", true); break;
    }
    case "strategy": data.settings.debt_strategy = ds.k; save(); break;
    case "history": sheetHistory(); break;
    case "delcheckin": if (confirm("Delete this check-in?")) delCheckpoint(ds.cp); break;
    case "settings": sheetSettings(); break;
    case "savesettings": {
      const s = data.settings;
      s.account_name = val("se_name").trim() || "Chequing";
      s.low_balance_threshold = parseMoney(val("se_cushion"));
      s.forecast_months = Number(val("se_months"));
      s.currency_symbol = val("se_cur").trim() || "$";
      localStorage.setItem("bt-theme", val("se_theme"));
      localStorage.setItem("bt-prompt", checked("se_prompt") ? "1" : "0");
      applyTheme();
      closeSheet(); save("Settings saved"); break;
    }
    case "reset": {
      if (!confirm("Erase all Balance Tracker data on this phone? (Your PC and iCloud copy are not touched.)")) break;
      localStorage.removeItem(KEY); localStorage.removeItem(META);
      load(); closeSheet(); tab = "home"; refresh(); break;
    }
    case "export": {
      const file = new File([JSON.stringify(data, null, 1)], `BalanceTracker-backup-${E.toISO(today)}.json`, { type: "application/json" });
      try { if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file] }); else download(file); }
      catch (e) { if (e.name !== "AbortError") toast(e.message); }
      break;
    }
    case "import": {
      const text = await pickFile();
      if (text === null) break;
      try {
        const incoming = E.normData(JSON.parse(text));
        if (!confirm(`Replace everything on this phone with this backup (${incoming.items.length} entries)?`)) break;
        undoSnap = clone(saved);
        data = incoming;
        save("Backup restored", true);
      } catch { toast("That isn't a Balance Tracker backup."); }
      break;
    }
  }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && ev.target.id === "lk_pin") pinUnlock();
});
document.addEventListener("change", (ev) => {
  const t = ev.target.closest("[data-change]");
  if (!t) return;
  if (t.dataset.change === "lockafter") { L.setAfter(Number(t.value)); toast("Saved"); return; }
  const s = data.settings;
  if (t.dataset.change === "dmode") s.debt_mode = t.value;
  if (t.dataset.change === "dfixed") s.debt_fixed_extra = parseMoney(t.value);
  if (t.dataset.change === "dinfc") s.debt_in_forecast = t.checked;
  save();
});

function applyTheme() {
  const th = localStorage.getItem("bt-theme") || "system";
  if (th === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", th);
  const dark = th === "dark" || (th === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", dark ? "#0E1117" : "#F3F5FA"));
}

// ------------------------------------------------------------------ start
load();
applyTheme();
recompute();
render();
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && E.todayDay() !== today) refresh();
});
function startupPrompt() {
  const lc = E.latestCheckpoint(data);
  if (lc && E.toDay(lc.date) < today && localStorage.getItem("bt-prompt") !== "0" && meta.lastPrompt !== E.toISO(today)) {
    meta.lastPrompt = E.toISO(today);
    persist();
    setTimeout(sheetCheckin, 400);
  }
}
if (locked) tryFaceId(true); else startupPrompt();
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    hiddenAt = Date.now();
    document.body.classList.add("cover"); // hide balances in the app switcher
  } else {
    document.body.classList.remove("cover");
    if (L.enabled() && !locked && hiddenAt !== null && (Date.now() - hiddenAt) / 60000 >= L.lockAfterMinutes()) {
      locked = true;
      render();
      tryFaceId(true);
    }
  }
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
if (navigator.storage?.persist) navigator.storage.persist().catch(() => {});
window.__bt = { get data() { return data; }, get locked() { return locked; }, E, L }; // for automated tests
