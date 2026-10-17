# SubScope

**The subscription bill you agreed to, and the one you are actually paying.**

A recurring charge is priced to be ignored: fifteen yuan a month, renewed
silently, raised quietly, started as a one-cent trial. Nobody cancels because
nobody adds it up. SubScope reads a bill file and reports every recurring
charge **by what it costs per year**, not per month — then flags the ones that
changed.

```
$ python demo.py

SubScope report
==========================================================
subscriptions      : 5
annual drain       : CNY 1,158.00
already paid       : CNY 983.01
duplicate waste    : CNY 32.00

merchant                     period          n       annual  flags
----------------------------------------------------------
FITNESS COACH APP            monthly         4       300.00  trial->paid raised x1
VIDEO PLUS                   monthly         5       300.00  raised x1
DESIGN SUITE PRO             yearly          3       198.00  24mo
CLOUD STORAGE PLUS           monthly         7       180.00  raised x2 micro-drain
NETEASE CLOUD MUSIC          monthly         8       180.00  micro-drain

possible double charges:
  MORNING COFFEE x2 on 2026-06-18, 2026-06-18 -> CNY 32.00 wasted
```

## Run it

```bash
python eval.py     # 80 assertions, offline, stdlib only
python demo.py     # a year of ordinary spending, and what nobody noticed
```

Zero network, zero API keys, zero third-party packages.

## What it finds

| Signal | What it means | How it is derived |
|---|---|---|
| **Recurring charge** | this is a subscription, not a purchase | ≥3 charges to the same merchant whose **median** gap lands in a period band |
| **Annual cost** | what it actually costs you | last price × 12 / 52 / 4 / 1 by period |
| **Price rise** | it went up and you did not notice | the amount sequence is not flat; count and total increase reported |
| **Trial → paid** | the one-cent trial became a subscription | first charge ≤ ¥1.00 and the current one is not |
| **Micro-drain** | cheap per charge, expensive per year | ≤ ¥15 per charge but ≥ ¥100 a year |
| **Dormancy** | how long this has been quietly renewing | months between first and last charge |
| **Double charge** | the same thing billed twice | same merchant, same amount, inside 24h |

## Design contract

* **stdlib only** — runs anywhere Python runs
* **no model in the detection path** — "you are being charged every month" is
  arithmetic, not an inference. A model would make it probabilistic and worse.
* **integer cents** — money never touches a float
* **deterministic** — the same bill file produces byte-identical output; nothing
  here reads the wall clock
* **no cloud** — the bill file is parsed locally. A tool that reads everything
  you spent money on should not be uploading it.

## Why median, not mean

One skipped month produces a gap of ~60 days. Averaged into a monthly
subscription that drags the period toward quarterly and the subscription
vanishes from the report entirely — the worst possible failure, because the
output still looks plausible. The median ignores it. This is asserted:
`[30, 31, 28, 90]` must still classify as monthly.

## Normalisation

Alipay, WeChat and generic bank exports disagree on column names, date
formats, sign conventions and what counts as a charge. One adapter per source
collapses them into a single record shape, so detection never knows where a
bill came from.

Two details that matter more than they look:

* **Neutral rows are dropped.** Alipay exports `不计收支` — refunds and internal
  transfers. Classifying those as spending invents charges that never left the
  account.
* **Merchants are upper-cased and whitespace-collapsed**, so one payee groups
  once.

## Layout

```
subscope/normalize.py   Alipay / WeChat / bank -> one record shape (cents)
subscope/detect.py      period classification, subscriptions, duplicates
subscope/report.py      text + JSON rendering (money formatted once, here)
eval.py                 80 assertions (incl. a real LC_ALL=C subprocess run)
demo.py                 a full year of bills, end to end
```

## License

MIT
