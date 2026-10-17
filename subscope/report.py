"""Report rendering: plain text for humans, JSON for pipes.

Money never appears as a float. `fmt_cents` is the only place cents become a
decimal string, and it formats -- it never computes.
"""

from __future__ import annotations

import json


def fmt_cents(cents: int) -> str:
    """123456 -> '1,234.56'"""
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    whole, frac = divmod(cents, 100)
    # format(x, ",") is locale-independent: the grouping separator is always a
    # comma, even under LC_ALL=C where a locale-aware formatter would differ.
    return "%s%s.%02d" % (sign, format(whole, ","), frac)


def money(cents: int) -> str:
    return "CNY " + fmt_cents(cents)


def render_text(result: dict, as_of: str = "") -> str:
    subs = result["subscriptions"]
    dupes = result["duplicates"]
    lines = []
    lines.append("SubScope report" + (("  as of " + as_of) if as_of else ""))
    lines.append("=" * 58)
    lines.append("subscriptions      : %d" % result["subscription_count"])
    lines.append("annual drain       : %s" % money(result["annual_total_cents"]))
    lines.append("already paid       : %s" % money(result["lifetime_total_cents"]))
    lines.append("duplicate waste    : %s" % money(result["duplicate_total_cents"]))
    lines.append("")

    if not subs:
        lines.append("No recurring charge reached %d repeats. Nothing to cancel."
                     % 3)
    else:
        lines.append("%-28s %-10s %6s %12s  flags" % (
            "merchant", "period", "n", "annual"))
        lines.append("-" * 58)
        for s in subs:
            flags = []
            if s["trial_conversion"]:
                flags.append("trial->paid")
            if s["raise_count"]:
                flags.append("raised x%d" % s["raise_count"])
            if s["micro_drain"]:
                flags.append("micro-drain")
            if s["dormant_months"] >= 12:
                flags.append("%dmo" % s["dormant_months"])
            name = s["merchant"]
            if len(name) > 28:
                name = name[:25] + "..."
            lines.append("%-28s %-10s %6d %12s  %s" % (
                name, s["period"], s["charges"],
                fmt_cents(s["annual_cents"]), " ".join(flags)))
        lines.append("")
        top = subs[0]
        lines.append("biggest: %s at %s/year (%s every %s)" % (
            top["merchant"], money(top["annual_cents"]),
            money(top["current_cents"]), top["period"]))

    if dupes:
        lines.append("")
        lines.append("possible double charges:")
        for d in dupes:
            lines.append("  %s x%d on %s -> %s wasted" % (
                d["merchant"], d["count"], ", ".join(d["dates"]),
                money(d["wasted_cents"])))
    return "\n".join(lines)


def render_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)


def to_json(result: dict) -> str:
    """ASCII-safe JSON for pipes and tests (non-ASCII escaped)."""
    return json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True)
