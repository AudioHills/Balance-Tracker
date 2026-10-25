"""Data model for Balance Tracker.

All money values are stored as integer cents to avoid floating point drift.
"""
from __future__ import annotations

import contextlib
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime

SCHEMA_VERSION = 1

INCOME = "income"
BILL = "bill"

# Frequency identifiers -> human labels (order is the order shown in the UI)
FREQUENCIES = {
    "once": "One time",
    "weekly": "Weekly",
    "biweekly": "Every 2 weeks",
    "fourweekly": "Every 4 weeks",
    "semimonthly": "Twice a month",
    "monthly": "Monthly",
    "bimonthly": "Every 2 months",
    "quarterly": "Every 3 months",
    "semiannual": "Every 6 months",
    "yearly": "Yearly",
}

# What to do when a payment lands on a Saturday/Sunday
WEEKEND_RULES = {
    "none": "Keep the date",
    "before": "Move to the Friday before",
    "after": "Move to the Monday after",
}

LAST_DAY = 31  # day-of-month value meaning "last day of the month"

DEBT_KINDS = {
    "credit_card": "Credit card",
    "line_of_credit": "Line of credit",
    "loan": "Loan",
}

DEBT_STRATEGIES = {
    "avalanche": "Highest interest first",
    "snowball": "Smallest balance first",
}

DEBT_MODES = ("auto", "fixed")  # auto = as much as the cushion allows; fixed = a set extra per month
THEMES = ("system", "light", "dark")

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def parse_hhmm(text: str) -> tuple[int, int]:
    """("08:30") -> (8, 30). Raises ValueError for anything that isn't a 24-hour HH:MM time."""
    m = _HHMM.match(text or "")
    if not m:
        raise ValueError(f"Not a time of day: {text!r}")
    return int(m.group(1)), int(m.group(2))


def card_paid_key(item_id: str, day: date) -> str:
    """Key under which a credit-card charge is remembered as paid off (see AppData.card_paid)."""
    return f"{item_id}|{day.isoformat()}"


