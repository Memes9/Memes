const NUM_KEYS = ["risk_pct","fixed_lot","max_lot","max_open_positions","max_trades_per_day",
  "max_daily_loss_pct","max_total_drawdown_pct","max_spread_points","signal_max_age_sec",
  "default_sl_points","default_tp_points","break_even_points","trailing_start_points","trailing_step_points",
  // قەبارەی لۆت
  "balance_pct",
  // پاراستنی SL + debounce
  "max_sl_pips","pip_points","debounce_sec",
  // قەرەبووی سپرێد
  "spread_extra_points","spread_cap_points",
  // Tier 1 / Tier 2
  "tier1_trigger_pct","tier1_lock_pct","tier2_trigger_pct","tier2_lock_pct","tier2_close_pct",
  // ژمارەی جادوویی
  "magic_1m","magic_3m","magic_default"];
const BOOL_KEYS = ["trading_enabled","trailing_enabled","allow_reverse","session_filter_enabled","confluence_enabled",
  "laol_passthrough","laol_trade_info_signals",
  "max_sl_enabled","debounce_enabled","spread_comp_enabled","respect_stops_level","progression_enabled"];
const TXT_KEYS = ["session_start_utc","session_end_utc"];
const SEL_KEYS = ["confluence_mode","confluence_sl_policy","confluence_tp_policy","laol_tp_mode","lot_mode"];
NUM_KEYS.push("confluence_window_sec","confluence_min_score");

let dirty = false;
document.addEventListener("input", () => { dirty = true; });

const fmt = (n, d = 2) => (n === null || n === undefined || isNaN(n)) ? "—" : Number(n).toFixed(d);
const t = ts => ts ? new Date(ts * 1000).toLocaleTimeString("en-GB") : "—";
const cls = p => Number(p) >= 0 ? "pos" : "neg";

async function refresh() {
  let s;
  try { s = await (await fetch("/api/state")).json(); }
  catch { return; }

  const conn = document.getElementById("conn");
  conn.textContent = s.connected ? "MT5: پەیوەندی کراوە" : "MT5: پەیوەندی نییە";
  conn.className = "pill " + (s.connected ? "on" : "off");

  const a = s.account || {};
  document.getElementById("balance").textContent = fmt(a.balance);
  document.getElementById("equity").textContent = fmt(a.equity);
  document.getElementById("freeMargin").textContent = fmt(a.free_margin);
  const pnl = document.getElementById("pnlToday");
  pnl.textContent = fmt(s.daily.pnl_today);
  pnl.className = cls(s.daily.pnl_today);
  document.getElementById("tradesToday").textContent = s.daily.trades_today;
  document.getElementById("winRate").textContent = s.stats.win_rate + "%";
  document.getElementById("pf").textContent = s.stats.profit_factor || "—";
  const pos = (a.open_positions || []);
  document.getElementById("openPos").textContent = pos.length;

  if (!dirty) {
    NUM_KEYS.forEach(k => { const e = document.getElementById(k); if (e) e.value = s.settings[k]; });
    BOOL_KEYS.forEach(k => { const e = document.getElementById(k); if (e) e.checked = !!s.settings[k]; });
    TXT_KEYS.forEach(k => { const e = document.getElementById(k); if (e) e.value = s.settings[k]; });
    SEL_KEYS.forEach(k => { const e = document.getElementById(k); if (e) e.value = s.settings[k]; });
  }

  const pt = !!s.settings.laol_passthrough;
  const note = document.getElementById("ptNote");
  if (note) {
    note.innerHTML = pt
      ? '<span style="color:var(--green)">✓ چالاکە — هەموو سیگناڵێک بەبێ فیلتەر دەگوازرێتەوە. SL/TP لە ئیندیکەیتەرەوە دێت. سنووری پۆزیشن و confluence کار ناکەن.</span>'
      : '<span style="color:#e08a24">⚠ ناچالاکە — سنوورەکانی مەترسی و confluence کاردەکەن.</span>';
  }
  document.querySelectorAll("#confluence_enabled,#confluence_mode,#confluence_window_sec,#confluence_min_score")
    .forEach(e => { e.disabled = pt; });

  renderPreviews(s.settings, a.balance);

  renderVotes(s.confluence);

  fill("posTable", pos, p => `<td>${p.ticket ?? "—"}</td><td>${p.symbol ?? ""}</td>
    <td>${p.side ?? p.type ?? ""}</td><td>${fmt(p.volume, 2)}</td>
    <td>${fmt(p.open_price ?? p.price, 2)}</td>
    <td class="${cls(p.profit)}">${fmt(p.profit)}</td>`);

  fill("ordTable", s.orders, o => `<td>${o.id}</td><td>${t(o.ts)}</td><td>${o.action}</td>
    <td>${o.symbol}</td><td>${fmt(o.volume, 2)}</td>
    <td><span class="st st-${o.status}">${o.status}</span></td>
    <td>${o.error || (o.ticket ? "#" + o.ticket : "")}</td>`);

  fill("trdTable", s.trades, x => `<td>${x.ticket}</td><td>${x.symbol}</td><td>${x.side}</td>
    <td>${fmt(x.volume, 2)}</td><td>${fmt(x.open_price, 2)}</td><td>${fmt(x.close_price, 2)}</td>
    <td class="${cls(x.profit)}">${fmt(x.profit)}</td>`);

  fill("sigTable", s.signals, g => `<td>${g.id}</td><td>${t(g.ts)}</td>
    <td>${g.source || ""}</td><td>${g.action || ""}</td><td>${g.symbol || ""}</td><td><span class="st st-${g.status}">${g.status}</span></td>
    <td>${g.reason || ""}</td>`);

  document.getElementById("log").innerHTML = s.events
    .map(e => `<div>[${t(e.ts)}] ${e.level.toUpperCase()} — ${e.message}</div>`).join("");
}

