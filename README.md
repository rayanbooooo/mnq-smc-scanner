# MNQ Scanner — Session Sweep & Displacement

Rayan's live dashboard for MNQ (Micro E-mini Nasdaq-100 futures), scanning the
8:00 PM / 9:00 PM / 9:30 AM New York session windows against two models:

- **Model 1 — Session Sweep & Displacement**: mark the swing high/low before
  a session open, wait for a liquidity sweep, then require an energetic
  reversal (large-bodied candles leaving a Fair Value Gap) confirmed by a
  candle *body* closing beyond a local structure point (a Market Structure
  Shift). Entry at the shift candle's close if price is still nearby,
  otherwise a limit at the FVG. Stop beyond the sweep extreme, breakeven at
  1:1 RR, target at 1:2 RR.
- **Model 2 — Inversion Fair Value Gap**: simpler alternative. The sweep leg
  itself must leave FVG(s) in its own direction; when price later closes
  through all of them, that inversion is the entry — immediately, no
  explicit structure shift needed.

All entries on the 8PM/9PM evening opens are subject to the hard midnight NY
cutoff; an open 8PM trade blocks a new 9PM entry (overlap constraint).

## How it works

- **`scanner/strategy.py`** — pure detection logic: NY session windows,
  fractal swing/FVG/MSS detection, both models, and a stateless trade-lifecycle
  replay (walks the bar history forward from entry to determine breakeven/
  stop/target — no persisted state file, so it's self-healing on every run).
- **`scanner/scan.py`** — pulls live 5-minute OHLCV + quote from TradingView
  Desktop (via the [tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp)
  `tv` CLI over its local CDP debug port), runs `strategy.evaluate_trading_night()`,
  and writes the result to `site/data/status.json`.
- **`scanner/run_and_push.sh`** — runs a scan, commits `status.json` if it
  changed, and pushes. Invoked every 60s by the `com.mnqscanner` LaunchAgent
  (`~/Library/LaunchAgents/com.mnqscanner.plist`) so it keeps running
  independent of any particular terminal or chat session.
- **`site/`** — static dashboard. Fetches `status.json` **directly from
  GitHub's raw content CDN** (not a same-origin path), so new data shows up
  without a Vercel redeploy. `vercel.json`'s `ignoreCommand` skips a rebuild
  when a push only touches `status.json`, so routine scans don't burn
  deployments — only real code changes do. Refreshes client-side every 10s.

**No automated trade execution.** This produces analysis and a verdict label
only.

## Documented assumptions

The source strategy description leaves some judgment calls; where the code
had to pick an interpretation, it's flagged here (and in `strategy.py`
comments) rather than silently guessed:

- **Swing high/low**: 5-minute fractal pivots (2 bars each side), looked back
  up to ~4h before the session open.
- **"Energetic/large-bodied" displacement**: body ≥ 55% of the candle's range
  AND ≥ 1.5× the pre-session median body size.
- **MSS pivot**: a *local* 1-bar fractal pivot formed after the sweep, not the
  original pre-session opposite extreme — matches the walkthrough examples
  ("closure above structure" referring to a nearby minor point, not the far
  side of the range).
- **Stop buffer**: 5 points beyond the sweep extreme ("just beyond" isn't
  quantified in the source).
- **Model 2 breakeven trigger**: the source says "nearest short-term
  liquidity pool," which isn't mechanically defined here — approximated as
  1:1 RR, same as Model 1.
- **9:30 AM search window**: no stated cutoff for how long a 9:30 AM setup
  stays valid; assumed 90 minutes.
- **9:30 AM under Model 1**: the source's Model 1 steps only ever reference
  8PM/9PM; 9:30 AM is evaluated under Model 2 only, per how Model 2's rules
  explicitly name it.

## Running a scan manually

```bash
python3 scanner/scan.py
```

Requires TradingView Desktop running locally with `--remote-debugging-port=9222`
and the `tradingview-mcp` repo cloned at `~/tradingview-mcp`.
