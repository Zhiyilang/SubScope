"""SubScope demo -- an ordinary bill file, and what nobody noticed.

Run:  python demo.py
Offline, stdlib only, no API keys.

Merchant names are ASCII here on purpose: the suite also runs under LC_ALL=C
in CI, and a CJK byte on stdout would crash the demo rather than the code.
Real bill files may of course contain CJK -- report.to_json escapes them.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from subscope import detect, normalize, report  # noqa: E402

# A year of ordinary spending: one streaming service, one cloud plan that
# quietly went up, one "free" trial that was never free, one design tool paid
# yearly, one coffee shop charged twice on a bad connection, and a salary.
ALIPAY = """交易时间,交易对方,收/支,金额
2025-11-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2025-12-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2026-01-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2026-02-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2026-03-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2026-04-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2026-05-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2026-06-05 09:12:00,NETEASE CLOUD MUSIC,支出,15.00
2025-12-01 08:00:00,CLOUD STORAGE PLUS,支出,10.00
2026-01-01 08:00:00,CLOUD STORAGE PLUS,支出,10.00
2026-02-01 08:00:00,CLOUD STORAGE PLUS,支出,10.00
2026-03-01 08:00:00,CLOUD STORAGE PLUS,支出,12.00
2026-04-01 08:00:00,CLOUD STORAGE PLUS,支出,12.00
2026-05-01 08:00:00,CLOUD STORAGE PLUS,支出,15.00
2026-06-01 08:00:00,CLOUD STORAGE PLUS,支出,15.00
2026-03-11 20:00:00,FITNESS COACH APP,支出,0.01
2026-04-11 20:00:00,FITNESS COACH APP,支出,25.00
2026-05-11 20:00:00,FITNESS COACH APP,支出,25.00
2026-06-11 20:00:00,FITNESS COACH APP,支出,25.00
2024-07-20 10:00:00,DESIGN SUITE PRO,支出,198.00
2025-07-20 10:00:00,DESIGN SUITE PRO,支出,198.00
2026-07-20 10:00:00,DESIGN SUITE PRO,支出,198.00
2026-06-18 13:05:00,MORNING COFFEE,支出,32.00
2026-06-18 13:05:00,MORNING COFFEE,支出,32.00
2026-01-10 10:00:00,EMPLOYER PAYROLL,收入,12000.00
2026-06-30 10:00:00,CARD REFUND,不计收支,50.00
"""

WECHAT = """交易时间,交易对方,收/支,金额(元)
2026-02-14 21:00:00,VIDEO PLUS,支出,20.00
2026-03-14 21:00:00,VIDEO PLUS,支出,20.00
2026-04-14 21:00:00,VIDEO PLUS,支出,20.00
2026-05-14 21:00:00,VIDEO PLUS,支出,25.00
2026-06-14 21:00:00,VIDEO PLUS,支出,25.00
"""


def main() -> int:
    rows = normalize.merge(normalize.load(ALIPAY, "alipay"),
                           normalize.load(WECHAT, "wechat"))
    print("parsed %d bill rows (%d outgoing)"
          % (len(rows), sum(1 for r in rows if r["direction"] == "out")))
    print()
    result = detect.scan(rows)
    print(report.render_text(result))
    print()
    print("what to actually do about it:")
    for s in result["subscriptions"]:
        note = []
        if s["trial_conversion"]:
            note.append("started as a 0.01 trial, now %s/month" % report.money(s["current_cents"]))
        if s["raise_count"]:
            note.append("price went up %d time(s), +%s per charge"
                        % (s["raise_count"], report.money(s["raise_cents"])))
        if s["micro_drain"]:
            note.append("small per charge, %s a year" % report.money(s["annual_cents"]))
        if note:
            print("  - %-22s %s" % (s["merchant"], "; ".join(note)))
        else:
            print("  - %-22s steady at %s/year" % (s["merchant"], report.money(s["annual_cents"])))
    if result["duplicates"]:
        print()
        print("  double charges worth disputing:")
        for d in result["duplicates"]:
            print("    %s on %s -> %s"
                  % (d["merchant"], ", ".join(d["dates"]), report.money(d["wasted_cents"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
