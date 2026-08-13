"""
GoldBridge — پردی نێوان TradingView و MetaTrader 5 (بەبێ خزمەتگوزاری کرێدار).

پێکهاتە:
  TradingView alert (webhook)  ->  /webhook/tradingview
        -> risk engine -> orders queue (SQLite)
        -> MT5 Expert Advisor بە WebRequest ی /api/orders/next وەریدەگرێت
        -> EA جێبەجێی دەکات و /api/orders/report دەنێرێتەوە
        -> داشبۆردی وێب: بەڕێوەبردنی هەژمار، مەترسی، مێژووی ترەید، kill switch
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import confluence, db, laol_adapter, risk
from .models import AccountReport, ExecReport, TVSignal

load_dotenv()

TV_SECRET = os.getenv("TV_WEBHOOK_SECRET", "change-me-tradingview-secret")
EA_TOKEN = os.getenv("EA_TOKEN", "change-me-ea-token")
ALLOWED_SYMBOLS = [s.strip() for s in os.getenv("ALLOWED_SYMBOLS", "").split(",") if s.strip()]
#: فەرمانی نەبردراو دوای ئەم ماوەیە بەدەر دەچێت (چرکە).
#: لە مۆدی passthrough دا بەرزە تا هیچ سیگناڵێک بێدەنگ نەفەوتێت.
ORDER_TTL_SEC = int(os.getenv("ORDER_TTL_SEC", "900"))

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "web"

app = FastAPI(title="GoldBridge", version="1.0.0")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    confluence.init()
    db.log_event("info", "GoldBridge server started")


# --------------------------------------------------------------------------
# 1) TradingView -> server
# --------------------------------------------------------------------------
@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    raw = (await request.body()).decode("utf-8", "ignore")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        db.execute(
            "INSERT INTO signals(ts, source, raw, status, reason) VALUES (?,?,?,?,?)",
            (time.time(), "tradingview", raw, "rejected", "JSON نادروست"),
        )
        raise HTTPException(400, "پەیامەکە JSON ی دروست نییە")

    try:
        signal = TVSignal(**payload)
    except Exception as exc:  # pydantic validation
        db.execute(
            "INSERT INTO signals(ts, source, raw, status, reason) VALUES (?,?,?,?,?)",
            (time.time(), "tradingview", raw, "rejected", str(exc)[:300]),
        )
        raise HTTPException(422, f"پەیامی ناتەواو: {exc}")

    if signal.secret != TV_SECRET:
        db.execute(
            "INSERT INTO signals(ts, source, raw, status, reason) VALUES (?,?,?,?,?)",
            (time.time(), "tradingview", raw, "rejected", "نهێنی هەڵە"),
        )
        raise HTTPException(401, "نهێنی هەڵەیە")

    sig_id = db.execute(
        "INSERT INTO signals(ts, source, raw, symbol, action, status) VALUES (?,?,?,?,?,?)",
        (time.time(), signal.strategy or "tradingview", raw, signal.symbol, signal.action, "received"),
    )
    return _process_signal(signal, sig_id)


def _process_signal(signal: TVSignal, sig_id: int):
    """پایپلاینی هاوبەش: مەترسی → هاوڕابوون → دروستکردنی فەرمان."""
    _settings = db.get_settings()
    ok, reason = risk.check(signal, ALLOWED_SYMBOLS)
    if not ok:
        db.execute("UPDATE signals SET status='rejected', reason=? WHERE id=?", (reason, sig_id))
        db.log_event("warn", f"سیگناڵ ڕەتکرایەوە: {reason}")
        return JSONResponse({"accepted": False, "reason": reason}, status_code=200)

    # --- confluence: چاوەڕوانی هاوڕابوونی ئیندیکەیتەرەکان ---
    if signal.action in ("buy", "sell"):
        agreed, cf_reason, cf_info = confluence.evaluate(signal)
        if not agreed:
            db.execute(
                "UPDATE signals SET status='waiting', reason=? WHERE id=?",
                (f"confluence: {cf_reason}", sig_id),
            )
            db.log_event("info", f"سیگناڵ لە چاوەڕوانیدا ({signal.strategy}): {cf_reason}")
            return JSONResponse(
                {"accepted": False, "waiting": True, "reason": cf_reason, "confluence": cf_info},
                status_code=200,
            )
        signal.sl, signal.tp = confluence.merge_levels(signal, cf_info)
        if cf_info:
            db.log_event(
                "info",
                f"✓ هاوڕابوون {signal.action.upper()} — {', '.join(cf_info.get('agreeing', []))}",
            )

    client_id = signal.signal_id or f"{signal.strategy}-{sig_id}-{uuid.uuid4().hex[:8]}"
    # idempotency: هەمان signal_id دوو جار ترەید ناکات
    dup = db.query("SELECT id FROM orders WHERE client_id=?", (client_id,))
    if dup:
        db.execute("UPDATE signals SET status='rejected', reason='دووبارە' WHERE id=?", (sig_id,))
        return {"accepted": False, "reason": "ئەم سیگناڵە پێشتر جێبەجێکراوە", "order_id": dup[0]["id"]}

    # ── یاسای ٣: ١ سیگناڵ = ١ ئۆردەر ─────────────────────────────────
    # ئەگەر TradingView هەمان ئەلێرت چەند جار بنێرێت بەبێ ئەوەی id بگۆڕێت
    # (بۆ نموونە لەبەر دووبارە هەوڵدانەوە)، تەنها یەکەمیان جێبەجێ دەبێت.
    # پشکنین: هەمان لەیئاوت + هەمان ئاراستە + هەمان سیمبول لە ماوەیەکی کورتدا.
    debounce = float(_settings.get("debounce_sec", 0) or 0)
    if debounce > 0 and signal.action in ("buy", "sell"):
        recent = db.query(
            """SELECT id, client_id, ts FROM orders
               WHERE symbol=? AND action=? AND magic=? AND ts >= ?
               ORDER BY id DESC LIMIT 1""",
            (signal.symbol, signal.action, signal.magic, time.time() - debounce),
        )
        if recent:
            db.execute(
                "UPDATE signals SET status='rejected', reason='debounce' WHERE id=?", (sig_id,)
            )
            db.log_event(
                "warn",
                f"⏱ debounce: {signal.action} {signal.symbol} tf{signal.tf} "
                f"— #{recent[0]['id']} پێش {debounce}چ دروستکرا",
            )
            return {
                "accepted": False,
                "reason": f"١ سیگناڵ = ١ ئۆردەر — ئۆردەرێک لە {debounce} چرکەی ڕابردوودا دروستکراوە",
                "order_id": recent[0]["id"],
            }

    volume, risk_pct = risk.sizing(signal)
    order_id = db.execute(
        """INSERT INTO orders(ts, signal_id, client_id, symbol, action, order_type, volume,
                              price, sl, tp, risk_pct, magic, tf, status, updated_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)""",
        (time.time(), sig_id, client_id, signal.symbol, signal.action, signal.order_type,
         volume, signal.price, signal.sl, signal.tp, risk_pct,
         signal.magic, signal.tf, time.time()),
    )
    db.execute("UPDATE signals SET status='queued' WHERE id=?", (sig_id,))
    db.log_event(
        "info",
        f"فەرمان دروستکرا #{order_id} {signal.action} {signal.symbol}"
        + (f" tf{signal.tf} magic={signal.magic}" if signal.magic else ""),
    )
    return {"accepted": True, "order_id": order_id, "client_id": client_id,
            "magic": signal.magic, "tf": signal.tf}


# --------------------------------------------------------------------------
# 1b) LAOL indicators (BETA 1 / BETA 2.5) — فۆرماتی سروشتی
# --------------------------------------------------------------------------
@app.post("/webhook/laol/{source}")
async def laol_webhook(source: str, request: Request, secret: str = ""):
    """
    وەرگرتنی ڕاستەوخۆی پەیامەکانی BETA 1 / BETA 2.5 بەبێ دەستکاریکردنی Pine.

    URL نموونە:
        https://your-server.com/webhook/laol/laol-beta1?secret=YOUR_SECRET
    """
    if secret != TV_SECRET:
        raise HTTPException(401, "نهێنی هەڵەیە")

    raw = (await request.body()).decode("utf-8", "ignore").strip()
    settings = db.get_settings()

    try:
        signal, reason, info = laol_adapter.parse(raw, source, TV_SECRET, settings)
    except laol_adapter.LaolParseError as exc:
        db.execute(
            "INSERT INTO signals(ts, source, raw, status, reason) VALUES (?,?,?,?,?)",
            (time.time(), source, raw, "rejected", str(exc)[:300]),
        )
        db.log_event("error", f"LAOL parse ({source}): {exc}")
        raise HTTPException(422, str(exc))

    if signal is None:
        db.execute(
            "INSERT INTO signals(ts, source, raw, status, reason) VALUES (?,?,?,?,?)",
            (time.time(), source, raw, "skipped", reason),
        )
        return {"accepted": False, "reason": reason, "info": info}

    sig_id = db.execute(
        "INSERT INTO signals(ts, source, raw, symbol, action, status) VALUES (?,?,?,?,?,?)",
        (time.time(), source, raw, signal.symbol, signal.action, "received"),
    )
    result = _process_signal(signal, sig_id)
    if isinstance(result, dict):
        result["tier"] = info.get("tier")
        result["laol_signal"] = info.get("signal")
    return result


# --------------------------------------------------------------------------
# 2) MT5 Expert Advisor <-> server
# --------------------------------------------------------------------------
def _check_ea(token: str) -> None:
    if token != EA_TOKEN:
        raise HTTPException(401, "تۆکنی EA هەڵەیە")


@app.get("/api/orders/next")
def next_order(token: str):
    """EA هەموو 1–3 چرکەیەک لێرە دەپرسێت: فەرمانی نوێ هەیە؟"""
    _check_ea(token)
    # بەسەرچوونی فەرمانە کۆنەکان
    db.execute(
        "UPDATE orders SET status='expired', error='ماوەی بەسەرچوو' "
        "WHERE status='pending' AND ts < ?",
        (time.time() - ORDER_TTL_SEC,),
    )
    rows = db.query("SELECT * FROM orders WHERE status='pending' ORDER BY id ASC LIMIT 1")
    if not rows:
        return {"has_order": False, "pending": 0}
    pending_left = db.query("SELECT COUNT(*) c FROM orders WHERE status='pending'")[0]["c"]
    o = rows[0]
    db.execute("UPDATE orders SET status='sent', updated_ts=? WHERE id=?", (time.time(), o["id"]))
    s = db.get_settings()
    passthrough = bool(s.get("laol_passthrough", True))

    # لە مۆدی passthrough دا EA هیچ شتێک زیاد ناکات و هیچ پۆزیشنێک نادات:
    # SL/TP وەک خۆی لە ئیندیکەیتەرەوە، بەبێ سنووری سپرێد، بەبێ پێچەوانەکردن.
    return {
        "has_order": True,
        # ژمارەی فەرمانی چاوەڕوان — EA بەکاریدەهێنێت بۆ خێراکردنی داواکاری
        "pending": max(0, pending_left - 1),
        "order": {
            "id": o["id"],
            "client_id": o["client_id"],
            "symbol": o["symbol"],
            "action": o["action"],
            "order_type": o["order_type"],
            "volume": o["volume"],
            "price": o["price"],
            "sl": o["sl"],
            "tp": o["tp"],
            "risk_pct": o["risk_pct"],
            # جیاکردنەوەی لەیئاوتەکان — EA بەم ژمارەیە ئۆردەرەکان جیا دەکاتەوە
            "magic": o["magic"] or 0,
            "tf": o["tf"] or "",
            "max_lot": s["max_lot"],
            "max_spread_points": 0 if passthrough else s["max_spread_points"],
            "allow_reverse": False if passthrough else s["allow_reverse"],
            "default_sl_points": 0 if passthrough else s["default_sl_points"],
            "default_tp_points": 0 if passthrough else s["default_tp_points"],
            "trailing_enabled": False if passthrough else s["trailing_enabled"],
            "trailing_start_points": s["trailing_start_points"],
            "trailing_step_points": s["trailing_step_points"],
            "break_even_points": 0 if passthrough else s["break_even_points"],
        },
    }


@app.post("/api/orders/report")
def order_report(rep: ExecReport):
    _check_ea(rep.token)
    rows = db.query("SELECT * FROM orders WHERE client_id=?", (rep.client_id,))
    if not rows:
        raise HTTPException(404, "فەرمان نەدۆزرایەوە")
    db.execute(
        "UPDATE orders SET status=?, ticket=?, fill_price=?, error=?, updated_ts=? WHERE client_id=?",
        (rep.status, rep.ticket, rep.fill_price, rep.error, time.time(), rep.client_id),
    )
    db.log_event("info" if rep.status == "filled" else "error",
                 f"ڕاپۆرت {rep.client_id}: {rep.status} {rep.error}")
    return {"ok": True}


@app.post("/api/account/report")
def account_report(rep: AccountReport):
    """heartbeat ی EA — هەموو 5–10 چرکەیەک."""
    _check_ea(rep.token)
    db.execute(
        """INSERT INTO account_snapshots(ts, login, broker, currency, balance, equity, margin,
                                         free_margin, margin_level, open_positions)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (time.time(), rep.login, rep.broker, rep.currency, rep.balance, rep.equity,
         rep.margin, rep.free_margin, rep.margin_level, json.dumps(rep.positions)),
    )
    db.execute("DELETE FROM account_snapshots WHERE id < (SELECT MAX(id)-500 FROM account_snapshots)")
    return {"ok": True, "trading_enabled": db.get_settings()["trading_enabled"]}


