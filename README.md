# MNQ SMC Scanner

Live dashboard applying the Azarel Cobos 6-Step Checklist strategy to Micro E-mini Nasdaq-100 futures (MNQ1!), scanning every 5 minutes via a local TradingView Desktop connection.

## How it works

- `scanner/scan.py` — pulls live 1H OHLCV + quote from TradingView Desktop (via the [tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp) `tv` CLI, which talks to the app over its local Chrome DevTools Protocol debug port), detects fractal swing pivots, and confirms Solidified Highs/Lows using the strategy's own rule: a pivot is only "solidified" once price closes back through the opposite pivot that preceded it. Writes the result to `site/data/status.json`.
- `site/` — static dashboard that reads `data/status.json` and displays the current step-by-step checklist status, key levels, and the latest TradingView news headline. Refreshes client-side every 30s.

Steps 1–3 (macro structure: breakout, last opposite push, target) are fully mechanical. Steps 4–6 (the retest zone, 1-minute micro shift, and execution) require judgment the script does not attempt to fully replace — it reports whether price has re-entered the Step 2 zone and gates Step 5 to the pre-NY-open window, but does not fabricate a clean 1-minute shift or place trades.

**No automated trade execution.** This produces analysis and a verdict label only.

## Running a scan manually

```bash
python3 scanner/scan.py
```

Requires TradingView Desktop running locally with `--remote-debugging-port=9222` and the `tradingview-mcp` repo cloned at `~/tradingview-mcp`.