def _d(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


@dataclass
class RecurringItem:
    """An income or bill that happens once or on a schedule."""

    name: str
    amount: int  # cents, always positive; sign comes from `kind`
    kind: str = BILL
    frequency: str = "monthly"
    start_date: date = field(default_factory=date.today)
    end_date: date | None = None
    # Second day of the month for "Twice a month" (31 = last day of month)
    second_day: int = LAST_DAY
    weekend_rule: str = "none"
    category: str = ""
    notes: str = ""
    active: bool = True
    # scheduled-date ISO string -> amount in cents, or None to skip that occurrence
    overrides: dict = field(default_factory=dict)
    # Debt id of the credit card this bill is charged to (paid off from chequing right away)
    paid_with: str = ""
    updated: str = ""  # UTC timestamp of the last change (for iPhone sync)
    id: str = field(default_factory=new_id)

    @property
    def signed_amount(self) -> int:
        return self.amount if self.kind == INCOME else -self.amount

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat() if self.end_date else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> RecurringItem:
        kind = d.get("kind", BILL)
        if kind not in (INCOME, BILL):
            raise ValueError(f"Unknown kind {kind!r}")
        freq = d.get("frequency", "monthly")
        if freq not in FREQUENCIES:
            raise ValueError(f"Unknown frequency {freq!r}")
        overrides = {}
        for k, v in (d.get("overrides") or {}).items():
            date.fromisoformat(k)  # validate
            overrides[k] = None if v is None else int(v)
        return cls(
            id=str(d.get("id") or new_id()),
            name=str(d["name"]),
            amount=abs(int(d["amount"])),
            kind=kind,
            frequency=freq,
            start_date=_d(d.get("start_date")) or date.today(),
            end_date=_d(d.get("end_date")),
            second_day=min(LAST_DAY, max(1, int(d.get("second_day") or LAST_DAY))),
            weekend_rule=d.get("weekend_rule", "none") if d.get("weekend_rule") in WEEKEND_RULES else "none",
            category=str(d.get("category", "")),
            notes=str(d.get("notes", "")),
            active=bool(d.get("active", True)),
            overrides=overrides,
            paid_with=str(d.get("paid_with") or ""),
            updated=str(d.get("updated") or ""),
        )


@dataclass
class Checkpoint:
    """A real balance the user entered on a given day.

    The earliest checkpoint is the starting balance. Every later one is a
    "check-in": the gap between what was projected and what the bank actually
    shows is recorded as unplanned spending (or unplanned income).
    """

    date: date
    balance: int  # cents
    # True if that day's scheduled items had already hit the account when the
    # balance was entered (so they are part of `balance`).
    includes_today: bool = True
    note: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Checkpoint:
        return cls(
            id=str(d.get("id") or new_id()),
            date=_d(d["date"]),
            balance=int(d["balance"]),
            includes_today=bool(d.get("includes_today", True)),
            note=str(d.get("note", "")),
            created_at=str(d.get("created_at", "")),
        )


@dataclass
class Debt:
    """A credit card, line of credit or loan being paid down."""

    name: str
    balance: int  # cents owed (positive)
    apr: float  # annual interest rate, percent (e.g. 19.99)
    kind: str = "credit_card"
    due_day: int = 1  # payment day of month (31 = last day)
    # Minimum payment = max(min_amount, min_percent% of balance [+ interest])
    min_amount: int = 1000
    min_percent: float = 0.0
    min_plus_interest: bool = True
    credit_limit: int = 0  # cents; 0 = not set
    linked_bill_id: str = ""  # an Income & Bills entry that already pays this debt
    updated_on: date = field(default_factory=date.today)
    notes: str = ""
    updated: str = ""  # UTC timestamp of the last change (for iPhone sync)
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["updated_on"] = self.updated_on.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Debt:
        kind = d.get("kind", "credit_card")
        return cls(
            id=str(d.get("id") or new_id()),
            name=str(d["name"]),
            balance=max(0, int(d.get("balance", 0))),
            apr=max(0.0, float(d.get("apr", 0))),
            kind=kind if kind in DEBT_KINDS else "credit_card",
            due_day=min(31, max(1, int(d.get("due_day", 1)))),
            min_amount=max(0, int(d.get("min_amount", 0))),
            min_percent=max(0.0, float(d.get("min_percent", 0))),
            min_plus_interest=bool(d.get("min_plus_interest", True)),
            credit_limit=max(0, int(d.get("credit_limit", 0))),
            linked_bill_id=str(d.get("linked_bill_id") or ""),
            updated_on=_d(d.get("updated_on")) or date.today(),
            notes=str(d.get("notes", "")),
            updated=str(d.get("updated") or ""),
        )


@dataclass
class Settings:
    theme: str = "system"  # system | light | dark
    currency_symbol: str = "$"
    low_balance_threshold: int = 10000  # cents
    forecast_months: int = 6
    prompt_on_open: bool = True
    reminder_time: str = "09:00"  # time of day for phone calendar reminders
    # Daily reminder emails / phone notifications
    email_enabled: bool = False
    email_to: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_ssl: bool = False  # True = SSL on connect (port 465); False = STARTTLS
    ntfy_enabled: bool = False
    ntfy_topic: str = ""
    notify_card: bool = True
    notify_debts: bool = True
    notify_bills: bool = False
    notify_paydays: bool = False
    notify_low: bool = True
    notify_days_before: int = 1
    notify_time: str = "08:00"
    notify_last_sent: str = ""  # ISO date of the last daily digest
    notify_task: bool = False  # Windows scheduled task registered
    # iPhone sync through iCloud Drive
    sync_enabled: bool = False
    sync_folder: str = ""
    hide_balance: bool = False  # eye toggle: show today's balance as ******
    account_name: str = "Chequing"
    # Debt payoff plan
    debt_strategy: str = "avalanche"
    debt_mode: str = "auto"  # auto = as much as the cushion allows; fixed = debt_fixed_extra per month
    debt_fixed_extra: int = 0  # cents per month
    debt_in_forecast: bool = False  # add the plan's payments to the day-by-day forecast

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Settings:
        """Read saved settings. A missing or malformed value falls back to its default rather
        than making the whole data file unreadable."""
        s = cls()
        for f in fields(cls):
            if f.name not in d:
                continue
            with contextlib.suppress(TypeError, ValueError):  # keep the default
                setattr(s, f.name, _coerce(d[f.name], type(getattr(s, f.name))))
        s._normalise()
        return s

    def _normalise(self) -> None:
        defaults = Settings()
        if self.theme not in THEMES:
            self.theme = defaults.theme
        if self.debt_strategy not in DEBT_STRATEGIES:
            self.debt_strategy = defaults.debt_strategy
        if self.debt_mode not in DEBT_MODES:
            self.debt_mode = defaults.debt_mode
        for name in ("reminder_time", "notify_time"):
            try:
                parse_hhmm(getattr(self, name))
            except ValueError:
                setattr(self, name, getattr(defaults, name))
        if not 1 <= self.smtp_port <= 65535:
            self.smtp_port = defaults.smtp_port
        self.forecast_months = max(1, min(36, self.forecast_months))
        self.notify_days_before = max(0, min(7, self.notify_days_before))
        self.low_balance_threshold = max(0, self.low_balance_threshold)
        self.debt_fixed_extra = max(0, self.debt_fixed_extra)
        self.currency_symbol = self.currency_symbol.strip()[:4] or defaults.currency_symbol
        self.account_name = self.account_name.strip() or defaults.account_name


def _coerce(value, kind: type):
    """Convert a JSON value to the type of a settings field."""
    if value is None:
        raise TypeError("missing value")
    if kind is bool:
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("true", "yes", "1"):
                return True
            if text in ("false", "no", "0", ""):
                return False
            raise ValueError(f"Not a yes/no value: {value!r}")
        return bool(value)
    if kind is int:
        return int(round(float(value)))
    if kind is float:
        return float(value)
    return str(value)


@dataclass
class AppData:
    items: list[RecurringItem] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    debts: list[Debt] = field(default_factory=list)
    # card_paid_key() values of card charges the user has marked as paid off
    card_paid: list[str] = field(default_factory=list)
    # Sync bookkeeping: id -> UTC time it was deleted; when shared settings last changed
    deleted: dict = field(default_factory=dict)
    settings_updated: str = ""
    settings: Settings = field(default_factory=Settings)

    # ---- convenience -------------------------------------------------
    @property
    def has_start(self) -> bool:
        return bool(self.checkpoints)

    def sorted_checkpoints(self) -> list[Checkpoint]:
        return sorted(self.checkpoints, key=lambda c: (c.date, c.created_at))

    @property
    def start(self) -> Checkpoint | None:
        cps = self.sorted_checkpoints()
        return cps[0] if cps else None

    @property
    def latest_checkpoint(self) -> Checkpoint | None:
        cps = self.sorted_checkpoints()
        return cps[-1] if cps else None

    def item(self, item_id: str) -> RecurringItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def debt(self, debt_id: str) -> Debt | None:
        return next((d for d in self.debts if d.id == debt_id), None)

    def checkpoint(self, cp_id: str) -> Checkpoint | None:
        return next((c for c in self.checkpoints if c.id == cp_id), None)

    def card_for(self, item: RecurringItem) -> Debt | None:
        """The credit card a bill is charged to, if any."""
        return self.debt(item.paid_with) if item.paid_with else None

    def add_checkpoint(self, cp: Checkpoint) -> None:
        """Add a checkpoint, replacing any other checkpoint on the same day."""
        self.checkpoints = [c for c in self.checkpoints if c.date != cp.date]
        self.checkpoints.append(cp)

    def categories(self) -> list[str]:
        return sorted({i.category for i in self.items if i.category}, key=str.lower)

    # ---- serialisation -----------------------------------------------
    def to_dict(self) -> dict:
        return {
            "app": "BalanceTracker",
            "schema": SCHEMA_VERSION,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "settings": self.settings.to_dict(),
            "items": [i.to_dict() for i in self.items],
            "checkpoints": [c.to_dict() for c in self.sorted_checkpoints()],
            "debts": [d.to_dict() for d in self.debts],
            "card_paid": sorted(self.card_paid)[-500:],
            "deleted": dict(self.deleted),
            "settings_updated": self.settings_updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AppData:
        if not isinstance(d, dict) or "items" not in d:
            raise ValueError("This file is not a Balance Tracker backup.")
        if int(d.get("schema", 1)) > SCHEMA_VERSION:
            raise ValueError("This backup was made by a newer version of Balance Tracker.")
        return cls(
            items=[RecurringItem.from_dict(i) for i in d.get("items", [])],
            checkpoints=[Checkpoint.from_dict(c) for c in d.get("checkpoints", [])],
            debts=[Debt.from_dict(x) for x in d.get("debts", [])],
            card_paid=[str(k) for k in d.get("card_paid", [])],
            deleted={str(k): str(v) for k, v in (d.get("deleted") or {}).items()},
            settings_updated=str(d.get("settings_updated") or ""),
            settings=Settings.from_dict(d.get("settings", {})),
        )
