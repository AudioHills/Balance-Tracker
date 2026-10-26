"""Daily reminder digest by email (and optionally ntfy phone push).

* `compose()` builds today's digest from the forecast, debt plan and card charges.
* `send_email()` / `send_ntfy()` deliver it.
* `run_daily()` is what `BalanceTracker.exe --send-reminders` runs from Windows Task
  Scheduler: it sends at most one digest per day, then exits.
* The email password is encrypted with Windows DPAPI (tied to the Windows user) and
  kept in secrets.json, which is never part of backups or exports (see secure_store.py).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import smtplib
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path

from . import money, secure_store
from .debts import full_forecast, make_plan
from .forecast import projection_end
from .formatting import month_day, relative_day
from .insights import unpaid_card_charges
from .models import INCOME, AppData, parse_hhmm

log = logging.getLogger(__name__)

TASK_NAME = "Balance Tracker Reminders"
SECRETS_FILE = secure_store.SECRETS_FILE
ACTIVITY_LOG = "reminders.log"  # shown in the app as "Last activity"
CARD_NAG_DAYS = 7  # keep reminding about an unpaid card charge for a week
MIN_NTFY_TOPIC = 16

EMAIL_PRESETS = {  # label -> (host, port, ssl)
    "Gmail": ("smtp.gmail.com", 587, False),
    "Outlook / Hotmail": ("smtp-mail.outlook.com", 587, False),
    "Yahoo": ("smtp.mail.yahoo.com", 465, True),
    "iCloud": ("smtp.mail.me.com", 587, False),
}


# --------------------------------------------------------------------------
# Password storage (Windows DPAPI, in secrets.json — see secure_store.py)
# --------------------------------------------------------------------------
def load_password(folder: Path) -> str:
    return secure_store.get(folder, "smtp_password")


def save_password(folder: Path, password: str) -> None:
    secure_store.put(folder, "smtp_password", password)


# --------------------------------------------------------------------------
# Digest
# --------------------------------------------------------------------------
@dataclass
class Digest:
    subject: str
    lines: list = field(default_factory=list)  # (emoji, text, urgent)
    footer: str = ""

    @property
    def text(self) -> str:
        body = "\n".join(f"{e} {t}" for e, t, _ in self.lines)
        return f"{body}\n\n{self.footer}\n\n— Balance Tracker"

    @property
    def html(self) -> str:
        rows = "".join(
            f"<tr><td style='padding:6px 10px;font-size:18px'>{e}</td>"
            f"<td style='padding:6px 0;font-size:15px;{'font-weight:600' if u else ''}'>{escape(t)}</td></tr>"
            for e, t, u in self.lines)
        return (f"<div style='font-family:Segoe UI,Arial,sans-serif;color:#18202F;max-width:560px'>"
                f"<h2 style='margin:0 0 12px;color:#4F5FE8'>Balance Tracker</h2>"
                f"<table style='border-collapse:collapse'>{rows}</table>"
                f"<p style='color:#677086;font-size:13px;margin-top:18px'>{escape(self.footer)}</p></div>")


def compose(data: AppData, today: date) -> Digest | None:
    """Today's reminders, or None if there's nothing worth sending."""
    s = data.settings
    if not data.has_start:
        return None
    plan = make_plan(data, today) if data.debts else None
    f = full_forecast(data, plan, today, projection_end(data, today))
    ahead = today + timedelta(days=s.notify_days_before)
    lines = []

    def when(d: date) -> str:
        return relative_day(d, today, long=False)

    # Card charges: today's, plus any from the last week not marked paid
    if s.notify_card:
        for c in unpaid_card_charges(data, today, CARD_NAG_DAYS):
            charged = c.occurrence.date
            late = "" if charged == today else f" (charged {month_day(charged)} — still unpaid)"
            lines.append(("💳", f"Pay {c.card.name} {money.fmt(c.amount)} — {c.occurrence.item.name}{late}", True))

    if s.notify_debts and plan is not None:
        names = {d.id: d.name for d in data.debts}
        totals = {}
        for p in plan.payments:
            if p.date in (today, ahead):
                key = (p.debt_id, p.date)
                mins, extra = totals.get(key, (0, 0))
                totals[key] = (mins, extra + p.amount) if p.extra else (mins + p.amount, extra)
        for (debt_id, d), (mins, extra) in sorted(totals.items(), key=lambda kv: kv[0][1]):
            name = names.get(debt_id, "Debt")
            if mins:
                text = f"{name} payment {money.fmt(mins + extra)} due {when(d)}"
                if extra:
                    text += f" (minimum {money.fmt(mins)} + {money.fmt(extra)} extra)"
            else:
                text = f"{name}: pay {money.fmt(extra)} extra {when(d)} (your payoff plan)"
            lines.append(("🏦", text, d == today))

    for e in f.entries:
        if e.date not in (today, ahead) or e.item_id is None:
            continue
        item = data.item(e.item_id)
        if item is None or item.paid_with:
            continue
        if item.kind == INCOME and s.notify_paydays and e.date == today:
            lines.append(("💰", f"{item.name} {money.fmt(e.amount)} lands today", False))
        elif item.kind != INCOME and s.notify_bills:
            lines.append(("🧾", f"{item.name} {money.fmt(-e.amount)} comes out {when(e.date)}", e.date == today))

    if s.notify_low:
        low = f.first_below(s.low_balance_threshold, today, today + timedelta(days=7))
        if low:
            what = "overdraft" if low[1] < 0 else f"below your {money.fmt(s.low_balance_threshold)} cushion"
            lines.append(("⚠️", f"Balance heads into {what} {when(low[0])} ({money.fmt(low[1])})", True))

    if not lines:
        return None
    first = lines[0][1]
    subject = (first if len(lines) == 1 else f"{first} (+{len(lines) - 1} more)")
    bal = f.balance_on(today)
    footer = f"Projected {s.account_name} balance today: {money.fmt(bal)}." if bal is not None else ""
    return Digest(f"{subject} · Balance Tracker", lines, footer)


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------
def _header(text: str) -> str:
    """A value safe for one email header line (names from a sync file could hold line breaks)."""
    return " ".join(str(text).split())


def send_email(s, password: str, subject: str, text: str, html: str | None = None, timeout: int = 20) -> None:
    msg = EmailMessage()
    msg["Subject"] = _header(subject)
    msg["From"] = _header(s.smtp_user or s.email_to)
    msg["To"] = _header(s.email_to)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    if s.smtp_ssl:
        server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=timeout, context=ctx)
    else:
        server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=timeout)
    with server:
        if not s.smtp_ssl:
            server.starttls(context=ctx)
        server.login(_header(s.smtp_user or s.email_to), password)
        server.send_message(msg)


def new_ntfy_topic() -> str:
    """A topic nobody can guess (about 144 random bits). ntfy.sh topics are public: anyone who knows
    the name can read the messages, so the name is the only thing keeping reminders private."""
    return f"bt-{secrets.token_urlsafe(18)}"


def ntfy_topic_problem(topic: str) -> str:
    """Why a topic is unsafe or unusable, or "" if it's fine."""
    if not re.fullmatch(r"[-_A-Za-z0-9]{1,64}", topic):
        return "Topic names can only use letters, digits, - and _ (up to 64 characters)."
    if len(topic) < MIN_NTFY_TOPIC:
        return (f"Anyone who guesses the topic can read your reminders. Use at least {MIN_NTFY_TOPIC} "
                "random characters (click New random topic).")
    return ""


