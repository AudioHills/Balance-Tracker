# Changelog

## 2.1.0 — Security

### New
- **Encrypted iPhone sync** (PC: Settings → iPhone sync → *Encrypt with a passphrase*): the sync file in iCloud
  Drive is encrypted with AES-256-GCM. Only devices that know the passphrase can read it, and copies made
  without it are ignored and reported instead of merged. The iPhone asks for the passphrase once.
- **Password-protected backups** on the PC and iPhone.
- **iPhone: encryption at rest.** With the app lock on, everything the app keeps on the phone is encrypted.
  The key is unlocked by your passcode or by Face ID (a passkey secret, iOS 18+), and dropped from memory
  when the app locks. 2.0 locks are upgraded the next time you enter your passcode (Face ID then needs to be
  turned on again).
- **iPhone lock:** passcodes of 6+ digits, or letters and numbers; common ones like 123456 are refused.
  Locks after 5 minutes without a tap even with the app open. Optional *erase after 10 wrong passcodes*.
  Changing the passcode needs the current one.
- **PC app lock** (Settings → Security): a password when the app opens, after you've been away, optionally
  on minimize, and with **Ctrl+L**. Growing waits after wrong passwords.
- [SECURITY.md](SECURITY.md): how your data is protected, and the limits.

### Fixed (security)
- iPhone: a crafted sync or backup file could run script in the app (through the currency symbol or a date)
  and read your data. Every file is now validated, all data is escaped, and a strict Content-Security-Policy
  stops injected script and blocks connections to other sites. The app also refuses to run inside a frame.
- iPhone: a file with an impossible date made the app fail to open until its data was erased; such files are
  now refused with an explanation, and unreadable saved data is kept aside instead of discarded.
- PC: names from a sync or backup file could be shown as rich text, including links.
- CSV exports: names starting with `=`, `+`, `-` or `@` could run as spreadsheet formulas.
- Calendar files: a carriage return in a name could add lines to the event.
- Email reminders: line breaks in names could add email headers.
- ntfy topics must be at least 16 random characters (topics are public to anyone who guesses them); new
  topics are 144-bit random, with a *New random topic* button.
- "Check for updates" only ever links to this repository's releases.
- The email app password (and now the sync key and lock) are encrypted with DPAPI plus app-specific entropy,
  without ever showing a prompt; 2.0's stored password is upgraded automatically. Data and secrets files are
  written atomically and readable only by you.
- Imports and sync files over 20 MB are refused; "Send a test now" has a short cooldown.

### Under the hood
- `encryption.py` / `web/crypto.js` share one file format, cross-checked in both directions.
- CI: read-only token by default, a separate release job is the only one that can write, git credentials
  aren't left on disk, releases carry a SHA-256 checksum, `pip-audit` checks dependencies, Dependabot keeps
  packages and actions up to date, and every push is scanned for committed secrets.
- New dependency: `cryptography`.

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
