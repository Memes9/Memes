"""
LAOL adapter — وەرگرتنی فۆرماتی سروشتیی ئیندیکەیتەرەکانی BETA 1 / BETA 2.5.

╔══════════════════════════════════════════════════════════════════╗
║  مۆدی گواستنەوەی تەواو (PASSTHROUGH)                             ║
║                                                                  ║
║  بەپێی داواکاری بەکارهێنەر:                                      ║
║   • هەموو سیگناڵێک دەگوازرێتەوە — بەبێ جیاوازی، بەبێ فیلتەر      ║
║   • SL/TP هەمیشە لە ئیندیکەیتەرەکەوە دێت (ڕێژەیی، بەپێی کاندڵ)   ║
║   • هیچ point/pip ێک لەلایەن سیستەمەوە دانانرێت                  ║
║   • ژمارەی پۆزیشنە کراوەکان سنووردار ناکرێت                      ║
║   • Risk:Reward = 1:8 لە ئیندیکەیتەرەکەوە دێت و ناگۆڕدرێت        ║
╚══════════════════════════════════════════════════════════════════╝

فۆرماتی پەیام:
    {"id":"1699999999-12","signal":"BULL_CONFIRMED","action":"BUY",
     "symbol":"XAUUSD","tf":"1","entry":3350.25,"sl":3345.10,
     "tp":3390.50,"tp_alt":3354.25}

هیچ گۆڕانکارییەک لە کۆدی Pine پێویست نییە.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .models import TVSignal

# ---------------------------------------------------------------- tiers
TIER_FORMING = "forming"
TIER_CONFIRMED = "confirmed"
TIER_FINAL = "final"
TIER_INFO = "info"

#: سیگناڵە ناسراوەکان -> (tier, action)
SIGNAL_MAP: dict[str, tuple[str, str]] = {
    "BEAR_FORMING":          (TIER_FORMING,   "sell"),
    "BULL_FORMING":          (TIER_FORMING,   "buy"),
    "BEAR_CONFIRMED":        (TIER_CONFIRMED, "sell"),
    "BULL_CONFIRMED":        (TIER_CONFIRMED, "buy"),
    "FINAL_ENTRY_BEAR":      (TIER_FINAL,     "sell"),
    "FINAL_ENTRY_BULL":      (TIER_FINAL,     "buy"),
    "ENTRY_LAOL_BEAR_TAKEN": (TIER_INFO,      "sell"),
    "ENTRY_LAOL_BULL_TAKEN": (TIER_INFO,      "buy"),
    "SCALP_LAOL_BEAR_TAKEN": (TIER_INFO,      "sell"),
    "SCALP_LAOL_BULL_TAKEN": (TIER_INFO,      "buy"),
}

DEFAULTS: dict[str, Any] = {
    #: مۆدی گواستنەوەی تەواو — هەموو سیگناڵێک دەبێتە ئۆردەر.
    #: کاتێک True بێت، هیچ فیلتەرێکی LAOL کار ناکات.
    "laol_passthrough": True,
    #: کام TP بەکاربهێنرێت. "tp" = ئەوەی ئیندیکەیتەر دایدەنێت (1:8).
    "laol_tp_mode": "tp",
    #: سیگناڵی *_TAKEN بە بنەڕەت زانیارییە (نە entry). بیکەرەوە ئەگەر
    #: دەتەوێت ئەوانیش ببنە ئۆردەر.
    "laol_trade_info_signals": False,
}


class LaolParseError(ValueError):
    pass


def _infer(sig_name: str) -> tuple[str, str]:
    """دۆزینەوەی (tier, action) بۆ سیگناڵی نەناسراو — بۆ ئیندیکەیتەری داهاتوو."""
    up = sig_name.upper()
    if "BULL" in up or "LONG" in up or "BUY" in up:
        action = "buy"
    elif "BEAR" in up or "SHORT" in up or "SELL" in up:
        action = "sell"
    else:
        action = ""
    if "FINAL" in up:
        tier = TIER_FINAL
    elif "CONFIRM" in up:
        tier = TIER_CONFIRMED
    elif "FORMING" in up:
        tier = TIER_FORMING
    elif "TAKEN" in up:
        tier = TIER_INFO
    else:
        tier = TIER_CONFIRMED
    return tier, action


def parse(raw: str | dict, source: str, secret: str, settings: dict) -> tuple[TVSignal | None, str, dict]:
    """
    گەڕانەوە: (سیگناڵ یان None, هۆکار, زانیاری)

    لە مۆدی passthrough دا تەنها ئەم حاڵەتانە None دەگەڕێننەوە:
      • ئاراستە (buy/sell) نەزانرا
      • سیگناڵی *_TAKEN و `laol_trade_info_signals` ناچالاکە
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LaolParseError(f"JSON نادروست: {exc}") from exc
    else:
        data = raw

    sig_name = str(data.get("signal", "")).strip().upper()
    if not sig_name:
        raise LaolParseError("خانەی 'signal' نەدۆزرایەوە")

    known = sig_name in SIGNAL_MAP
    tier, action = SIGNAL_MAP[sig_name] if known else _infer(sig_name)

    # ئاراستە: یەکەم لە خانەی action، ئەگەر نەبوو لە ناوی سیگناڵەوە
    raw_action = str(data.get("action", "")).strip().lower()
    if raw_action in ("buy", "long"):
        action = "buy"
    elif raw_action in ("sell", "short"):
        action = "sell"

    info = {
        "tier": tier,
        "signal": sig_name,
        "source": source,
        "laol_id": str(data.get("id", "")),
        "tf": str(data.get("tf", "")),
        "known": known,
    }

    if not action:
        raise LaolParseError(f"ئاراستەی سیگناڵ نەزانرا: {sig_name}")

    passthrough = bool(settings.get("laol_passthrough", True))

    # سیگناڵی *_TAKEN تەنها زانیارییە مەگەر بەکارهێنەر بیکاتەوە
    if tier == TIER_INFO and not settings.get("laol_trade_info_signals", False):
        return None, f"سیگناڵی زانیاری ({sig_name}) — بۆ ترەید ناچالاککراوە", info

    # --- ئاستەکان: هەمیشە لە ئیندیکەیتەرەکەوە ---
    def _num(key: str) -> float:
        v = data.get(key, 0)
        if v in (None, "", "na", "NaN"):
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    entry = _num("entry")
    sl = _num("sl")
    tp_main = _num("tp")
    tp_alt = _num("tp_alt")

    tp_mode = settings.get("laol_tp_mode", DEFAULTS["laol_tp_mode"])
    tp = tp_alt if (tp_mode == "tp_alt" and tp_alt > 0) else tp_main
    if tp <= 0:
        tp = tp_main or tp_alt

    is_buy = action == "buy"

    # پشکنینی ئاراستەی SL — تەنها بۆ ڕێگری لە ئۆردەری هەڵە لای بڕۆکەر.
    # ئەمە فیلتەری ستراتیژی نییە؛ ئۆردەری پێچەوانە لای MT5 ڕەت دەکرێتەوە.
    if entry > 0 and sl > 0:
        if is_buy and sl >= entry:
            raise LaolParseError(f"BUY بەڵام SL ({sl}) لەسەرەوەی entry ({entry}) — ئۆردەری نادروست")
        if not is_buy and sl <= entry:
            raise LaolParseError(f"SELL بەڵام SL ({sl}) لەخوارەوەی entry ({entry}) — ئۆردەری نادروست")
        info["rr"] = round(abs(tp - entry) / abs(entry - sl), 2) if tp > 0 else 0

    if not passthrough:
        info["note"] = "passthrough ناچالاکە"

    signal = TVSignal(
        secret=secret,
        action=action,
        symbol=str(data.get("symbol", "XAUUSD")),
        price=entry,
        sl=sl,
        tp=tp,
        strategy=source,
        signal_id=f"{source}-{sig_name}-{data.get('id', '')}",
        comment=f"{sig_name}|tf{data.get('tf', '')}",
    )
    return signal, "ok", info
