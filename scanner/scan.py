#!/usr/bin/env python3
"""
MNQ Azarel 6-Step SMC scanner.

Pulls live MNQ data from TradingView Desktop (via the tv CLI, which talks to
the app over its local CDP debug port), applies the fractal-pivot /
close-confirmation logic for Solidified Highs & Lows, and writes a status
snapshot to data/status.json for the website to read.

Steps 1-3 (macro structure) are fully mechanical. Steps 4-6 (the retest zone,
1m micro shift, and execution) require judgment this script does not
attempt to replace -- it only reports whether price has re-entered the
Step 2 zone, and leaves the "is this actually a clean shift" call to a human
(or a future, more careful pass) rather than guessing.
"""
import json
import subprocess
import sys
import datetime
import os

TV_CLI = [sys.executable.replace("python3", "node")] if False else None
NODE_BIN = "node"
CLI_PATH = os.path.expanduser("~/tradingview-mcp/src/cli/index.js")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_PATH = os.path.join(REPO_ROOT, "site", "data", "status.json")

# Price levels this run reconfirms/extends from the manually-verified session
# (kept only as a fallback label; the live pivot detection below is authoritative)
FRACTAL_N = 2


def tv(*args):
    """Run a tv CLI command and parse its JSON output."""
    proc = subprocess.run(
        [NODE_BIN, CLI_PATH, *args],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tv {' '.join(args)} failed: {proc.stderr.strip()}")
    out = proc.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"tv {' '.join(args)} gave non-JSON output: {out[:300]}")


def et_str(unix_time):
    u = datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc)
    e = u - datetime.timedelta(hours=4)  # EDT (good enough for Aug)
    return e.strftime("%Y-%m-%d %H:%M ET")


def fractal_pivots(bars, n=FRACTAL_N):
    highs, lows = [], []
    for i in range(n, len(bars) - n):
        window = bars[i - n:i + n + 1]
        if bars[i]["high"] == max(b["high"] for b in window):
            highs.append(i)
        if bars[i]["low"] == min(b["low"] for b in window):
            lows.append(i)
    pivots = sorted([(i, "H", bars[i]["high"]) for i in highs] +
                     [(i, "L", bars[i]["low"]) for i in lows])
    cleaned = []
    for p in pivots:
        if cleaned and cleaned[-1][1] == p[1]:
            if p[1] == "H" and p[2] > cleaned[-1][2]:
                cleaned[-1] = p
            elif p[1] == "L" and p[2] < cleaned[-1][2]:
                cleaned[-1] = p
        else:
            cleaned.append(p)
    return cleaned


def confirm(pivots, bars):
    """For each pivot, find the bar (if any) whose close breaks the immediately
    preceding opposite-type pivot -- that's what "solidifies" it per the
    strategy's own definition."""
    results = []
    for idx, (i, typ, price) in enumerate(pivots):
        entry = {"index": i, "time": bars[i]["time"], "type": typ, "price": price,
                 "confirmed": False, "confirmed_at": None, "confirmed_price": None}
        if idx > 0:
            prev = pivots[idx - 1]
            target = prev[2]
            for b in bars[i + 1:]:
                if typ == "H" and b["close"] < target:
                    entry.update(confirmed=True, confirmed_at=b["time"], confirmed_price=b["close"])
                    break
                if typ == "L" and b["close"] > target:
                    entry.update(confirmed=True, confirmed_at=b["time"], confirmed_price=b["close"])
                    break
        results.append(entry)
    return results


NEWS_JS = (
    "(() => { try { "
    "const cards = Array.from(document.querySelectorAll('.card-B562enCp')); "
    "const items = cards.map(c => (c.textContent||'').trim().replace(/\\s+/g,' ').replace(/^News/,'').replace(/More events.*$/,'').trim()); "
    "return JSON.stringify(items); "
    "} catch(e) { return JSON.stringify([]); } })()"
)


def fetch_news():
    try:
        result = tv("ui", "eval", NEWS_JS)
        raw = result.get("result") if isinstance(result, dict) else result
        items = json.loads(raw) if isinstance(raw, str) else raw
        return items if items else []
    except Exception:
        return []


