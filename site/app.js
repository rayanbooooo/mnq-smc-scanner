const STEP_LABELS = {
  "1": "HTF Solidified Breakout",
  "2": "Last Opposite Push (OB)",
  "3": "Target High/Low Solidified",
  "4": "Step 2 Retrace & Shift",
  "5": "1m Micro Displacement Shift",
  "6": "1m Retest Entry & Risk Set",
};

const STEP_DESC = {
  "1": "A prior Solidified High/Low on the 1H chart that price has broken back through — this sets the range and direction (long vs short).",
  "2": "The last candle/wick against the move right before the breakout — the order block, where the move likely originated from.",
  "3": "The extreme reached after the breakout. Only counts as a real target once price closes back through the swing point right before it — until then it's unconfirmed, not a fabricated level.",
  "4": "Price needs to pull back into the Step 2 zone. \"Watching\" means it's back in range; the actual shift confirmation happens on the 1-minute chart in Step 5.",
  "5": "Inside the Step 2 zone, the 1-minute chart needs to break its own recent swing point with real displacement. Gated to the 30-min pre-NY-open window — never simulated outside it.",
  "6": "Entry = retest of the 1m order block from Step 5. Stop below/above the 1m Solidified Low/High. Target = the Step 3 level.",
};

const ICONS = {
  confirmed: "✅",
  identified: "✅",
  pending: "⏳",
  watching: "⏳",
  gated_to_ny_window: "⏳",
  not_reached: "❌",
  not_applicable: "❌",
  none: "❌",
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

function stepDetailText(key, step) {
  const d = step.detail;
  if (!d) return "";
  if (key === "1" && d.price) return `${d.direction === "bullish" ? "Broke above" : "Broke below"} ${fmtPrice(d.price)}`;
  if (key === "2" && d.price) return `Push level ${fmtPrice(d.price)}`;
  if (key === "3" && d.price) return `${fmtPrice(d.price)}${d.confirmed ? " — confirmed" : " — unconfirmed"}`;
  if (key === "4" && d.zone) return `Zone ${fmtPrice(d.zone)} · price now ${fmtPrice(d.price_now)}`;
  return "";
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
  document.getElementById("ny-window").textContent = data.in_ny_preopen_window ? "ACTIVE" : "closed";
  document.getElementById("ny-chip").classList.toggle("active", !!data.in_ny_preopen_window);

  const box = document.getElementById("verdict-box");
  const val = document.getElementById("verdict-value");
  const isAplus = data.verdict === "A++ SETUP";
  box.className = "hero " + (isAplus ? "aplus" : "notrade");
  val.className = "verdict-value " + (isAplus ? "aplus" : "notrade");
  val.textContent = data.verdict || "—";

  const stepsEl = document.getElementById("steps");
  stepsEl.innerHTML = "";
  for (const key of ["1", "2", "3", "4", "5", "6"]) {
    const step = data.steps[key];
    if (!step) continue;
    const icon = ICONS[step.status] || "❌";
    const row = document.createElement("div");
    row.className = "step-row";
    row.innerHTML = `
      <div class="step-icon ${step.status}">${icon}</div>
      <div class="step-num">${key}</div>
      <div style="flex:1">
        <div class="step-label">${STEP_LABELS[key]}</div>
        <div class="step-detail">${stepDetailText(key, step)}</div>
        <div class="step-detail-long">${STEP_DESC[key]}</div>
      </div>`;
    stepsEl.appendChild(row);
  }

  const levelsEl = document.getElementById("levels");
  levelsEl.innerHTML = "";
  const levels = [];
  if (data.solidified_high) levels.push(["Solidified High", data.solidified_high.price]);
  if (data.solidified_low) levels.push(["Solidified Low", data.solidified_low.price]);
  if (data.steps["2"] && data.steps["2"].detail) levels.push(["Step 2 Order Block", data.steps["2"].detail.price]);
  if (data.steps["3"] && data.steps["3"].detail) levels.push(["Step 3 Target", data.steps["3"].detail.price]);
  for (const [name, price] of levels) {
    const row = document.createElement("div");
    row.className = "level-row";
    row.innerHTML = `<span class="level-name">${name}</span><span class="level-price">${fmtPrice(price)}</span>`;
    levelsEl.appendChild(row);
  }

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