def send_ntfy(topic: str, title: str, text: str, timeout: int = 15) -> None:
    if ntfy_topic_problem(topic):
        raise ValueError(ntfy_topic_problem(topic))
    body = json.dumps({"topic": topic, "title": _header(title), "message": text, "tags": ["moneybag"]}).encode()
    req = urllib.request.Request("https://ntfy.sh/", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def deliver(data: AppData, folder: Path, digest: Digest) -> list:
    """Send the digest on every enabled channel. Returns a list of error strings."""
    s = data.settings
    errors = []
    if s.email_enabled and s.email_to:
        try:
            send_email(s, load_password(folder), digest.subject, digest.text, digest.html)
        except Exception as e:  # noqa: BLE001 - report any delivery failure
            errors.append(f"Email: {e}")
    if s.ntfy_enabled and s.ntfy_topic:
        try:
            body = "\n".join(f"{e} {t}" for e, t, _ in digest.lines)
            send_ntfy(s.ntfy_topic, digest.subject.replace(" · Balance Tracker", ""), body)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Phone notification: {e}")
    return errors


def due_now(data: AppData, now: datetime | None = None) -> bool:
    s = data.settings
    if not (s.email_enabled or s.ntfy_enabled):
        return False
    now = now or datetime.now()
    try:
        at = parse_hhmm(s.notify_time)
    except ValueError:
        at = (8, 0)
    return s.notify_last_sent != now.date().isoformat() and (now.hour, now.minute) >= at


def run_daily(store, now: datetime | None = None) -> str:
    """Send today's digest once (used by the scheduled task and on app start)."""
    data = store.load()
    if not due_now(data, now):
        return "not due"
    today = (now or datetime.now()).date()
    digest = compose(data, today)
    errors = deliver(data, store.folder, digest) if digest else []
    if not errors:
        data.settings.notify_last_sent = today.isoformat()
        store.save(data)
    log_activity(store.folder, "nothing to send" if not digest else ("; ".join(errors) or "sent"))
    return "; ".join(errors) if errors else ("sent" if digest else "nothing to send")


def last_log(folder: Path) -> str:
    """The most recent line of the reminder activity log."""
    try:
        lines = (Path(folder) / ACTIVITY_LOG).read_text(encoding="utf-8").splitlines()
        return lines[-1] if lines else ""
    except OSError:
        return ""


def log_activity(folder: Path, msg: str) -> None:
    """Record what the reminder sender did, for "Last activity" in the app (last 200 lines kept)."""
    log.info("Reminders: %s", msg)
    try:
        p = Path(folder) / ACTIVITY_LOG
        lines = p.read_text(encoding="utf-8").splitlines()[-200:] if p.exists() else []
        lines.append(f"{datetime.now():%Y-%m-%d %H:%M} {msg}")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        log.warning("Couldn't write %s: %s", ACTIVITY_LOG, e)


# --------------------------------------------------------------------------
# Windows Task Scheduler
# --------------------------------------------------------------------------
def launch_command() -> tuple:
    """(program, arguments) that start this app in reminder mode."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--send-reminders"
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return str(pyw if pyw.exists() else exe), f'"{main}" --send-reminders'


def task_xml(at: str, program: str, args: str) -> str:
    start = f"{date.today().isoformat()}T{at}:00"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Sends Balance Tracker's daily payment reminders.</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger><Delay>PT2M</Delay></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(program)}</Command><Arguments>{escape(args)}</Arguments></Exec>
  </Actions>
</Task>
"""


def _schtasks(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def install_task(at: str) -> None:
    if sys.platform != "win32":
        raise OSError("Scheduled reminders are only available on Windows.")
    program, args = launch_command()
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        Path(path).write_text(task_xml(at, program, args), encoding="utf-16")
        r = _schtasks("/Create", "/TN", TASK_NAME, "/XML", path, "/F")
        if r.returncode != 0:
            raise OSError((r.stderr or r.stdout).strip() or "schtasks failed")
    finally:
        Path(path).unlink(missing_ok=True)


def remove_task() -> None:
    if sys.platform == "win32":
        _schtasks("/Delete", "/TN", TASK_NAME, "/F")