def main():
    tv("symbol", "MNQ1!")
    tv("timeframe", "60")
    ohlcv = tv("ohlcv", "-n", "80")
    bars = ohlcv["bars"]
    quote = tv("quote")
    price = quote["last"]

    pivots = fractal_pivots(bars)
    confirmed_pivots = confirm(pivots, bars)

    solidified_highs = [p for p in confirmed_pivots if p["type"] == "H" and p["confirmed"]]
    solidified_lows = [p for p in confirmed_pivots if p["type"] == "L" and p["confirmed"]]

    last_solidified_high = solidified_highs[-1] if solidified_highs else None
    last_solidified_low = solidified_lows[-1] if solidified_lows else None

    # Step 1: most recent confirmed solidified point that price has SINCE
    # broken back through in the continuation direction. "breakout_at" is
    # the actual bar where that re-break happened (not when the pivot was
    # originally confirmed) -- that's the real anchor for Steps 2 and 3.
    step1 = None
    for p in reversed(confirmed_pivots):
        if not p["confirmed"]:
            continue
        later_bars = [b for b in bars if b["time"] > p["confirmed_at"]]
        if p["type"] == "H":
            breakout_bar = next((b for b in later_bars if b["close"] > p["price"]), None)
            if breakout_bar:
                step1 = {**p, "direction": "bullish", "breakout_at": breakout_bar["time"]}
                break
        if p["type"] == "L":
            breakout_bar = next((b for b in later_bars if b["close"] < p["price"]), None)
            if breakout_bar:
                step1 = {**p, "direction": "bearish", "breakout_at": breakout_bar["time"]}
                break

    # Step 2: the opposite-type fractal pivot immediately before Step 1's
    # actual breakout bar -- the last push against the move before it expanded.
    step2 = None
    if step1:
        opp = "L" if step1["direction"] == "bullish" else "H"
        later_opp = [p for p in pivots if p[1] == opp and bars[p[0]]["time"] <= step1["breakout_at"]]
        if later_opp:
            step2 = later_opp[-1]

    # Step 3: the extreme reached after Step 1 in the breakout direction, and
    # whether it has been confirmed (close back through the pivot right
    # before it) -- exactly the same test as everywhere else, applied to
    # whatever comes after Step 1.
    step3 = None
    if step1:
        after = [b for b in bars if b["time"] > step1["breakout_at"]]
        if after:
            if step1["direction"] == "bullish":
                extreme = max(after, key=lambda b: b["high"])
                ext_price, ext_time = extreme["high"], extreme["time"]
                ref_bars = [b for b in bars if b["time"] < ext_time]
                # nearest prior swing low before the extreme
                prior_lows = [p for p in pivots if p[1] == "L" and bars[p[0]]["time"] < ext_time]
                ref_price = prior_lows[-1][2] if prior_lows else step2[2] if step2 else None
            else:
                extreme = min(after, key=lambda b: b["low"])
                ext_price, ext_time = extreme["low"], extreme["time"]
                prior_highs = [p for p in pivots if p[1] == "H" and bars[p[0]]["time"] < ext_time]
                ref_price = prior_highs[-1][2] if prior_highs else step2[2] if step2 else None
            confirmed3 = False
            confirmed3_at = None
            if ref_price is not None:
                for b in bars:
                    if b["time"] <= ext_time:
                        continue
                    if step1["direction"] == "bullish" and b["close"] < ref_price:
                        confirmed3, confirmed3_at = True, b["time"]
                        break
                    if step1["direction"] == "bearish" and b["close"] > ref_price:
                        confirmed3, confirmed3_at = True, b["time"]
                        break
            step3 = {"price": ext_price, "time": ext_time, "ref_price": ref_price,
                     "confirmed": confirmed3, "confirmed_at": confirmed3_at}

    # Step 4: has price re-entered the Step 2 zone (+/- 15pt tolerance)?
    step4_active = False
    if step2:
        step4_active = abs(price - step2[2]) <= 15

    now_et = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4))
    in_preopen_window = (now_et.hour == 9 and now_et.minute >= 0) or (now_et.hour == 8 and now_et.minute >= 45)

    steps = {
        "1": {"label": "HTF Solidified Breakout", "status": "confirmed" if step1 else "none",
              "detail": step1},
        "2": {"label": "Last Opposite Push (OB)", "status": "identified" if step2 else "none",
              "detail": {"time": bars[step2[0]]["time"], "price": step2[2]} if step2 else None},
        "3": {"label": "Target High/Low Solidified", "status": ("confirmed" if step3 and step3["confirmed"] else "pending" if step3 else "none"),
              "detail": step3},
        "4": {"label": "Step 2 Retrace & Shift", "status": "watching" if step4_active else "not_reached",
              "detail": {"price_now": price, "zone": step2[2] if step2 else None}},
        "5": {"label": "1m Micro Displacement Shift", "status": "gated_to_ny_window" if not in_preopen_window else "pending_manual_review",
              "detail": None},
        "6": {"label": "1m Retest Entry & Risk Set", "status": "not_applicable", "detail": None},
    }

    a_plus_plus = (
        steps["1"]["status"] == "confirmed"
        and steps["3"]["status"] == "confirmed"
        and steps["4"]["status"] == "watching"
        and in_preopen_window
    )

    status = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generated_at_et": et_str(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        "symbol": quote.get("symbol", "CME_MINI:MNQ1!"),
        "price": price,
        "quote": quote,
        "steps": steps,
        "solidified_low": last_solidified_low,
        "solidified_high": last_solidified_high,
        "in_ny_preopen_window": in_preopen_window,
        "verdict": "A++ SETUP" if a_plus_plus else "NO TRADE",
        "news": fetch_news(),
    }

    with open(STATUS_PATH, "w") as f:
        json.dump(status, f, indent=2, default=str)

    print(json.dumps({"ok": True, "verdict": status["verdict"], "price": price}))


if __name__ == "__main__":
    main()
