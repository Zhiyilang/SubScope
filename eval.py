"""SubScope assertion suite -- stdlib only, no network, deterministic.

Run:  python eval.py
Exit: 0 when every assertion passes, 1 on the first failure.

Output is deliberately ASCII-only: this suite also runs under a hostile locale
(LC_ALL=C with no PYTHONUTF8) in CI, where a stray CJK byte would crash the
harness rather than the thing under test.  Merchant names in the fixtures are
ASCII for the same reason -- real bills may contain CJK, which is why
report.to_json escapes non-ASCII and is asserted to below.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from subscope import detect, normalize, report  # noqa: E402
from subscope.normalize import BillError  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        FAILURES.append(name)
        print("  FAIL %s %s" % (name, detail))


def expect_raises(name, fn, exc_type):
    try:
        fn()
    except exc_type:
        check(name, True)
    except Exception as exc:  # noqa: BLE001
        check(name, False, "raised %s not %s" % (type(exc).__name__, exc_type.__name__))
    else:
        check(name, False, "did not raise")


def alipay_csv(rows):
    """rows: (date, merchant, flag, amount)"""
    lines = ["交易时间,交易对方,收/支,金额"]
    for d, m, f, a in rows:
        lines.append("%s,%s,%s,%s" % (d, m, f, a))
    return "\n".join(lines) + "\n"


def rec(date, merchant, cents, direction="out", source="alipay"):
    return {"date": date, "merchant": merchant, "amount_cents": cents,
            "direction": direction, "source": source}


# ------------------------------------------------------------- normalisation
def test_normalize():
    print("\n[normalise]")
    check("plain amount", normalize.parse_amount_cents("12.00") == 1200)
    check("currency-symbol amount", normalize.parse_amount_cents("¥12.00") == 1200)
    check("wechat style amount", normalize.parse_amount_cents("¥3.50") == 350)
    check("negative amount", normalize.parse_amount_cents("-3.50") == -350)
    check("integer amount", normalize.parse_amount_cents("12") == 1200)
    expect_raises("empty amount raises", lambda: normalize.parse_amount_cents(""), BillError)
    expect_raises("non-numeric amount raises",
                  lambda: normalize.parse_amount_cents("abc"), BillError)

    check("datetime collapses to date",
          normalize.parse_date("2026-01-05 12:34:56") == "2026-01-05")
    check("slash date", normalize.parse_date("2026/1/5") == "2026-01-05")
    check("dot date", normalize.parse_date("2026.01.05") == "2026-01-05")
    expect_raises("garbage date raises",
                  lambda: normalize.parse_date("tomorrow"), BillError)

    check("merchant upper-cased",
          normalize.normalise_merchant("netease music") == "NETEASE MUSIC")
    check("merchant whitespace collapsed",
          normalize.normalise_merchant("  netease   music ") == "NETEASE MUSIC")

    # The neutral-row rule: Alipay exports "不计收支" for refunds and internal
    # transfers.  Treating those as spending invents charges.
    text = alipay_csv([
        ("2026-01-05 10:00:00", "NETEASE MUSIC", "支出", "15.00"),
        ("2026-01-06 10:00:00", "SOME REFUND", "不计收支", "99.00"),
        ("2026-01-07 10:00:00", "SALARY CO", "收入", "5000.00"),
    ])
    rows = normalize.load(text, "alipay")
    check("neutral row dropped", len(rows) == 2, "got %d" % len(rows))
    check("outgoing row kept",
          any(r["merchant"] == "NETEASE MUSIC" and r["direction"] == "out" for r in rows))
    check("incoming row kept",
          any(r["merchant"] == "SALARY CO" and r["direction"] == "in" for r in rows))
    check("zero amount row dropped",
          len(normalize.load(alipay_csv([("2026-01-05 10:00:00", "X", "支出", "0.00")]),
                             "alipay")) == 0)

    bank = "日期,摘要,金额\n2026-01-05,COFFEE,-30.00\n2026-01-06,REFUND,12.00\n"
    rows = normalize.load(bank, "bank")
    check("bank negative is outgoing", rows[0]["direction"] == "out")
    check("bank positive is incoming", rows[1]["direction"] == "in")
    check("bank amount absolute", rows[0]["amount_cents"] == 3000)

    expect_raises("unknown source raises",
                  lambda: normalize.load(bank, "venmo"), BillError)

    merged = normalize.merge(
        normalize.load(alipay_csv([("2026-03-01 10:00:00", "A", "支出", "1.00")]), "alipay"),
        normalize.load(alipay_csv([("2026-01-01 10:00:00", "B", "支出", "2.00")]), "alipay"),
    )
    check("merge sorts by date", merged[0]["merchant"] == "B")


# ------------------------------------------------------------------ period
def test_period():
    print("\n[period classification]")
    check("weekly", detect.classify_period([7, 7, 7]) == "weekly")
    check("biweekly", detect.classify_period([14, 14]) == "biweekly")
    check("monthly with real month lengths",
          detect.classify_period([31, 28, 31, 30]) == "monthly")
    check("quarterly", detect.classify_period([91, 92, 90]) == "quarterly")
    check("yearly", detect.classify_period([365, 366]) == "yearly")
    # The whole reason for median: one gap of 90 (a skipped month, a manual
    # renewal) must not reclassify a monthly subscription as quarterly.
    check("median resists an outlier gap",
          detect.classify_period([30, 31, 28, 90]) == "monthly",
          "mean would give 44.75 -> no period at all")
    check("no period for random gaps", detect.classify_period([3, 45, 200]) is None)
    check("empty gaps give no period", detect.classify_period([]) is None)

    check("annualize monthly", detect.annualize_cents(1500, "monthly") == 18000)
    check("annualize yearly", detect.annualize_cents(19800, "yearly") == 19800)
    check("annualize weekly", detect.annualize_cents(600, "weekly") == 31200)


# ------------------------------------------------------------ subscriptions
def monthly(merchant, cents, months, start=(2026, 1, 5)):
    rows = []
    y, m, d = start
    for i in range(months):
        mm = m + i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        rows.append(rec("%04d-%02d-%02d" % (yy, mm, d), merchant, cents))
    return rows


def test_subscriptions():
    print("\n[subscription detection]")
    rows = monthly("NETEASE MUSIC", 1500, 4)
    subs = detect.detect_subscriptions(rows)
    check("monthly subscription found", len(subs) == 1)
    if subs:
        s = subs[0]
        check("period is monthly", s["period"] == "monthly")
        check("charge count", s["charges"] == 4)
        check("current price", s["current_cents"] == 1500)
        check("annual cost", s["annual_cents"] == 18000)
        check("lifetime cost", s["lifetime_cents"] == 6000)
        check("no raise recorded", s["raise_count"] == 0)
        check("small monthly fee is a micro-drain", s["micro_drain"])
        check("dormant months counted", s["dormant_months"] == 3)

    check("two charges are not a subscription",
          detect.detect_subscriptions(monthly("ONE OFF", 1500, 2)) == [])
    check("random dates are not a subscription",
          detect.detect_subscriptions([
              rec("2026-01-05", "X", 100), rec("2026-02-20", "X", 100),
              rec("2026-06-01", "X", 100)]) == [])
    check("refunds do not form a subscription",
          detect.detect_subscriptions(
              monthly("REFUNDED", 1500, 3) +
              [rec("2026-04-05", "REFUNDED", 1500, "in")]) [0]["charges"] == 3)

    # yearly: three annual renewals
    yearly = [rec("2024-03-01", "IQiyi", 19800), rec("2025-03-01", "IQiyi", 19800),
              rec("2026-03-01", "IQiyi", 19800)]
    subs = detect.detect_subscriptions(yearly)
    check("yearly subscription found", len(subs) == 1)
    check("yearly period", subs[0]["period"] == "yearly")
    check("yearly annual cost equals the charge", subs[0]["annual_cents"] == 19800)

    # A price rise is the signal people never notice.
    raised = monthly("CLOUD STORAGE", 1000, 2) + [rec("2026-03-05", "CLOUD STORAGE", 1500)]
    subs = detect.detect_subscriptions(raised)
    check("raised subscription still detected", len(subs) == 1)
    check("raise counted", subs[0]["raise_count"] == 1)
    check("raise amount", subs[0]["raise_cents"] == 500)
    check("current price is the new one", subs[0]["current_cents"] == 1500)

    # Free trial that quietly became a paid subscription.
    trial = [rec("2026-01-05", "FITNESS", 1), rec("2026-02-05", "FITNESS", 2500),
             rec("2026-03-05", "FITNESS", 2500)]
    subs = detect.detect_subscriptions(trial)
    check("trial conversion flagged", subs[0]["trial_conversion"])
    check("trial annual cost uses the real price", subs[0]["annual_cents"] == 30000)

    check("expensive monthly fee is not a micro-drain",
          not detect.detect_subscriptions(monthly("BIG SUITE", 50000, 3))[0]["micro_drain"])


def test_duplicates():
    print("\n[duplicate charges]")
    rows = [rec("2026-05-01", "SHOP", 3000), rec("2026-05-01", "SHOP", 3000)]
    dupes = detect.detect_duplicates(rows)
    check("same-day double charge found", len(dupes) == 1)
    check("duplicate count", dupes[0]["count"] == 2)
    check("wasted amount", dupes[0]["wasted_cents"] == 3000)

    rows = [rec("2026-05-01", "SHOP", 3000), rec("2026-05-09", "SHOP", 3000)]
    check("charges a week apart are not duplicates",
          detect.detect_duplicates(rows) == [])

    rows = [rec("2026-05-01", "SHOP", 3000), rec("2026-05-01", "OTHER", 3000)]
    check("different merchants are not duplicates",
          detect.detect_duplicates(rows) == [])

    rows = [rec("2026-05-01", "SHOP", 3000), rec("2026-05-02", "SHOP", 3000),
            rec("2026-05-03", "SHOP", 3000)]
    dupes = detect.detect_duplicates(rows)
    check("three-in-a-row reported once", len(dupes) == 1)
    check("three charges waste two", dupes[0]["wasted_cents"] == 6000)


def test_scan_and_report():
    print("\n[scan + report]")
    rows = monthly("NETEASE MUSIC", 1500, 4) + \
        [rec("2024-03-01", "IQiyi", 19800), rec("2025-03-01", "IQiyi", 19800),
         rec("2026-03-01", "IQiyi", 19800)]
    result = detect.scan(rows)
    check("two subscriptions", result["subscription_count"] == 2)
    check("annual total is the sum",
          result["annual_total_cents"] == 18000 + 19800)
    check("ranked by annual cost",
          result["subscriptions"][0]["merchant"] == "IQiyi")

    again = detect.scan(copy.deepcopy(rows))
    check("scan is deterministic", result == again)

    text = report.render_text(result)
    check("report has a header", "SubScope report" in text)
    check("report shows the annual drain", "378.00" in text)
    check("report names the biggest one", "biggest: IQiyi" in text)
    check("empty scan renders without crashing",
          "No recurring charge" in report.render_text(detect.scan([])))

    check("fmt_cents groups thousands", report.fmt_cents(123456) == "1,234.56")
    check("fmt_cents pads cents", report.fmt_cents(5) == "0.05")
    check("fmt_cents handles negatives", report.fmt_cents(-1500) == "-15.00")
    check("money prefixes CNY", report.money(1500) == "CNY 15.00")

    # A real bill file is full of CJK merchant names.  JSON meant for a pipe
    # must survive an ascii-only stdout, so to_json escapes them.
    cjk = detect.scan(monthly("网易云音乐", 1500, 3))
    encoded = report.to_json(cjk)
    check("to_json is ascii-safe", all(ord(ch) < 128 for ch in encoded),
          "non-ascii byte would crash an LC_ALL=C pipe")
    check("to_json still parses", json.loads(encoded)["subscription_count"] == 1)
    check("render_json keeps readable text", "网易云音乐" in report.render_json(cjk))


def test_hostile_locale():
    print("\n[hostile locale]")
    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["PYTHONIOENCODING"] = "ascii"
    # Without this the child re-enters this test and forks forever.
    env["SUBSCOPE_SKIP_LOCALE"] = "1"
    proc = subprocess.run([sys.executable, "eval.py"], cwd=here, env=env,
                          capture_output=True, text=True)
    check("suite exits 0 under LC_ALL=C", proc.returncode == 0,
          (proc.stderr or "")[-300:])
    check("suite prints EVAL_OK under LC_ALL=C",
          "EVAL_OK" in proc.stdout and "0 failed" in proc.stdout,
          (proc.stdout or "")[-300:])
    check("no assertion failed under LC_ALL=C", "FAIL " not in proc.stdout,
          (proc.stdout or "")[-300:])


def main():
    test_normalize()
    test_period()
    test_subscriptions()
    test_duplicates()
    test_scan_and_report()
    if os.environ.get("SUBSCOPE_SKIP_LOCALE"):
        print("\n[hostile locale] skipped")
    else:
        test_hostile_locale()
    print("\n%d passed, %d failed" % (PASS, FAIL))
    if FAIL:
        print("FAILED: %s" % ", ".join(FAILURES))
        return 1
    print("EVAL_OK assertions=%d" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
