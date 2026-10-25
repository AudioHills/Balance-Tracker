from datetime import date

import pytest

from balance_tracker.formatting import (
    ampm,
    days_away,
    months_away,
    nice_date,
    ordinal,
    plural,
    relative_day,
)
from balance_tracker.models import AppData, Settings, parse_hhmm


def test_settings_survive_bad_values():
    s = Settings.from_dict({
        "theme": "neon", "low_balance_threshold": None, "forecast_months": "120", "prompt_on_open": "false",
        "smtp_port": 0, "notify_time": "25:00", "notify_days_before": 99, "currency_symbol": "  ",
        "account_name": "", "debt_mode": "turbo", "hide_balance": 1, "unknown_setting": 5,
    })
    assert s.theme == "system" and s.low_balance_threshold == 10000 and s.forecast_months == 36
    assert s.prompt_on_open is False and s.hide_balance is True
    assert s.smtp_port == 587 and s.notify_time == "08:00" and s.notify_days_before == 7
    assert s.currency_symbol == "$" and s.account_name == "Chequing" and s.debt_mode == "auto"


def test_a_corrupt_setting_no_longer_makes_the_file_unreadable():
    data = AppData.from_dict({"items": [], "settings": {"forecast_months": {"oops": 1}}})
    assert data.settings.forecast_months == 6


def test_parse_hhmm():
    assert parse_hhmm("08:30") == (8, 30)
    for bad in ("8:30", "24:00", "12:60", "", "noon"):
        with pytest.raises(ValueError):
            parse_hhmm(bad)


def test_formatting():
    today = date(2026, 10, 5)
    assert nice_date(date(2026, 10, 9), today) == "Fri Oct 9"
    assert nice_date(date(2027, 1, 2), today) == "Sat Jan 2, 2027"
    assert nice_date(date(2026, 10, 4), today) == "Yesterday"
    assert relative_day(date(2026, 10, 9), today) == "on Friday, October 9"
    assert relative_day(date(2026, 10, 9), today, long=False) == "on Fri Oct 9"
    assert relative_day(date(2026, 10, 6), today) == "tomorrow"
    assert days_away(date(2026, 10, 10), today) == "in 5 days"
    assert months_away(date(2028, 11, 1), today) == "in 2 years 1 month"
    assert months_away(date(2026, 10, 30), today) == "this month"
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 31)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "31st"]
    assert ampm("00:05") == "12:05 AM" and ampm("17:30") == "5:30 PM"
    assert plural(1, "entry", "entries") == "1 entry" and plural(0, "entry", "entries") == "0 entries"
    assert plural(2, "bill") == "2 bills"