// پێشبینینی زیندوو: ژمارەکان چی دەکەن لە ڕاستیدا
function renderPreviews(st, balance) {
  const lotNote = document.getElementById("lotNote");
  if (lotNote) {
    if (st.lot_mode === "fixed") {
      lotNote.innerHTML = `هەموو مامەڵەکان بە <b>${fmt(st.fixed_lot, 2)}</b> لۆت دەکرێنەوە.`;
    } else {
      const pct = Number(st.balance_pct) || 0;
      const bal = Number(balance) || 0;
      const lot = bal > 0 ? (bal / 100) * 0.01 * pct : 0;
      const ex = [100, 500, 1000, 10000]
        .map(b => `${b}$ → ${((b / 100) * 0.01 * pct).toFixed(2)}`).join("  •  ");
      lotNote.innerHTML = bal > 0
        ? `باڵانسی ئێستا <b>${fmt(bal)}$</b> بە ${pct}% → <b>${lot.toFixed(2)}</b> لۆت<br><span class="dim">${ex}</span>`
        : `${pct}% لە باڵانس:  ${ex}`;
    }
  }

  const tierNote = document.getElementById("tierNote");
  if (tierNote) {
    if (!st.progression_enabled) {
      tierNote.innerHTML = '<span style="color:#e08a24">⚠ ناچالاکە — SL دوای کردنەوە ناجوڵێت.</span>';
    } else {
      const rows = [50, 100, 250].map(tp =>
        `TP ${tp}p → Tier1 لە ${(tp * st.tier1_trigger_pct / 100).toFixed(0)}p (SL +${(tp * st.tier1_lock_pct / 100).toFixed(1)}p)` +
        ` • Tier2 لە ${(tp * st.tier2_trigger_pct / 100).toFixed(0)}p (SL +${(tp * st.tier2_lock_pct / 100).toFixed(1)}p, ` +
        `${st.tier2_close_pct}% دادەخرێت)`
      ).join("<br>");
      tierNote.innerHTML = `<span class="dim">${rows}</span>`;
    }
  }
}

