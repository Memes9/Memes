"""Risk / guard engine: هەموو سیگناڵێک لێرەوە تێدەپەڕێت پێش ئەوەی ببێت بە فەرمان."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import db


def _today_start_ts() -> float:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _in_session(s: dict) -> bool:
    if not s.get("session_filter_enabled"):
        return True
    now = datetime.now(timezone.utc).strftime("%H:%M")
    start, end = s.get("session_start_utc", "00:00"), s.get("session_end_utc", "23:59")
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end  # سێشنی بەشەوی


def latest_account() -> dict | None:
    rows = db.query("SELECT * FROM account_snapshots ORDER BY id DESC LIMIT 1")
    return rows[0] if rows else None


def daily_stats() -> dict:
    start = _today_start_ts()
    trades = db.query("SELECT COUNT(*) c FROM orders WHERE ts >= ? AND status IN ('sent','filled')", (start,))
    pnl = db.query("SELECT COALESCE(SUM(profit),0) p FROM trades WHERE closed_ts >= ?", (start,))
    return {"trades_today": trades[0]["c"], "pnl_today": pnl[0]["p"]}


def open_positions_count() -> int:
    acc = latest_account()
    if not acc or not acc.get("open_positions"):
        return 0
    import json

    try:
        return len(json.loads(acc["open_positions"]))
    except Exception:
        return 0


def sl_distance_pips(signal, s: dict | None = None) -> float:
    """دووری SL بە پیپ. 0 ئەگەر SL یان entry نەبێت."""
    s = s if s is not None else db.get_settings()
    entry = float(signal.price or 0)
    sl = float(signal.sl or 0)
    if entry <= 0 or sl <= 0:
        return 0.0
    point = _symbol_point(signal.symbol)
    pip_points = float(s.get("pip_points", 10.0)) or 10.0
    return abs(entry - sl) / (point * pip_points)


def _symbol_point(symbol: str) -> float:
    """پۆینتی سیمبول. ئاڵتون = 0.01، جووتە فۆرێکسەکان = 0.00001."""
    sym = (symbol or "").upper()
    if "XAU" in sym or "GOLD" in sym:
        return 0.01
    if "JPY" in sym:
        return 0.001
    return 0.00001


def check_max_sl(signal, s: dict | None = None) -> tuple[bool, str]:
    """یاسای ٣ — پاراستنی زۆرترین SL.

    ئەگەر دووری SL ی سیگناڵ لە ``max_sl_pips`` گەورەتر بێت، ئۆردەرەکە
    ڕەت دەکرێتەوە پێش ئەوەی بگاتە MT5.
    """
    s = s if s is not None else db.get_settings()
    limit = float(s.get("max_sl_pips", 0) or 0)
    if limit <= 0:
        return True, "ok"
    dist = sl_distance_pips(signal, s)
    if dist <= 0:
        return True, "ok"  # SL نەنێردراوە — پشکنین ناکرێت
    if dist > limit:
        return False, f"SL زۆر گەورەیە ({dist:.1f} پیپ > {limit:.0f} پیپ)"
    return True, "ok"


def check(signal, allowed_symbols: list[str]) -> tuple[bool, str]:
    """گەڕانەوە: (ڕێگەپێدراوە؟, هۆکار)."""
    s = db.get_settings()

    if not s.get("trading_enabled", True):
        return False, "ترەیدینگ ناچالاککراوە (kill switch)"

    if allowed_symbols and signal.symbol.upper() not in [x.upper() for x in allowed_symbols]:
        return False, f"سیمبولی ڕێگەپێنەدراو: {signal.symbol}"

    if signal.action in ("close", "close_all", "modify"):
        return True, "ok"  # داخستن هەمیشە ڕێگەپێدراوە

    # ── یاسای ٣: پاراستنی زۆرترین SL ─────────────────────────────────
    # ئەگەر دووری SL لە سنوور تێپەڕی، ئۆردەرەکە لێرەدا دەوەستێت و
    # هەرگیز ناگاتە MT5. ئەمە پێش passthrough دەپشکنرێت چونکە
    # پاراستنی سەرمایەیە نەک فیلتەری ستراتیژی.
    ok_sl, why_sl = check_max_sl(signal, s)
    if not ok_sl:
        return False, why_sl

    # ── مۆدی گواستنەوەی تەواو ────────────────────────────────────────
    # کاتێک چالاک بێت، تەنها kill switch و سیمبول و سنووری SL کاردەکەن.
    # هەموو سیگناڵێکی تر دەبێتە ئۆردەر — بەبێ سنووری پۆزیشن یان ژمارەی ترەید.
    if s.get("laol_passthrough", True):
        return True, "ok (passthrough)"

    if not _in_session(s):
        return False, "دەرەوەی کاتی سێشنی دیاریکراو"

    # کۆنی سیگناڵ
    if signal.time:
        try:
            ts = datetime.fromisoformat(signal.time.replace("Z", "+00:00")).timestamp()
            age = time.time() - ts
            if age > float(s.get("signal_max_age_sec", 60)):
                return False, f"سیگناڵ زۆر کۆنە ({int(age)} چرکە)"
        except Exception:
            pass

    # فیلتەری سپرێد + دراودان
    acc = latest_account()
    if acc:
        if float(s.get("max_daily_loss_pct", 0)) > 0 and acc.get("balance"):
            pnl = daily_stats()["pnl_today"]
            limit = -abs(float(s["max_daily_loss_pct"]) / 100.0 * float(acc["balance"]))
            if pnl <= limit:
                return False, f"سنووری زیانی ڕۆژانە پڕبووەتەوە ({pnl:.2f})"
        if float(s.get("max_total_drawdown_pct", 0)) > 0 and acc.get("balance"):
            dd = (float(acc["balance"]) - float(acc["equity"])) / float(acc["balance"]) * 100
            if dd >= float(s["max_total_drawdown_pct"]):
                return False, f"drawdown ی گشتی زۆرە ({dd:.2f}%)"

    if open_positions_count() >= int(s.get("max_open_positions", 99)):
        return False, "ژمارەی پۆزیشنە کراوەکان لە سنوورە"

    if daily_stats()["trades_today"] >= int(s.get("max_trades_per_day", 999)):
        return False, "ژمارەی ترەیدی ڕۆژانە پڕبووەتەوە"

    return True, "ok"


def sizing(signal) -> tuple[float, float]:
    """گەڕانەوەی (volume, risk_pct). ئەگەر volume=0 بێت EA خۆی حیسابی دەکات."""
    s = db.get_settings()
    if signal.volume and signal.volume > 0:
        return min(float(signal.volume), float(s.get("max_lot", 1.0))), 0.0
    if float(s.get("fixed_lot", 0)) > 0:
        return min(float(s["fixed_lot"]), float(s.get("max_lot", 1.0))), 0.0
    risk = float(signal.risk_pct if signal.risk_pct is not None else s.get("risk_pct", 0.5))
    return 0.0, risk
