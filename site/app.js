const SESSION_LABELS = { "8pm": "8:00 PM Open", "9pm": "9:00 PM Open", "930am": "9:30 AM Open" };

const STATUS_BADGE = {
  waiting_for_open: { text: "UPCOMING", tone: "dim" },
  waiting_for_sweep: { text: "WATCHING RANGE", tone: "amber" },
  expired_no_sweep: { text: "NO SWEEP", tone: "dim" },
  watching_for_reversal: { text: "AWAITING REVERSAL", tone: "amber" },
  expired_no_reversal: { text: "NO REVERSAL", tone: "dim" },
  overlap_skipped: { text: "SKIPPED — OVERLAP", tone: "dim" },
  invalid_trade_geometry: { text: "INVALID SETUP", tone: "dim" },
};

const TRADE_BADGE = {
  pending_entry: { text: "LIMIT PENDING", tone: "amber" },
  open: { text: "TRADE OPEN", tone: "live" },
  breakeven_exit: { text: "CLOSED @ BREAKEVEN", tone: "dim" },
  stopped_out: { text: "STOPPED OUT", tone: "red" },
  target_hit: { text: "TARGET HIT", tone: "green" },
  overlap_skipped: { text: "SKIPPED — OVERLAP", tone: "dim" },
};

function timeAgo(iso) {
  const then = new Date(iso).getTime();
  const secs = Math.floor((Date.now() - then) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m ago`;
}

function fmtPrice(p) {
  if (p === null || p === undefined) return "—";
  return p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const nyTimeFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
function fmtNyTime(unixSeconds) {
  if (unixSeconds === null || unixSeconds === undefined) return "—";
  return nyTimeFmt.format(new Date(unixSeconds * 1000));
}

function badgeHtml(badge) {
  return `<span class="badge badge-${badge.tone}">${badge.text}</span>`;
}

function watchingHtml(session) {
  if (session.status === "waiting_for_sweep" && session.swing_high && session.swing_low) {
    return `<div class="watch-box">
      <div class="watch-title">Looking for</div>
      <div class="watch-line">A sweep above <b>${fmtPrice(session.swing_high.price)}</b> or below <b>${fmtPrice(session.swing_low.price)}</b> to open this session's setup.</div>
    </div>`;
  }
  if (!session.watching) return "";
  const dir = session.sweep.direction === "up" ? "bearish (short)" : "bullish (long)";
  const lines = [];
  const m1 = session.watching.model1, m2 = session.watching.model2;

  if (m1 && !m1.confirmed) {
    if (!m1.fvgs.length) {
      lines.push(`<b>Model 1:</b> no displacement Fair Value Gap yet in the ${dir} reversal — needs a large-bodied candle to leave one.`);
    } else if (!m1.mss) {
      const fvg = m1.fvgs[0];
      lines.push(`<b>Model 1:</b> FVG formed at ${fmtPrice(fvg.bottom)}–${fmtPrice(fvg.top)} — watching for a candle <i>body</i> close beyond the post-sweep pivot to confirm the structure shift.`);
    }
  }
  if (m2 && !m2.confirmed) {
    if (!m2.fvgs.length) {
      lines.push(`<b>Model 2:</b> the sweep leg left no Fair Value Gap — no inversion setup available this session.`);
    } else {
      const verb = m2.direction === "up" ? "above" : "below";
      lines.push(`<b>Model 2:</b> watching for a candle to <i>close</i> ${verb} <b>${fmtPrice(m2.inversion_boundary)}</b> to confirm the inversion.`);
    }
  }
  if (!lines.length) return "";
  return `<div class="watch-box"><div class="watch-title">Looking for</div>${lines.map(l => `<div class="watch-line">${l}</div>`).join("")}</div>`;
}

function renderSession(key, session) {
  const label = SESSION_LABELS[key];
  const badge = session.trade ? (TRADE_BADGE[session.trade.status] || STATUS_BADGE[session.status]) : STATUS_BADGE[session.status];

  const rows = [];
  if (session.swing_high) rows.push(["Pre-session high", fmtPrice(session.swing_high.price), fmtNyTime(session.swing_high.time)]);
  if (session.swing_low) rows.push(["Pre-session low", fmtPrice(session.swing_low.price), fmtNyTime(session.swing_low.time)]);
  if (session.sweep) {
    rows.push([`Sweep (${session.sweep.direction === "up" ? "above high" : "below low"})`, fmtPrice(session.sweep.extreme), fmtNyTime(session.sweep.time)]);
  }
  if (session.signal) {
    const s = session.signal;
    const fvg = s.fvgs && s.fvgs[0];
    rows.push([`Model ${s.model} signal`, fmtPrice(s.signal_price), fmtNyTime(s.signal_time)]);
    if (fvg) rows.push(["FVG zone", `${fmtPrice(fvg.bottom)} – ${fmtPrice(fvg.top)}`, ""]);
  }

  let tradeHtml = "";
  if (session.trade) {
    const t = session.trade;
    const dirClass = t.direction === "long" ? "long" : "short";
    tradeHtml = `
      <div class="trade-box ${dirClass}">
        <div class="trade-head">
          <span class="trade-dir">${t.direction.toUpperCase()}</span>
          <span class="trade-model">Model ${t.model} · ${t.entry_type === "market_close" ? "market" : "limit"}</span>
        </div>
        <div class="trade-levels">
          <div><span>Entry</span><b>${fmtPrice(t.entry)}</b></div>
          <div><span>Stop</span><b>${fmtPrice(t.stop)}</b></div>
          <div><span>Target</span><b>${fmtPrice(t.target)}</b></div>
          <div><span>BE trigger</span><b>${fmtPrice(t.breakeven_trigger)}</b></div>
        </div>
        ${t.be_moved ? '<div class="trade-note">Stop moved to breakeven</div>' : ""}
        ${t.exit_price !== null ? `<div class="trade-note">Closed at ${fmtPrice(t.exit_price)} · ${fmtNyTime(t.exit_time)}</div>` : ""}
      </div>`;
  }

  const rowsHtml = rows.map(([name, value, time]) => `
    <div class="sess-row">
      <span class="sess-name">${name}</span>
      <span class="sess-value">${value}${time ? ` <span class="sess-time">${time}</span>` : ""}</span>
    </div>`).join("");

  return `
    <div class="session-card">
      <div class="session-head">
        <div>
          <div class="session-label">${label}</div>
          <div class="session-open">opens ${fmtNyTime(session.open_time)} ET</div>
        </div>
        ${badgeHtml(badge)}
      </div>
      ${rowsHtml}
      ${session.trade ? tradeHtml : watchingHtml(session)}
    </div>`;
}

const STATUS_URL = "https://raw.githubusercontent.com/rayanbooooo/mnq-smc-scanner/main/site/data/status.json";
let lastPrice = null;

async function refresh() {
  let data;
  try {
    const res = await fetch(`${STATUS_URL}?t=${Date.now()}`, { cache: "no-store" });
    data = await res.json();
    document.querySelector(".live-badge").classList.remove("offline");
  } catch (e) {
    document.getElementById("last-updated").textContent = "connection lost";
    document.querySelector(".live-badge").classList.add("offline");
    return;
  }

  document.getElementById("last-updated").textContent = `updated ${timeAgo(data.generated_at)} · ${data.generated_at_et}`;

  const priceEl = document.getElementById("price");
  priceEl.textContent = fmtPrice(data.price);
  if (lastPrice !== null && data.price !== lastPrice) {
    priceEl.classList.remove("flash-up", "flash-down");
    void priceEl.offsetWidth;
    priceEl.classList.add(data.price > lastPrice ? "flash-up" : "flash-down");
  }
  lastPrice = data.price;

  document.getElementById("symbol").textContent = (data.symbol || "").replace("CME_MINI:", "");
  document.getElementById("trading-day").textContent = data.trading_day || "—";

  const box = document.getElementById("verdict-box");
  const val = document.getElementById("verdict-value");
  const detail = document.getElementById("verdict-detail");
  const verdict = data.verdict || { headline: "—", detail: "", tone: "none" };
  box.className = "hero " + verdict.tone;
  val.className = "verdict-value " + verdict.tone;
  val.textContent = verdict.headline;
  detail.textContent = verdict.detail || "";

  const sessionsEl = document.getElementById("sessions");
  sessionsEl.innerHTML = ["8pm", "9pm", "930am"].map(key => renderSession(key, data.sessions[key])).join("");

  const newsEl = document.getElementById("news");
  newsEl.innerHTML = "";
  if (data.news && data.news.length) {
    for (const headline of data.news) {
      const item = document.createElement("div");
      item.className = "news-item";
      item.textContent = headline;
      newsEl.appendChild(item);
    }
  } else {
    newsEl.innerHTML = `<div class="news-empty">No headline captured this scan</div>`;
  }
}

refresh();
setInterval(refresh, 10000);
