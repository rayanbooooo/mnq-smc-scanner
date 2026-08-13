#!/usr/bin/env python3
"""
MNQ Session Sweep & Displacement / Inversion FVG scanner.

Pulls live 5-minute MNQ bars from TradingView Desktop (via the tv CLI, over
its local CDP debug port) and evaluates the 8pm / 9pm / 9:30am NY session
windows against Model 1 (Session Sweep & Displacement) and Model 2 (Inversion
FVG). See scanner/strategy.py for the detection logic and its documented
assumptions. Writes a status snapshot to site/data/status.json.
"""
import json
import shutil
import subprocess
import sys
import datetime
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy

NODE_BIN = shutil.which("node") or "/usr/local/bin/node"
CLI_PATH = os.path.expanduser("~/tradingview-mcp/src/cli/index.js")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_PATH = os.path.join(REPO_ROOT, "site", "data", "status.json")

BAR_COUNT = 250  # 5m bars: enough to cover pre-8pm lookback through now, even late in the 930am window


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
    return strategy.to_ny(unix_time).strftime("%Y-%m-%d %H:%M ET")


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


ACTIVE_STATUSES = ("open", "pending_entry")
SESSION_LABELS = {"8pm": "8:00 PM Open", "9pm": "9:00 PM Open", "930am": "9:30 AM Open"}


def compute_verdict(sessions):
    for key in ("8pm", "9pm", "930am"):
        trade = sessions[key].get("trade")
        if trade and trade["status"] in ACTIVE_STATUSES:
            state = "OPEN" if trade["status"] == "open" else "PENDING"
            return {"headline": f"{trade['direction'].upper()} {state}",
                    "detail": f"{SESSION_LABELS[key]} · Model {trade['model']}", "tone": trade["direction"]}
    for key in ("8pm", "9pm", "930am"):
        if sessions[key]["status"] == "watching_for_reversal":
            return {"headline": "WATCHING", "detail": f"{SESSION_LABELS[key]} swept, awaiting reversal", "tone": "watching"}
    for key in ("8pm", "9pm", "930am"):
        if sessions[key]["status"] == "waiting_for_sweep":
            return {"headline": "WATCHING", "detail": f"{SESSION_LABELS[key]} pre-session range", "tone": "watching"}
    return {"headline": "NO ACTIVE SETUP", "detail": "No session currently in play", "tone": "none"}


def main():
    tv("symbol", "MNQ1!")
    tv("timeframe", "5")
    ohlcv = tv("ohlcv", "-n", str(BAR_COUNT))
    bars = ohlcv["bars"]
    quote = tv("quote")
    price = quote["last"]

    now_unix = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    night = strategy.evaluate_trading_night(bars, now_unix)

    status = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generated_at_et": et_str(now_unix),
        "symbol": quote.get("symbol", "CME_MINI:MNQ1!"),
        "price": price,
        "quote": quote,
        "trading_day": night["trading_day"],
        "windows": night["windows"],
        "sessions": night["sessions"],
        "verdict": compute_verdict(night["sessions"]),
        "news": fetch_news(),
    }

    with open(STATUS_PATH, "w") as f:
        json.dump(status, f, indent=2, default=str)

    print(json.dumps({"ok": True, "verdict": status["verdict"]["headline"], "price": price}))


if __name__ == "__main__":
    main()
