"""
LAOL adapter — وەرگرتنی فۆرماتی سروشتیی ئیندیکەیتەرەکانی BETA 1 / BETA 2.5.

ئەم ئیندیکەیتەرانە پێشتر `alert()` یان تێدایە بەم شێوەیە:

    {"id":"1699999999-12","signal":"BULL_CONFIRMED","action":"BUY",
     "symbol":"XAUUSD","tf":"1","entry":3350.25,"sl":3345.10,
     "tp":3390.50,"tp_alt":3354.25}

بۆیە **هیچ گۆڕانکارییەک لە کۆدی Pine پێویست نییە**. تەنها ئەم ئەدەپتەرە
پەیامەکە وەردەگرێت و دەیگۆڕێت بۆ فۆرماتی ناوخۆیی سیستەمەکە.

جۆرەکانی سیگناڵ (tier):
    FORMING       — لەسەر کەندیلی تەواو نەبوو دەردەچێت  ⚠ ڕەنگە بگۆڕدرێت
    CONFIRMED     — لەسەر داخستنی کەندیلی M1
    FINAL_ENTRY   — بەهێزترین: هەموو شەرتەکان + شکاندنی LAOL
    *_TAKEN       — تەنها زانیاری، ترەید ناکات
"""
from __future__ import annotations

import json
from typing import Any

from .models import TVSignal

# ---------------------------------------------------------------- tiers
TIER_FORMING = "forming"
TIER_CONFIRMED = "confirmed"
TIER_FINAL = "final"
TIER_INFO = "info"

SIGNAL_MAP: dict[str, tuple[str, str]] = {
    # signal name          -> (tier, action)
    "BEAR_FORMING":        (TIER_FORMING,   "sell"),
    "BULL_FORMING":        (TIER_FORMING,   "buy"),
    "BEAR_CONFIRMED":      (TIER_CONFIRMED, "sell"),
    "BULL_CONFIRMED":      (TIER_CONFIRMED, "buy"),
    "FINAL_ENTRY_BEAR":    (TIER_FINAL,     "sell"),
    "FINAL_ENTRY_BULL":    (TIER_FINAL,     "buy"),
    # زانیاری تەنها — ترەید ناکەن
    "ENTRY_LAOL_BEAR_TAKEN": (TIER_INFO, ""),
    "ENTRY_LAOL_BULL_TAKEN": (TIER_INFO, ""),
    "SCALP_LAOL_BEAR_TAKEN": (TIER_INFO, ""),
    "SCALP_LAOL_BULL_TAKEN": (TIER_INFO, ""),
}

DEFAULTS: dict[str, Any] = {
    # کام ئاستی سیگناڵ ترەید بکات
    "laol_trade_forming": False,     # ⚠ بنەڕەت: ناچالاک (ڕەنگە repaint بکات)
    "laol_trade_confirmed": True,
    "laol_trade_final": True,
    # کام TP بەکاربهێنرێت: "tp" (٨ ئەوەندەی مەترسی) یان "tp_alt" (٤٠ pip)
    "laol_tp_mode": "tp_alt",
    # زیادکردنی مەودای ئارامی بۆ SL (بە point)
    "laol_sl_buffer_points": 0,
    # زۆرترین دووری SL — ئەگەر زیاتر بوو سیگناڵ ڕەت دەکرێتەوە (0 = بێ سنوور)
    "laol_max_sl_points": 0,
    # کەمترین دووری SL — ڕێگری لە SL ی زۆر تەسک
    "laol_min_sl_points": 0,
}


class LaolParseError(ValueError):
    pass


def parse(raw: str | dict, source: str, secret: str, settings: dict) -> tuple[TVSignal | None, str, dict]:
    """
    گەڕانەوە: (سیگناڵ یان None, هۆکار, زانیاری)

    ئەگەر None بگەڕێتەوە واتە سیگناڵەکە ترەید ناکات (بەڵام هەڵە نییە).
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LaolParseError(f"JSON نادروست: {exc}") from exc
    else:
        data = raw

    sig_name = str(data.get("signal", "")).upper()
    if not sig_name:
        raise LaolParseError("خانەی 'signal' نەدۆزرایەوە")

    if sig_name not in SIGNAL_MAP:
        raise LaolParseError(f"جۆری سیگناڵی نەناسراو: {sig_name}")

    tier, action = SIGNAL_MAP[sig_name]
    info = {"tier": tier, "signal": sig_name, "source": source,
            "laol_id": str(data.get("id", "")), "tf": str(data.get("tf", ""))}

    if tier == TIER_INFO:
        return None, f"سیگناڵی زانیاری ({sig_name}) — ترەید ناکات", info

    # ئایا ئەم ئاستە ڕێگەپێدراوە؟
    gate = {
        TIER_FORMING: "laol_trade_forming",
        TIER_CONFIRMED: "laol_trade_confirmed",
        TIER_FINAL: "laol_trade_final",
    }[tier]
    if not settings.get(gate, DEFAULTS[gate]):
        return None, f"ئاستی '{tier}' ناچالاککراوە لە ڕێکخستنەکاندا", info

    # --- ئاستەکان ---
    try:
        entry = float(data.get("entry", 0) or 0)
        sl = float(data.get("sl", 0) or 0)
        tp_main = float(data.get("tp", 0) or 0)
        tp_alt = float(data.get("tp_alt", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise LaolParseError(f"ئاستی ژمارەیی نادروست: {exc}") from exc

    tp_mode = settings.get("laol_tp_mode", DEFAULTS["laol_tp_mode"])
    tp = tp_alt if (tp_mode == "tp_alt" and tp_alt > 0) else tp_main
    if tp <= 0:
        tp = tp_main or tp_alt

    is_buy = action == "buy"

    # پشکنینی لۆجیکی ئاستەکان — پارێزەری گرنگ
    if entry > 0 and sl > 0:
        if is_buy and sl >= entry:
            raise LaolParseError(f"BUY بەڵام SL ({sl}) لەسەرەوەی entry ({entry})")
        if not is_buy and sl <= entry:
            raise LaolParseError(f"SELL بەڵام SL ({sl}) لەخوارەوەی entry ({entry})")

    # مەودای ئارامی + سنوورەکانی SL
    point = float(settings.get("_point", 0.01)) or 0.01
    buf = float(settings.get("laol_sl_buffer_points", 0)) * point
    if buf > 0 and sl > 0:
        sl = sl + buf if not is_buy else sl - buf

    if entry > 0 and sl > 0:
        sl_pts = abs(entry - sl) / point
        info["sl_points"] = round(sl_pts, 1)
        max_sl = float(settings.get("laol_max_sl_points", 0))
        min_sl = float(settings.get("laol_min_sl_points", 0))
        if max_sl > 0 and sl_pts > max_sl:
            return None, f"SL زۆر دوورە ({sl_pts:.0f} > {max_sl:.0f} point)", info
        if min_sl > 0 and sl_pts < min_sl:
            return None, f"SL زۆر تەسکە ({sl_pts:.0f} < {min_sl:.0f} point)", info

    signal = TVSignal(
        secret=secret,
        action=action,
        symbol=str(data.get("symbol", "XAUUSD")),
        price=entry,
        sl=sl,
        tp=tp,
        strategy=source,
        # ناسنامەی بێهاوتا: سەرچاوە + ناوی سیگناڵ + id ی ناو Pine
        signal_id=f"{source}-{sig_name}-{data.get('id', '')}",
        comment=f"{sig_name}|tf{data.get('tf', '')}",
    )
    return signal, "ok", info
