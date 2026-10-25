# Changelog

## 2.0.0

### New
- **Until payday** (Dashboard and iPhone Home): the next paycheque, what goes out before it, the
  lowest balance before then, and a **daily spending allowance**: the most you can spend every day
  until payday while staying above your cushion for the next 30 days, including bills right after
  payday.
- **Where your bills go**: monthly bills by category on Income & Bills (PC and iPhone).
- **Change amount from a date on**: for rent increases, a new phone plan or a raise. Right-click a
  line in Day by day or an entry in Income & Bills (on the iPhone, tap the line or open the entry).
  Earlier dates keep the old amount and the schedule never moves, even for bills on the 31st or
  Feb 29.
- **Undo history**: every change can be undone, up to 25 steps back, with **Ctrl+Z**.
- **Filter Day by day** by name or category (**Ctrl+F**). CSV export follows the filter.
- **Keyboard shortcuts list** (**F1**), and **Check for updates** in Settings.
- Unexpected errors are written to `balance-tracker.log` in the data folder and reported, instead
  of failing silently.

### Fixed
- Amount boxes (balances, cushion, bills) could show blank because the text field inside was 1px wide.
- Safe to spend showed $0 whenever the automatic payoff plan was in the forecast, which contradicted
  "Can I afford it?". Spending room is now measured before the plan's extra payments, which shrink
  to fit whatever you spend.
- A single malformed setting no longer makes the whole data file unreadable.
- Monthly totals no longer count entries whose end date has passed.
- iPhone: Settings → Save reset "Watch ahead" to 1 month when the PC used a value the phone's list
  didn't have, and synced that back to the PC.
- iPhone: semicolons in names weren't escaped in calendar (.ics) files.
- Check-ins said "Nothing unplanned so far" when you'd come out ahead; the Dashboard's average
  unplanned spending divided by three months even with less data.
- Duplicating an entry added the copy even if you cancelled the editor.
- Adding a debt before entering a starting balance crashed the Debts page.
- Changing one setting re-saved every setting on the page, which could overwrite a value that had
  just synced from the phone.
- Merged iPhone copies and safety backups were never cleaned up; the backup list is now sorted by
  date with readable names, and no longer offers phone sync copies, which would have switched off
  sync and email reminders if restored.
- "Email & phone reminders" showed as "Email _phone"; links were hard to read in dark mode; the debt
  chart's axis went below zero; "Send a test now" froze the window while sending.

### Under the hood
- Business logic moved out of the UI into tested core modules (`insights.py`, `formatting.py`),
  ported to the iPhone engine and cross-checked against it.
- The UI is split into one module per page and dialog. Only the visible page recomputes after a
  change.
- `pyproject.toml`, ruff linting in CI, logging, and tests grew from 60 to 97.
