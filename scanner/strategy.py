"""
Session Sweep & Displacement (Model 1) + Inversion FVG (Model 2) detection.

Pure functions over 5-minute OHLCV bars -- no I/O, no TradingView calls. scan.py
fetches bars and calls evaluate_trading_night() to get the full picture.

This is a best-effort mechanical read of an inherently discretionary strategy.
Where the source rules leave a judgment call, the choice made and why is noted
inline -- treat those as documented assumptions to correct, not hidden guesses.

NY session windows, one "trading night" = evening opens (8pm/9pm) + the
following morning's 9:30am open, all gated by the hard midnight cutoff on the
evening opens only (9:30am has no such cutoff -- it IS the morning).
"""
import datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

FRACTAL_N = 2          # bars each side for a "confirmed" pre-session swing
MSS_FRACTAL_N = 1       # bars each side for the local post-sweep pivot (quick/local by design)
LOOKBACK_BARS = 48       # 5m bars (~4h) scanned for the pre-session swing high/low
DISPLACEMENT_BODY_PCT = 0.55   # candle body must be >= this fraction of its range
DISPLACEMENT_BODY_MULT = 1.5   # ...and >= this multiple of the pre-session median body
ENTRY_CLOSE_TOLERANCE = 15     # points: how far price can drift from the MSS close and still get a "market" entry
STOP_BUFFER = 5                # points beyond the sweep extreme for the stop
RR_BREAKEVEN = 1.0
RR_TARGET = 2.0
SESSION_930_SEARCH_MINUTES = 90   # no stated cutoff for 9:30am setups; documented assumption


def to_ny(unix_time):
    return datetime.datetime.fromtimestamp(unix_time, datetime.timezone.utc).astimezone(NY)


def session_windows(now_unix):
    """Return this trading night's key times as unix timestamps.

    'Trading night' = the 8pm/9pm evening opens plus the 9:30am open that
    follows them, mirroring how futures sessions actually roll (the evening
    session belongs to the *next* calendar day's session, not the one whose
    date it falls on).
    """
    now = to_ny(now_unix)
    if now.time() >= datetime.time(18, 0):
        evening_date = now.date()
    elif now.time() < datetime.time(9, 30):
        evening_date = now.date() - datetime.timedelta(days=1)
    else:
        evening_date = now.date()  # daytime dead zone -> points at tonight
    morning_date = evening_date + datetime.timedelta(days=1)

    def mk(d, h, m):
        return int(datetime.datetime(d.year, d.month, d.day, h, m, tzinfo=NY).timestamp())

    return {
        "trading_day": morning_date.isoformat(),
        "8pm": mk(evening_date, 20, 0),
        "9pm": mk(evening_date, 21, 0),
        "midnight": mk(morning_date, 0, 0),
        "930am": mk(morning_date, 9, 30),
    }


def fractal_swings(bars, n):
    """All confirmed fractal pivots (n bars each side). Returns (highs, lows), each
    a list of {time, price} ordered by time."""
    highs, lows = [], []
    for i in range(n, len(bars) - n):
        window = bars[i - n:i + n + 1]
        if bars[i]["high"] == max(b["high"] for b in window):
            highs.append({"time": bars[i]["time"], "price": bars[i]["high"]})
        if bars[i]["low"] == min(b["low"] for b in window):
            lows.append({"time": bars[i]["time"], "price": bars[i]["low"]})
    return highs, lows


def last_swing_before(bars, before_time, n=FRACTAL_N, lookback=LOOKBACK_BARS):
    pre = [b for b in bars if b["time"] < before_time][-lookback:]
    highs, lows = fractal_swings(pre, n)
    return (highs[-1] if highs else None), (lows[-1] if lows else None)