@app.post("/api/trades/closed")
def closed_trade(payload: dict = Body(...)):
    _check_ea(payload.get("token", ""))
    db.execute(
        """INSERT INTO trades(ts, ticket, symbol, side, volume, open_price, close_price, profit, closed_ts)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (time.time(), payload.get("ticket", 0), payload.get("symbol", ""), payload.get("side", ""),
         payload.get("volume", 0), payload.get("open_price", 0), payload.get("close_price", 0),
         payload.get("profit", 0), payload.get("closed_ts", time.time())),
    )
    return {"ok": True}


# --------------------------------------------------------------------------
# 3) Dashboard API
# --------------------------------------------------------------------------
@app.get("/api/state")
def state():
    acc = risk.latest_account()
    if acc and acc.get("open_positions"):
        try:
            acc["open_positions"] = json.loads(acc["open_positions"])
        except Exception:
            acc["open_positions"] = []
    return {
        "settings": db.get_settings(),
        "account": acc,
        "daily": risk.daily_stats(),
        "confluence": confluence.status(ALLOWED_SYMBOLS[0] if ALLOWED_SYMBOLS else "XAUUSD"),
        "connected": bool(acc and time.time() - acc["ts"] < 30),
        "orders": db.query("SELECT * FROM orders ORDER BY id DESC LIMIT 25"),
        "signals": db.query("SELECT * FROM signals ORDER BY id DESC LIMIT 25"),
        "trades": db.query("SELECT * FROM trades ORDER BY id DESC LIMIT 25"),
        "events": db.query("SELECT * FROM events ORDER BY id DESC LIMIT 30"),
        "stats": _stats(),
    }


def _stats() -> dict:
    rows = db.query("SELECT profit FROM trades")
    profits = [r["profit"] or 0 for r in rows]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "total_trades": len(profits),
        "win_rate": round(len(wins) / len(profits) * 100, 2) if profits else 0,
        "net_profit": round(sum(profits), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else 0,
        "avg_win": round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0,
    }


@app.post("/api/settings")
def update_settings(patch: dict = Body(...)):
    out = db.set_settings(patch)
    db.log_event("info", f"ڕێکخستن نوێکرایەوە: {list(patch.keys())}")
    return out


@app.post("/api/confluence/sources")
def set_sources(payload: dict = Body(...)):
    """
    پێناسەکردنی سەرچاوەکان و کێشیان، نموونە:
        {"sources": {"laol-beta1": 1.0, "laol-beta25": 1.5}}
    ناوەکان دەبێت هەمان `strategy` ی ناو پەیامی TradingView بن.
    """
    src = payload.get("sources", {})
    if not isinstance(src, dict):
        raise HTTPException(422, "sources دەبێت object بێت")
    db.set_settings({"confluence_sources": {str(k): float(v) for k, v in src.items()}})
    db.log_event("info", f"سەرچاوەکانی confluence: {list(src.keys())}")
    return confluence.status()


@app.post("/api/confluence/reset")
def reset_votes():
    """سڕینەوەی هەموو دەنگە چاوەڕوانەکان."""
    db.execute("UPDATE votes SET consumed=1 WHERE consumed=0")
    db.log_event("info", "دەنگەکانی confluence سڕانەوە")
    return {"ok": True}


@app.post("/api/panic")
def panic():
    """ڕاگرتنی خێرا: ترەیدینگ دەکوژێنێتەوە + فەرمانی داخستنی هەموو پۆزیشنەکان دەنێرێت."""
    db.set_settings({"trading_enabled": False})
    cid = f"panic-{uuid.uuid4().hex[:8]}"
    db.execute(
        """INSERT INTO orders(ts, client_id, symbol, action, order_type, status, updated_ts)
           VALUES (?,?,?,?,?,'pending',?)""",
        (time.time(), cid, "ALL", "close_all", "market", time.time()),
    )
    db.log_event("warn", "PANIC: هەموو پۆزیشنەکان دادەخرێن و ترەیدینگ ڕاگیرا")
    return {"ok": True, "client_id": cid}


@app.post("/api/manual-order")
def manual_order(payload: dict = Body(...)):
    """ترەیدی دەستی لە داشبۆردەوە."""
    cid = f"manual-{uuid.uuid4().hex[:8]}"
    oid = db.execute(
        """INSERT INTO orders(ts, client_id, symbol, action, order_type, volume, price, sl, tp,
                              risk_pct, status, updated_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)""",
        (time.time(), cid, payload.get("symbol", "XAUUSD"), payload.get("action", "buy"),
         "market", float(payload.get("volume", 0) or 0), 0.0,
         float(payload.get("sl", 0) or 0), float(payload.get("tp", 0) or 0),
         float(payload.get("risk_pct", 0) or 0), time.time()),
    )
    return {"ok": True, "order_id": oid, "client_id": cid}


@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": time.time()}


# --------------------------------------------------------------------------
# 4) Static dashboard
# --------------------------------------------------------------------------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
