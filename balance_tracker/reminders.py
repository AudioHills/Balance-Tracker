"""Phone reminders via a calendar file (.ics).

The file can be imported into Google Calendar, Outlook or the iPhone/Android
calendar app. Reminders then fire from the phone itself, even when the PC is
off. Event IDs are stable, so re-importing an updated file replaces the old
events instead of duplicating them in calendars that honour UIDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from . import money
from .forecast import add_months, occurrences
from .models import AppData, INCOME


@dataclass
class Reminder:
    uid: str
    day: date
    title: str
    detail: str
    days_before: int = 0


def collect(data: AppData, plan, today: date, months: int = 6, card_charges: bool = True,
            debt_payments: bool = True, bills: bool = False, paydays: bool = False,
            days_before: int = 1) -> list:
    end = add_months(today, months)
    out = []
    for item in data.items:
        card = data.debt(item.paid_with) if item.paid_with else None
        want = (card is not None and card_charges) or (card is None and item.kind != INCOME and bills) \
            or (item.kind == INCOME and paydays)
        if not want:
            continue
        for o in occurrences(item, today, end):
            amt = money.fmt(abs(o.amount))
            if card is not None:
                out.append(Reminder(f"card-{item.id}-{o.date}", o.date, f"💳 Pay {card.name} {amt} ({item.name})",
                                    f"{item.name} is charged to {card.name} today. Pay {amt} from chequing "
                                    f"right away so no interest builds up."))
            elif item.kind == INCOME:
                out.append(Reminder(f"pay-{item.id}-{o.date}", o.date, f"💰 {item.name} {amt}",
                                    f"{item.name} should land today."))
            else:
                out.append(Reminder(f"bill-{item.id}-{o.date}", o.date, f"🧾 {item.name} {amt}",
                                    f"{item.name} comes out of chequing today.", days_before))
    if debt_payments and plan is not None:
        names = {d.id: d.name for d in data.debts}
        by_key = {}
        for p in plan.payments:
            if today <= p.date <= end:
                mins, extra = by_key.get((p.debt_id, p.date), (0, 0))
                by_key[(p.debt_id, p.date)] = (mins + (0 if p.extra else p.amount), extra + (p.amount if p.extra else 0))
        for (debt_id, d), (mins, extra) in sorted(by_key.items(), key=lambda kv: kv[0][1]):
            name = names.get(debt_id, "Debt")
            total = money.fmt(mins + extra)
            parts = ([f"minimum {money.fmt(mins)}"] if mins else []) + ([f"extra {money.fmt(extra)}"] if extra else [])
            out.append(Reminder(f"debt-{debt_id}-{d}", d, f"💳 {name} payment {total}",
                                f"Payoff plan: pay {total} to {name} ({' + '.join(parts)}).", days_before))
    out.sort(key=lambda r: (r.day, r.title))
    return out


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold to 75 octets per RFC 5545 without splitting UTF-8 characters."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 74:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def to_ics(reminders: list, at: str = "09:00", calendar_name: str = "Balance Tracker") -> str:
    hh, mm = (int(x) for x in at.split(":"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Balance Tracker//Reminders//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(calendar_name)}"]
    for r in reminders:
        start = datetime.combine(r.day, time(hh, mm))  # floating local time on the phone
        end = start + timedelta(minutes=15)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{r.uid}@balance-tracker",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start:%Y%m%dT%H%M%S}",
            f"DTEND:{end:%Y%m%dT%H%M%S}",
            f"SUMMARY:{_esc(r.title)}",
            f"DESCRIPTION:{_esc(r.detail)}",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(r.title)}", "TRIGGER:PT0M", "END:VALARM",
        ]
        if r.days_before:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc('Coming up: ' + r.title)}",
                      f"TRIGGER:-P{r.days_before}D", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
