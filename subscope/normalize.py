"""Bill normalisation: Alipay / WeChat / bank CSV -> one record shape.

Every downstream rule sees the same record, so detection logic never has to
know where a bill came from.  Money is integer cents from here on -- floats
never reach the detectors.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import re

# Record keys: date (YYYY-MM-DD), merchant, amount_cents, direction, source.
DIRECTION_OUT = "out"
DIRECTION_IN = "in"

_AMOUNT = re.compile(r"-?\d+(?:\.\d+)?")
_DATE_SPLIT = re.compile(r"[\sT]+")


class BillError(ValueError):
    """Raised for a bill row that cannot be interpreted at all."""


def parse_amount_cents(raw: str) -> int:
    """'12.00' / '¥12.00' / '-3.50' -> 1200 / 1200 / -350 (integer cents)."""
    if raw is None:
        raise BillError("empty amount")
    text = str(raw).strip()
    if not text:
        raise BillError("empty amount")
    match = _AMOUNT.search(text)
    if not match:
        raise BillError("no numeric amount in %r" % raw)
    value = float(match.group(0))
    # Round once, at the boundary, then never touch floats again.
    return int(round(value * 100))


def parse_date(raw: str) -> str:
    """'2026-01-05 12:34:56' / '2026/1/5' / '2026.01.05' -> '2026-01-05'."""
    if raw is None:
        raise BillError("empty date")
    text = str(raw).strip()
    if not text:
        raise BillError("empty date")
    head = _DATE_SPLIT.split(text)[0]
    for sep in ("-", "/", "."):
        if sep in head:
            parts = head.split(sep)
            if len(parts) == 3:
                y, m, d = (int(p) for p in parts)
                return "%04d-%02d-%02d" % (y, m, d)
    raise BillError("unparseable date %r" % raw)


def to_date(iso: str) -> _dt.date:
    y, m, d = (int(p) for p in iso.split("-"))
    return _dt.date(y, m, d)


def normalise_merchant(raw: str) -> str:
    """Collapse whitespace and strip decoration so the same payee groups once."""
    text = " ".join(str(raw or "").split())
    return text.strip("* ").upper()


# ---------------------------------------------------------------- sources
# Each adapter returns records for OUT rows only by default; refunds (IN) are
# kept because a refunded subscription charge is itself a signal.

def _rows(text: str):
    return list(csv.DictReader(io.StringIO(text)))


def _pick(row: dict, *names):
    """First non-empty value among candidate column names (and substrings)."""
    for name in names:
        for key in row:
            if key and name in key:
                value = row[key]
                if value is not None and str(value).strip():
                    return str(value).strip()
    return ""


def from_alipay(text: str) -> list:
    """Alipay export: 交易时间 / 交易对方 / 收支 / 金额."""
    out = []
    for row in _rows(text):
        raw_date = _pick(row, "交易时间", "日期")
        if not raw_date:
            continue
        amount = parse_amount_cents(_pick(row, "金额"))
        if amount == 0:
            continue
        flag = _pick(row, "收/支", "收支")
        # Alipay exports carry neutral rows ("不计收支": refunds, internal
        # transfers).  Classifying them as spending would invent charges that
        # never left the account, so they are dropped here.
        if flag == "支出":
            direction = DIRECTION_OUT
        elif flag == "收入":
            direction = DIRECTION_IN
        else:
            continue
        out.append({
            "date": parse_date(raw_date),
            "merchant": normalise_merchant(_pick(row, "交易对方", "对方")),
            "amount_cents": abs(amount),
            "direction": direction,
            "source": "alipay",
        })
    return out


def from_wechat(text: str) -> list:
    """WeChat export: 交易时间 / 交易对方 / 收/支 / 金额(元)."""
    out = []
    for row in _rows(text):
        raw_date = _pick(row, "交易时间", "日期")
        if not raw_date:
            continue
        amount = parse_amount_cents(_pick(row, "金额"))
        if amount == 0:
            continue
        flag = _pick(row, "收/支", "收支")
        # WeChat writes "/" for neutral rows.  Only explicit 支出/收入 count.
        if flag == "支出":
            direction = DIRECTION_OUT
        elif flag == "收入":
            direction = DIRECTION_IN
        else:
            continue
        out.append({
            "date": parse_date(raw_date),
            "merchant": normalise_merchant(_pick(row, "交易对方", "对方")),
            "amount_cents": abs(amount),
            "direction": direction,
            "source": "wechat",
        })
    return out


def from_bank(text: str) -> list:
    """Generic bank export: 日期 / 摘要(对手) / 金额 (negative = outgoing)."""
    out = []
    for row in _rows(text):
        raw_date = _pick(row, "日期", "交易时间", "date")
        if not raw_date:
            continue
        amount = parse_amount_cents(_pick(row, "金额", "amount"))
        if amount == 0:
            continue
        out.append({
            "date": parse_date(raw_date),
            "merchant": normalise_merchant(_pick(row, "摘要", "对手", "对方", "merchant")),
            "amount_cents": abs(amount),
            "direction": DIRECTION_OUT if amount < 0 else DIRECTION_IN,
            "source": "bank",
        })
    return out


ADAPTERS = {"alipay": from_alipay, "wechat": from_wechat, "bank": from_bank}


def load(text: str, source: str) -> list:
    if source not in ADAPTERS:
        raise BillError("unknown source %r" % source)
    return ADAPTERS[source](text)


def merge(*groups) -> list:
    """Merge sources and sort by date. Stable: equal dates keep source order."""
    rows = [r for g in groups for r in g]
    return sorted(rows, key=lambda r: (r["date"], r["source"], r["merchant"]))
