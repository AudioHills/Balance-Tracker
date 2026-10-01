# Balance Tracker

A modern Windows desktop app that forecasts your chequing account **day by day**.
Enter your balance, add your paycheques and bills once (weekly, every 2 weeks, twice a month,
monthly, yearly…), and Balance Tracker works out every future date and the running balance for you.

## Features

**What you asked for**
- **Starting balance.** Entered on first launch, editable in Settings.
- **Income and bills that repeat.** Choose one-time, weekly, every 2 weeks, every 4 weeks, twice a
  month (e.g. the 15th and the last day), monthly, every 2, 3 or 6 months, or yearly. Optional end date.
- **Day-by-day ledger.** Every day's running balance, either all days or only days with
  activity. Export it to CSV for Excel.
- **Check in on open.** Each time you open the app, it asks what your bank shows. The gap from the
  plan is logged as **unplanned spending** (or unplanned income). It appears as its own line in the
  ledger, and the forecast is re-anchored to your real balance.
- **Modern UI** with light and dark modes. Click the ☾/☀ button at the top of the sidebar (or press
  `Ctrl+T`) to switch, or choose *Match Windows* in Settings.
- **Backup and import.** Export a backup file, import it (replace or merge), and restore automatic
  daily backups.

**Extras**
- **Safe to spend:** how much you could spend today without any day in the next 30 days dropping
  below your cushion.
- **Overdraft and low-balance alerts:** a banner warns you before the forecast goes negative or
  below a cushion you set.
- **Interactive forecast chart:** hover over any day to see its balance, click it to open that day
  in the ledger.
- **Weekend handling:** a payday that falls on a Saturday or Sunday can move to the Friday before
  or the Monday after.
- **Month-end smart dates:** a bill on the 31st lands on Feb 28/29, Apr 30, and so on.
- **One-off changes:** right-click a ledger line to *skip it this time* or *change the amount this
  time* (e.g. a bigger hydro bill) without touching the schedule.
- **Unplanned spending trends:** a monthly chart, a monthly average, and a running total since you
  started.
- **Monthly snapshot:** average income, bills, and money left over per month, plus how much of it
  goes to unplanned spending.
- **Undo** after deletes and edits. Automatic daily backups (last 30 days kept) and a safety copy
  before every restore.
- **Debt payoff planner** (Debts tab): add credit cards, lines of credit and loans with their
  interest rates and minimum-payment rules. The plan pays the highest rate first (or the smallest
  balance first, if you prefer) and sizes each month's extra payment so your chequing balance never
  drops below your cushion. It shows your debt-free date, interest saved, the order to pay things
  off, and a 12-month payment schedule. It can also add the payments to your day-by-day forecast.
- **Credit-card bills:** set a bill's *Paid with* to a credit card if it's charged to the card and you
  pay the card off right away. It shows as "Pay Visa: Netflix" in the forecast. Charges from the
  last two weeks appear in a **Pay your card** list on the Dashboard, where you tick them off once paid.
- **Email & phone reminders:** *📱 Reminders → Email & phone reminders* sends a short daily email
  on days something needs doing, e.g. "Pay Visa $11.99 — Spotify", debt payments due, bills,
  paydays and low-balance warnings. It sends through your own Gmail/Outlook/Yahoo/iCloud account
  using an *app password*, which is encrypted with Windows DPAPI and never included in backups.
  You can also get push notifications through the free **ntfy** app. A Windows scheduled task sends
  the reminders even when the app is closed; it catches up at logon if the PC was off, and sends at
  most one message per day. Activity is logged to `reminders.log` in the data folder.
- **Calendar reminders:** *📱 Reminders → Export to my calendar* saves a .ics file for Google
  Calendar, iPhone Calendar or Outlook, so reminders fire from your phone even when the PC is off.
- **Can I afford it?:** test a purchase on any date. It tells you whether you stay above your
  cushion and, if not, the first date it would fit.
- **Calendar date pickers:** click any date box to pick a date from a calendar.
- **Keyboard shortcuts:** `Ctrl+1…6` switch pages, `Ctrl+K` check in, `Ctrl+I` add income,
  `Ctrl+B` add bill, `Ctrl+D` add debt, `Ctrl+A` "Can I afford it?".

## iPhone app

