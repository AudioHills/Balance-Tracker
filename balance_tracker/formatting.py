"""Human-friendly wording for dates, times and counts.

Shared by the desktop UI, the reminder emails and the calendar export so the same day is
always described the same way. Days of the month are never zero-padded ("Oct 5").
"""
from __future__ import annotations

from datetime import date, timedelta

from .models import parse_hhmm


def short_date(d: date) -> str:
    """"Mon Oct 5"."""
    return f"{d:%a %b} {d.day}"


def long_date(d: date) -> str:
    """"Monday, October 5"."""
    return f"{d:%A, %B} {d.day}"


def full_date(d: date) -> str:
    """"Mon Oct 5, 2026"."""
    return f"{d:%a %b} {d.day}, {d.year}"


def month_day(d: date) -> str:
    """"Oct 5"."""
    return f"{d:%b} {d.day}"


def nice_date(d: date, today: date) -> str:
    """Today / Tomorrow / Yesterday, else "Mon Oct 5" (with the year when it isn't this year)."""
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return short_date(d) if d.year == today.year else full_date(d)


def relative_day(d: date, today: date, long: bool = True) -> str:
    """Fits into a sentence: "today", "tomorrow" or "on Monday, October 5" ("on Mon Oct 5" short)."""
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return "on " + (long_date(d) if long else short_date(d))


def days_away(d: date, today: date) -> str:
    """"today", "tomorrow", "in 5 days"."""
    n = (d - today).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n < 0:
        return plural(-n, "day") + " ago"
    return "in " + plural(n, "day")


def months_away(d: date, today: date) -> str:
    """"this month", "in 7 months", "in 2 years 3 months"."""
    m = (d.year - today.year) * 12 + d.month - today.month
    if m <= 0:
        return "this month"
    years, months = divmod(m, 12)
    parts = ([plural(years, "year")] if years else []) + ([plural(months, "month")] if months else [])
    return "in " + " ".join(parts)


def ago(d: date, today: date) -> str:
    """"today", "yesterday", "12 days ago"."""
    n = (today - d).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    return f"{n} days ago"


def ordinal(n: int) -> str:
    """1 -> "1st", 22 -> "22nd", 13 -> "13th"."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def plural(n: int, word: str) -> str:
    """plural(1, "day") -> "1 day", plural(3, "day") -> "3 days"."""
    return f"{n} {word}{'' if n == 1 else 's'}"


def ampm(hhmm: str) -> str:
    """"17:05" -> "5:05 PM"."""
    h, m = parse_hhmm(hhmm)
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
