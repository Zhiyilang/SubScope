"""Subscription detection: deterministic, integer-cent, no model in the loop.

The whole point of SubScope is that "you are being silently charged" is an
arithmetic fact, not an opinion.  Every number in the report is derived by
subtraction and median -- there is no model anywhere in this path, so the same
bill file always produces the same report.

Money is integer cents.  Dates are ISO strings.  Nothing here reads the wall
clock: the same bill file always produces byte-identical output.
"""

from __future__ import annotations

import datetime as _dt
import statistics

from .normalize import DIRECTION_OUT, to_date

# (name, nominal days, tolerance).  Ordered smallest first: the first match
# wins, and the bands do not overlap.
PERIODS = (
    ("weekly", 7, 2),
    ("biweekly", 14, 3),
    ("monthly", 30, 6),
    ("quarterly", 91, 12),
    ("yearly", 365, 20),
)

ANNUAL_MULTIPLIER = {
    "weekly": 52,
    "biweekly": 26,
    "monthly": 12,
    "quarterly": 4,
    "yearly": 1,
}

MIN_REPEATS = 3          # fewer charges than this and "subscription" is a guess
TRIAL_CEILING_CENTS = 100    # first charge <= 1.00 smells like a trial
MICRO_AMOUNT_CENTS = 1500    # <= 15.00 per charge
MICRO_DRAIN_CENTS = 10000    # ...but >= 100.00 a year is still a drain
DUPLICATE_WINDOW_DAYS = 1


def classify_period(gaps: list):
    """Median gap -> period name, or None. Median, not mean: one late charge
    must not drag a monthly subscription into the quarterly band."""
    if not gaps:
        return None
    median = statistics.median(gaps)
    for name, nominal, tol in PERIODS:
        if nominal - tol <= median <= nominal + tol:
            return name
    return None


def annualize_cents(amount_cents: int, period: str) -> int:
    """What this costs per year at the current price."""
    return amount_cents * ANNUAL_MULTIPLIER[period]


def detect_subscriptions(records: list, min_repeats: int = MIN_REPEATS) -> list:
    """Group outgoing charges by merchant, find the recurring ones."""
    groups = {}
    for rec in records:
        if rec["direction"] != DIRECTION_OUT:
            continue
        groups.setdefault(rec["merchant"], []).append(rec)

    subs = []
    for merchant, rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda r: r["date"])
        if len(rows) < min_repeats:
            continue
        dates = [to_date(r["date"]) for r in rows]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        period = classify_period(gaps)
        if period is None:
            continue
        amounts = [r["amount_cents"] for r in rows]
        current = amounts[-1]
        raises = [j for j in range(1, len(amounts)) if amounts[j] > amounts[j - 1]]
        subs.append({
            "merchant": merchant,
            "period": period,
            "charges": len(rows),
            "first_date": rows[0]["date"],
            "last_date": rows[-1]["date"],
            "amounts_cents": amounts,
            "current_cents": current,
            "annual_cents": annualize_cents(current, period),
            "lifetime_cents": sum(amounts),
            "raise_count": len(raises),
            "raise_cents": (current - amounts[0]) if raises else 0,
            "trial_conversion": (amounts[0] <= TRIAL_CEILING_CENTS
                                 and current > TRIAL_CEILING_CENTS),
            "micro_drain": (current <= MICRO_AMOUNT_CENTS
                            and annualize_cents(current, period) >= MICRO_DRAIN_CENTS),
            "dormant_months": _months(dates[0], dates[-1]),
            "sources": sorted({r["source"] for r in rows}),
        })

    subs.sort(key=lambda s: (-s["annual_cents"], s["merchant"]))
    return subs


def _months(first: _dt.date, last: _dt.date) -> int:
    return int(round((last - first).days / 30.44))


def detect_duplicates(records: list,
                      window_days: int = DUPLICATE_WINDOW_DAYS) -> list:
    """Same merchant, same amount, charged twice inside the window."""
    buckets = {}
    for rec in records:
        if rec["direction"] != DIRECTION_OUT:
            continue
        key = (rec["merchant"], rec["amount_cents"])
        buckets.setdefault(key, []).append(rec)

    dupes = []
    for (merchant, amount), rows in sorted(buckets.items()):
        rows = sorted(rows, key=lambda r: r["date"])
        run = [rows[0]]
        for prev, cur in zip(rows, rows[1:]):
            if (to_date(cur["date"]) - to_date(prev["date"])).days <= window_days:
                run.append(cur)
            else:
                if len(run) >= 2:
                    dupes.append(_dupe(merchant, amount, run))
                run = [cur]
        if len(run) >= 2:
            dupes.append(_dupe(merchant, amount, run))
    return dupes


def _dupe(merchant, amount, run):
    return {
        "merchant": merchant,
        "amount_cents": amount,
        "count": len(run),
        "dates": [r["date"] for r in run],
        "wasted_cents": amount * (len(run) - 1),
    }


def scan(records: list, min_repeats: int = MIN_REPEATS) -> dict:
    """One pass: everything the report needs."""
    subs = detect_subscriptions(records, min_repeats=min_repeats)
    dupes = detect_duplicates(records)
    return {
        "subscriptions": subs,
        "duplicates": dupes,
        "subscription_count": len(subs),
        "annual_total_cents": sum(s["annual_cents"] for s in subs),
        "lifetime_total_cents": sum(s["lifetime_cents"] for s in subs),
        "duplicate_total_cents": sum(d["wasted_cents"] for d in dupes),
        "flagged": [s for s in subs
                    if s["trial_conversion"] or s["raise_count"] or s["micro_drain"]],
    }