The `web/` folder is an installable web app (PWA). Open it in Safari, then tap **Share → Add to
Home Screen**. It runs offline, keeps its data on the phone, and uses the same forecasting and debt
engine as the PC: `tests/test_web_engine.py` checks that both produce identical numbers.

**Syncing with the PC through iCloud Drive**
1. On the PC, install **iCloud for Windows** (Microsoft Store), sign in, and turn on iCloud Drive.
2. In Balance Tracker on the PC, go to **Settings → iPhone sync → Turn on iPhone sync**. The PC then
   keeps `iCloud Drive\Balance Tracker\BalanceTracker-sync.json` up to date.
3. On the iPhone, tap **⟳ → Choose sync file** and pick that file to pull the PC's data in. To send
   phone edits back, tap **Send to PC → Save to Files → iCloud Drive → Balance Tracker → Replace**.
   The PC merges them within a minute.

**Face ID lock.** In the iPhone app, go to *More → Settings → Face ID & passcode*. It uses Face ID (via a
passkey) with a passcode backup, stored only as a salted PBKDF2 hash. Repeated wrong passcodes trigger
growing wait times, and balances are blurred in the app switcher.

Each income/bill and debt carries a change timestamp, and deletions are remembered. Merging keeps
the newest version of every record, so edits made on either device survive whichever order you sync in.

**Hosting.** `web/` is a static site. `.github/workflows/pages.yml` deploys it to GitHub Pages
(the repository must be public on GitHub Free), or point Cloudflare Pages or Netlify at the `web`
folder. Set `WEB_APP_URL` in `balance_tracker/__init__.py` so the PC's Settings page links to it.

## Getting the .exe

**Option A: download it from GitHub.** Open the repository's **Releases** page (right-hand side of
the repo's main page) and download `BalanceTracker.exe` from the latest release. A new release is
published automatically whenever the default branch is updated; bump `__version__` in
`balance_tracker/__init__.py` to make a new version number.

**Option B: build it yourself on Windows.**
1. Install Python 3.10 or newer from python.org (tick *Add python.exe to PATH*).
2. Double-click `build.bat`. The program appears at `dist\BalanceTracker.exe`.

To run from source without building, double-click `run.bat`, or run `pip install -r requirements.txt`
and then `python main.py`.

> Windows SmartScreen may warn about an unsigned app the first time. Click *More info → Run anyway*.

## Where your data lives

`%APPDATA%\BalanceTracker\data.json`, with daily snapshots in the `backups` folder next to it.
The Settings page shows the exact path and has an *Open data folder* button. Set the
`BALANCE_TRACKER_HOME` environment variable to keep the data somewhere else (e.g. a OneDrive folder).

## How check-ins work

The forecast starts from your starting balance and adds or subtracts each scheduled item.
When you check in with your real balance:

```
plan expected  $1,240.00
bank shows     $1,105.00
               ---------
unplanned      −$135.00   ← recorded as "Check-in: unplanned spending"
```

From then on, the forecast continues from $1,105.00. If that day's paycheque or bills have
already landed, leave *"This balance already includes that day's scheduled items"* ticked.
Otherwise untick it, and they'll be applied after your check-in.

## Development

```
pip install -r requirements-dev.txt
python -m pytest            # engine tests and an offscreen UI smoke test
python main.py
```

Code layout:

| Path | What |
| --- | --- |
| `balance_tracker/models.py` | Data classes (amounts in integer cents) and JSON (de)serialisation |
| `balance_tracker/forecast.py` | Schedule generation and the day-by-day projection engine |
| `balance_tracker/debts.py` | Debt payoff simulation and the cushion-aware payment planner |
| `balance_tracker/notify.py` | Daily reminder digest, email/ntfy delivery, Windows scheduled task |
| `balance_tracker/reminders.py` | Calendar (.ics) export |
| `balance_tracker/sync.py` | iPhone sync: change stamps, deletion markers, record-level merge |
| `web/` | iPhone web app: `engine.js` (port of the engine), `app.js` (UI), service worker, manifest |
| `balance_tracker/storage.py` | Load/save, automatic backups, import/export, CSV |
| `balance_tracker/ui/` | PySide6 (Qt) interface: theme, pages, dialogs, custom charts |