def find_fvgs(bars, direction):
    """3-candle Fair Value Gaps in `bars` (chronological). direction: 'up' or 'down'.
    'up' = bullish gap (bars[i+1].low > bars[i-1].high), 'down' = bearish gap.

    'time' is the displacement (middle) candle; 'confirmed_at' is when the gap
    actually becomes verifiable (the third candle's close) -- use
    confirmed_at, not time, for anything checking "was this known by then"."""
    gaps = []
    for i in range(1, len(bars) - 1):
        left, right = bars[i - 1], bars[i + 1]
        if direction == "up" and right["low"] > left["high"]:
            gaps.append({"top": right["low"], "bottom": left["high"], "time": bars[i]["time"],
                         "confirmed_at": right["time"]})
        elif direction == "down" and right["high"] < left["low"]:
            gaps.append({"top": left["low"], "bottom": right["high"], "time": bars[i]["time"],
                         "confirmed_at": right["time"]})
    return gaps


def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def is_displacement(bar, ref_body_median):
    rng = bar["high"] - bar["low"]
    body = abs(bar["close"] - bar["open"])
    if rng <= 0:
        return False
    return (body / rng) >= DISPLACEMENT_BODY_PCT and body >= DISPLACEMENT_BODY_MULT * max(ref_body_median, 1e-9)


def find_sweep(bars, open_time, search_end, swing_high, swing_low):
    """First bar (open_time <= t < search_end) that trades beyond swing_high or
    swing_low. If a single bar clears both, the side it closed nearer to wins
    (ambiguous otherwise -- documented simplification)."""
    for b in bars:
        if b["time"] < open_time or b["time"] >= search_end:
            continue
        swept_high = swing_high and b["high"] > swing_high["price"]
        swept_low = swing_low and b["low"] < swing_low["price"]
        if swept_high and swept_low:
            direction = "up" if abs(b["close"] - swing_high["price"]) < abs(b["close"] - swing_low["price"]) else "down"
        elif swept_high:
            direction = "up"
        elif swept_low:
            direction = "down"
        else:
            continue
        level = swing_high if direction == "up" else swing_low
        extreme = b["high"] if direction == "up" else b["low"]
        return {"direction": direction, "time": b["time"], "extreme": extreme, "swept_level": level["price"]}
    return None


def find_mss(bars, reversal_dir, n=MSS_FRACTAL_N):
    """Local pivot in the reversal leg, then the first bar whose BODY closes
    beyond it in reversal_dir. bars must start at (or after) the sweep bar."""
    pivot_type = "L" if reversal_dir == "up" else "H"
    for i in range(n, len(bars) - n):
        window = bars[i - n:i + n + 1]
        is_pivot = (
            bars[i]["low"] == min(b["low"] for b in window) if pivot_type == "L"
            else bars[i]["high"] == max(b["high"] for b in window)
        )
        if not is_pivot:
            continue
        pivot_price = bars[i]["low"] if pivot_type == "L" else bars[i]["high"]
        for b in bars[i + n + 1:]:
            if reversal_dir == "up" and b["close"] > pivot_price:
                return {"pivot_time": bars[i]["time"], "pivot_price": pivot_price,
                        "confirmed_at": b["time"], "confirmed_price": b["close"]}
            if reversal_dir == "down" and b["close"] < pivot_price:
                return {"pivot_time": bars[i]["time"], "pivot_price": pivot_price,
                        "confirmed_at": b["time"], "confirmed_price": b["close"]}
    return None


def evaluate_model1(bars, sweep, pre_bars, search_end):
    """Sweep & Displacement: reversal leg needs a qualifying displacement FVG
    AND an MSS body-close, both before search_end."""
    reversal_dir = "down" if sweep["direction"] == "up" else "up"
    reversal_bars = [b for b in bars if b["time"] >= sweep["time"] and b["time"] < search_end]
    if len(reversal_bars) < 3:
        return None

    ref_body_median = median([abs(b["close"] - b["open"]) for b in pre_bars]) if pre_bars else 0
    raw_fvgs = find_fvgs(reversal_bars, reversal_dir)
    disp_fvgs = [g for g in raw_fvgs if any(
        is_displacement(b, ref_body_median) for b in reversal_bars if b["time"] == g["time"]
    )]
    if not disp_fvgs:
        return None

    mss = find_mss(reversal_bars, reversal_dir)
    if not mss:
        return None

    # Only FVGs that existed by the moment MSS confirmed are eligible as an
    # entry reference -- otherwise re-scanning later (with more bars in the
    # window) could silently pick a different, later-formed FVG.
    fvgs_at_signal = [g for g in disp_fvgs if g["confirmed_at"] <= mss["confirmed_at"]] or disp_fvgs

    return {"model": "1", "direction": reversal_dir, "fvgs": fvgs_at_signal, "mss": mss,
            "signal_time": mss["confirmed_at"], "signal_price": mss["confirmed_price"]}