function renderVotes(cf) {
  const box = document.getElementById("voteBoard");
  if (!cf) { box.innerHTML = ""; return; }
  const sources = Object.keys(cf.sources || {});
  if (!cf.enabled) {
    box.innerHTML = `<div class="vote-note">Confluence ناچالاکە — هەر سیگناڵێک بەتەنیا ترەید دەکات.</div>`;
    return;
  }
  if (!sources.length) {
    box.innerHTML = `<div class="vote-note warn-note">⚠ هیچ سەرچاوەیەک پێناسە نەکراوە — <code>confluence_sources</code> ڕێک بخە.</div>`;
    return;
  }
  const cards = sources.map(src => {
    const v = (cf.live_votes || {})[src];
    if (!v) return `<div class="vote idle"><b>${src}</b><span>چاوەڕوان</span></div>`;
    const dir = v.action === "buy" ? "buy" : "sell";
    const label = v.action === "buy" ? "کڕین" : "فرۆشتن";
    return `<div class="vote ${dir}"><b>${src}</b><span>${label} · ${v.age_sec}s</span></div>`;
  }).join("");

  const votes = Object.values(cf.live_votes || {});
  const buys = votes.filter(v => v.action === "buy").length;
  const sells = votes.filter(v => v.action === "sell").length;
  let verdict = "چاوەڕوانی سیگناڵ";
  let vcls = "idle";
  if (cf.mode === "all" && buys === sources.length) { verdict = "✓ هەموویان: کڕین"; vcls = "buy"; }
  else if (cf.mode === "all" && sells === sources.length) { verdict = "✓ هەموویان: فرۆشتن"; vcls = "sell"; }
  else if (buys && sells) { verdict = "✗ ناکۆکی نێوان ئیندیکەیتەرەکان"; vcls = "conflict"; }
  else if (buys || sells) { verdict = `بەشێکی هاوڕان (${buys + sells}/${sources.length})`; vcls = "idle"; }

  box.innerHTML = `<div class="vote-grid">${cards}</div>
    <div class="verdict ${vcls}">${verdict}</div>
    <div class="vote-note">ماوەی هاوڕابوون: ${cf.window_sec} چرکە · شێواز: ${cf.mode}</div>`;
}

function fill(id, rows, render) {
  const tb = document.querySelector(`#${id} tbody`);
  if (!rows || !rows.length) { tb.innerHTML = `<tr><td colspan="7" style="color:#8ea0c0">داتا نییە</td></tr>`; return; }
  tb.innerHTML = rows.map(r => `<tr>${render(r)}</tr>`).join("");
}

document.getElementById("saveBtn").onclick = async () => {
  const patch = {};
  NUM_KEYS.forEach(k => { const e = document.getElementById(k); if (e) patch[k] = parseFloat(e.value) || 0; });
  BOOL_KEYS.forEach(k => { const e = document.getElementById(k); if (e) patch[k] = e.checked; });
  TXT_KEYS.forEach(k => { const e = document.getElementById(k); if (e) patch[k] = e.value; });
  SEL_KEYS.forEach(k => { const e = document.getElementById(k); if (e) patch[k] = e.value; });
  await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) });
  dirty = false;
  const m = document.getElementById("saveMsg");
  m.textContent = "✓ پاشەکەوتکرا";
  setTimeout(() => m.textContent = "", 2500);
  refresh();
};

document.getElementById("killBtn").onclick = async () => {
  if (!confirm("دڵنیایت؟ هەموو پۆزیشنەکان دادەخرێن و ترەیدینگ ڕادەگیرێت.")) return;
  await fetch("/api/panic", { method: "POST" });
  dirty = false; refresh();
};

document.querySelectorAll("[data-act]").forEach(b => b.onclick = async () => {
  const act = b.dataset.act;
  if (act !== "close_all" && !confirm(`ناردنی فەرمانی ${act.toUpperCase()}؟`)) return;
  await fetch("/api/manual-order", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: act,
      symbol: document.getElementById("m_symbol").value,
      volume: document.getElementById("m_volume").value,
      sl: document.getElementById("m_sl").value,
      tp: document.getElementById("m_tp").value
    })
  });
  refresh();
});

refresh();
setInterval(refresh, 3000);
