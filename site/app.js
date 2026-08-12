const STEP_LABELS = {
  "1": "HTF Solidified Breakout",
  "2": "Last Opposite Push (OB)",
  "3": "Target High/Low Solidified",
  "4": "Step 2 Retrace & Shift",
  "5": "1m Micro Displacement Shift",
  "6": "1m Retest Entry & Risk Set",
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

async function refresh() {
  let data;
  try {
    const res = await fetch(`data/status.json?t=${Date.now()}`, { cache: "no-store" });
    data = await res.json();
  } catch (e) {
    document.getElementById("last-updated").textContent = "connection lost";
    return;
  }

  document.getElementById("last-updated").textContent = `updated ${timeAgo(data.generated_at)} · ${data.generated_at_et}`;
  document.getElementById("price").textContent = fmtPrice(data.price);
  document.getElementById("symbol").textContent = (data.symbol || "").replace("CME_MINI:", "");
  document.getElementById("ny-window").textContent = data.in_ny_preopen_window ? "ACTIVE" : "closed";

  const box = document.getElementById("verdict-box");
  const val = document.getElementById("verdict-value");
  const isAplus = data.verdict === "A++ SETUP";
  box.className = "verdict " + (isAplus ? "aplus" : "notrade");
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
setInterval(refresh, 30000);