def evaluate_model2(bars, sweep, open_time, search_end):
    """Inversion FVG: the sweep leg itself must leave FVG(s) in the sweep
    direction; price must later close beyond ALL of them (the deepest/highest
    boundary) to confirm the inversion."""
    sweep_leg = [b for b in bars if b["time"] >= open_time and b["time"] <= sweep["time"]]
    leg_fvgs = find_fvgs(sweep_leg, sweep["direction"])
    if not leg_fvgs:
        return None

    reversal_dir = "down" if sweep["direction"] == "up" else "up"
    boundary = min(g["bottom"] for g in leg_fvgs) if sweep["direction"] == "up" else max(g["top"] for g in leg_fvgs)

    after = [b for b in bars if b["time"] > sweep["time"] and b["time"] < search_end]
    for b in after:
        if reversal_dir == "up" and b["close"] > boundary:
            return {"model": "2", "direction": reversal_dir, "fvgs": leg_fvgs, "inversion_boundary": boundary,
                    "signal_time": b["time"], "signal_price": b["close"]}
        if reversal_dir == "down" and b["close"] < boundary:
            return {"model": "2", "direction": reversal_dir, "fvgs": leg_fvgs, "inversion_boundary": boundary,
                    "signal_time": b["time"], "signal_price": b["close"]}
    return None


def build_trade(signal, sweep):
    """Entry price/type is decided once, purely from the signal itself, so it
    never drifts on later re-scans of the same session."""
    direction = signal["direction"]  # 'up' = long, 'down' = short
    stop = (sweep["extreme"] - STOP_BUFFER) if direction == "up" else (sweep["extreme"] + STOP_BUFFER)

    if signal["model"] == "1":
        # "If price remains close to the shift point upon candle closure" --
        # read as: how far the MSS candle's own close ran past the pivot it broke.
        mss_price = signal["mss"]["confirmed_price"]
        pivot_price = signal["mss"]["pivot_price"]
        if abs(mss_price - pivot_price) <= ENTRY_CLOSE_TOLERANCE:
            entry, entry_type = mss_price, "market_close"
        else:
            nearest_fvg = min(signal["fvgs"], key=lambda g: abs(mss_price - (g["top"] + g["bottom"]) / 2))
            entry = nearest_fvg["top"] if direction == "down" else nearest_fvg["bottom"]
            entry_type = "limit_fvg"
    else:
        entry, entry_type = signal["signal_price"], "market_close"

    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + RR_TARGET * risk if direction == "up" else entry - RR_TARGET * risk
    be_price = entry + RR_BREAKEVEN * risk if direction == "up" else entry - RR_BREAKEVEN * risk

    return {
        "model": signal["model"], "direction": "long" if direction == "up" else "short",
        "entry": entry, "entry_type": entry_type, "entry_signal_time": signal["signal_time"],
        "stop": stop, "breakeven_trigger": be_price, "target": target, "risk_points": risk,
    }


