# Security

## Reporting a problem

Please report security issues privately through **GitHub → Security → Report a vulnerability** on this
repository (turn on *Private vulnerability reporting* in Settings → Code security if it isn't on yet),
rather than in a public issue.

## How Balance Tracker protects your data

Balance Tracker has **no server, no accounts and no database**. Your data lives in a file on your PC
(`%APPDATA%\BalanceTracker\data.json`) and in the iPhone app's storage on your phone. The only things that
ever leave your devices are the ones you turn on:

| What | Where it goes | Protection |
| --- | --- | --- |
| iPhone sync file | Your iCloud Drive | **Encrypted** with your sync passphrase (AES-256-GCM, PBKDF2-SHA256 × 600,000). Files made without the passphrase are refused, so nobody can slip in fake data. |
| Exported backups | Wherever you save them | Optional password, same encryption. |
| Daily reminder email | Your own email provider | TLS with a verified certificate (STARTTLS or SSL); never sent unencrypted. The app password is encrypted with Windows DPAPI. |
| ntfy phone notifications | ntfy.sh | Anyone who knows a topic name can read it, so topics are 144-bit random by default and short ones are refused. |
| "Check for updates" | api.github.com | Nothing about you is sent; the download link must point at this repository. |

**On the PC**
- Secrets (email app password, sync key, lock password hash) are kept apart from your data in
  `secrets.json`, encrypted with Windows DPAPI plus app-specific entropy, and never included in backups or
  the sync file. Data files are written atomically and readable only by you.
- **App lock** (Settings → Security): a password (scrypt-hashed) asked for when the app opens, after you've
  been away (Windows idle time), optionally when minimized, or on demand with **Ctrl+L**. Wrong passwords earn
  growing waits. The lock is a privacy screen, not encryption: the data file is protected by your Windows
  sign-in, so turn on **BitLocker / Device encryption** to protect it if the PC is lost or stolen.
- Names and notes from a sync or backup file are always shown as plain text, never as rich text or links.

**On the iPhone**
- **App lock with encryption at rest** (More → Settings → Face ID & passcode): with a passcode set,
  everything the app stores is encrypted with a random 256-bit key. That key is only stored wrapped — by your
  passcode (PBKDF2-SHA256 × 600,000) and, with Face ID on, by a secret only your passkey can produce (WebAuthn
  PRF, iOS 18+). While locked, neither the key nor your data is in memory. It locks when you leave the app,
  after 5 minutes without a tap, and can erase its data after 10 wrong passcodes.
- A strict **Content-Security-Policy**: only the app's own files can run, nothing can be loaded from or sent
  to anywhere else, and the app refuses to run inside another site's frame.
- Every file you open (sync file or backup) is validated before use: dates, numbers and settings are
  checked, markup is stripped from the currency symbol, and everything shown is HTML-escaped.

## The 20-point checklist

| # | Check | In Balance Tracker |
| --- | --- | --- |
| 1 | Hide API keys | No API keys exist. The only secrets (email app password, sync key) are DPAPI-encrypted on the PC, never in code or git. |
| 2 | Check env variables | Only `BALANCE_TRACKER_HOME` (data folder). No `.env` files; `.gitignore` blocks them. |
| 3 | Check keys in git | Full history scanned: nothing found. `tests/test_repo_hygiene.py` scans every push. |
| 4 | Protect admin routes | No server or routes. The equivalent — reminder task, settings — runs as your Windows user only. |
| 5 | Add auth | App lock on PC and iPhone (Face ID + passcode); the iPhone lock also encrypts the data. |
| 6 | Check user perms | Single-user app. Data and secrets files are private to your account; scheduled task runs with least privilege. |
| 7 | Sanitize user inputs | Every imported/synced file is validated on both devices (strict dates, clamped numbers, size limits). |
| 8 | Protect against XSS | HTML-escaping everywhere, sanitized currency symbol, plain-text Qt labels, and a strict CSP. |
| 9 | SQL injection | No SQL or database. CSV exports are protected against the spreadsheet equivalent (formula injection). |
| 10 | Check DB rules | No database. Storage is local; the sync file is encrypted and authenticated. |
| 11 | Rate limiting | Growing waits after wrong passwords/passcodes (optional erase on iPhone); test emails have a cooldown; at most one reminder a day. |
| 12 | Spend cap | No paid services or APIs, so nothing can run up a bill. |
| 13 | Secure file uploads | Imports are size-limited, parsed as data only, validated, and encrypted files are authenticated. |
| 14 | CSRF protection | No server, cookies or sessions, so there's nothing to forge. |
| 15 | Check CORS | No API to share. The service worker only handles the app's own origin, and the CSP blocks all other connections. |
| 16 | Enable HTTPS | GitHub Pages serves the iPhone app over HTTPS; email uses verified TLS; all outbound requests are HTTPS. |
| 17 | Security headers | CSP and `no-referrer` via `<meta>` (GitHub Pages can't set headers), plus frame-busting in place of `frame-ancestors`. |
| 18 | Secure cookies | No cookies are used. |
| 19 | Disable debug mode | No debug mode or test hooks in the shipped apps; the .exe has no console. |
| 20 | Check prod settings | Least-privilege CI (only the release job can write), no persisted git credentials, SHA-256 checksums on releases, Dependabot and `pip-audit`. |

## Limits worth knowing

- **The PC's data file isn't encrypted by Balance Tracker.** Anyone signed in as you, or malware running as
  you, can read it. Use BitLocker/Device encryption and a Windows password.
- **A short iPhone passcode can be guessed offline** by someone who copies the app's storage off an unlocked,
  trusted computer. A longer passcode, or one with letters, makes that impractical. Face ID's key is strong.
- **GitHub Pages sites share an origin.** Every Pages site under `audiohills.github.io` can read the iPhone
  app's storage. With the app lock on, that storage is encrypted; for full isolation, host the app on its own
  domain (Cloudflare Pages, Netlify, or a custom domain for Pages).
- **iCloud Drive** is protected by Apple; with the sync passphrase set, the file is unreadable even to Apple.
  Turning on Advanced Data Protection protects the rest of your iCloud data the same way.
- **Releases aren't code-signed**, so Windows SmartScreen warns. Compare the SHA-256 checksum published with
  each release.

## Recommended repository settings

- Settings → Code security: turn on **Dependabot alerts**, **Secret scanning** and **Push protection**, and
  **Private vulnerability reporting**.
- Settings → Branches: protect the default branch (require pull requests and passing checks).
- Settings → Pages: keep **Enforce HTTPS** on.
- Settings → Actions → General: set **Workflow permissions** to *Read repository contents*.
