"""Money formatting helpers (values are integer cents)."""
from __future__ import annotations

_symbol = "$"


def set_symbol(symbol: str) -> None:
    global _symbol
    _symbol = symbol or "$"


def fmt(cents: int | None, signed: bool = False) -> str:
    if cents is None:
        return "—"
    neg = cents < 0
    body = f"{_symbol}{abs(cents) / 100:,.2f}"
    if neg:
        return f"−{body}"
    if signed and cents > 0:
        return f"+{body}"
    return body


def fmt_short(cents: int) -> str:
    """Compact form for chart axes: $1.2k, −$350."""
    v = cents / 100
    sign = "−" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000:
        return f"{sign}{_symbol}{v / 1_000_000:.1f}M"
    if v >= 10_000:
        return f"{sign}{_symbol}{v / 1000:.0f}k"
    if v >= 1000:
        k = f"{v / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{_symbol}{k}k"
    return f"{sign}{_symbol}{v:.0f}"


def to_cents(value: float) -> int:
    return int(round(value * 100))