def replay_lifecycle(trade, bars, now_unix):
    """Walk bars forward from the entry signal to determine status: pending
    (limit not filled yet), open, breakeven-armed, stopped_out, target_hit."""
    is_long = trade["direction"] == "long"
    after = [b for b in bars if b["time"] >= trade["entry_signal_time"]]

    filled_at = None
    if trade["entry_type"] == "market_close":
        filled_at = trade["entry_signal_time"]
    else:
        for b in after:
            if (is_long and b["low"] <= trade["entry"]) or (not is_long and b["high"] >= trade["entry"]):
                filled_at = b["time"]
                break
        if filled_at is None:
            return {**trade, "status": "pending_entry", "be_moved": False, "exit_price": None, "exit_time": None}

    monitor = [b for b in bars if b["time"] >= filled_at]
    be_moved = False
    effective_stop = trade["stop"]
    for b in monitor:
        if not be_moved and (
            (is_long and b["high"] >= trade["breakeven_trigger"]) or
            (not is_long and b["low"] <= trade["breakeven_trigger"])
        ):
            be_moved = True
            effective_stop = trade["entry"]

        stopped = (is_long and b["low"] <= effective_stop) or (not is_long and b["high"] >= effective_stop)
        hit_target = (is_long and b["high"] >= trade["target"]) or (not is_long and b["low"] <= trade["target"])
        if stopped and hit_target:
            # same bar hit both -- assume the nearer-to-open outcome triggered first
            stopped = abs(b["open"] - effective_stop) <= abs(b["open"] - trade["target"])
            hit_target = not stopped
        if stopped:
            status = "breakeven_exit" if effective_stop == trade["entry"] else "stopped_out"
            return {**trade, "status": status, "be_moved": be_moved, "exit_price": effective_stop, "exit_time": b["time"]}
        if hit_target:
            return {**trade, "status": "target_hit", "be_moved": be_moved, "exit_price": trade["target"], "exit_time": b["time"]}

    return {**trade, "status": "open", "be_moved": be_moved, "exit_price": None, "exit_time": None}


def evaluate_session(bars, open_time, search_end, now_unix):
    """Full pipeline for one session window: swing -> sweep -> Model 1/2 -> trade."""
    swing_high, swing_low = last_swing_before(bars, open_time)
    result = {
        "open_time": open_time, "search_end": search_end,
        "swing_high": swing_high, "swing_low": swing_low,
        "sweep": None, "signal": None, "trade": None, "status": "waiting_for_open",
    }
    if now_unix < open_time:
        return result

    sweep = find_sweep(bars, open_time, min(search_end, now_unix), swing_high, swing_low)
    if not sweep:
        result["status"] = "expired_no_sweep" if now_unix >= search_end else "waiting_for_sweep"
        return result
    result["sweep"] = sweep

    pre_bars = [b for b in bars if b["time"] < open_time][-LOOKBACK_BARS:]
    sig1 = evaluate_model1(bars, sweep, pre_bars, min(search_end, now_unix))
    sig2 = evaluate_model2(bars, sweep, open_time, min(search_end, now_unix))
    signal = min([s for s in (sig1, sig2) if s], key=lambda s: s["signal_time"], default=None)

    if not signal:
        result["status"] = "expired_no_reversal" if now_unix >= search_end else "watching_for_reversal"
        return result
    result["signal"] = signal

    trade = build_trade(signal, sweep)
    if not trade:
        result["status"] = "invalid_trade_geometry"
        return result
    result["trade"] = replay_lifecycle(trade, bars, now_unix)
    result["status"] = "trade"
    return result


def evaluate_trading_night(bars, now_unix):
    """Evaluate 8pm, 9pm and 9:30am sessions, applying the midnight cutoff to
    the evening opens and the 9pm-overlap constraint."""
    win = session_windows(now_unix)

    sessions = {}
    sessions["8pm"] = evaluate_session(bars, win["8pm"], win["midnight"], now_unix)

    # 9pm only takes a NEW trade if no 8pm trade is open/pending at 9pm's own
    # prospective entry -- but its swing/sweep detection always runs so the
    # dashboard can still show what's happening at that level.
    sessions["9pm"] = evaluate_session(bars, win["9pm"], win["midnight"], now_unix)
    eight_pm_trade = sessions["8pm"]["trade"]
    if sessions["9pm"]["trade"] and eight_pm_trade:
        nine_pm_signal_time = sessions["9pm"]["trade"]["entry_signal_time"]
        was_open = (
            eight_pm_trade["status"] in ("open",) or
            (eight_pm_trade.get("exit_time") and eight_pm_trade["exit_time"] > nine_pm_signal_time)
        )
        if was_open:
            sessions["9pm"] = {**sessions["9pm"], "status": "overlap_skipped",
                                "trade": {**sessions["9pm"]["trade"], "status": "overlap_skipped"}}

    search_end_930 = win["930am"] + SESSION_930_SEARCH_MINUTES * 60
    sessions["930am"] = evaluate_session(bars, win["930am"], search_end_930, now_unix)

    return {"trading_day": win["trading_day"], "windows": win, "sessions": sessions}
