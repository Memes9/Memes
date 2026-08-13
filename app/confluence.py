"""
Confluence engine — لێکدانەوەی سیگناڵی چەند ئیندیکەیتەرێک پێکەوە.

بیرۆکە: هەر ئیندیکەیتەرێک بە جیا سیگناڵی خۆی دەنێرێت (بە `strategy` ی جیاواز).
ترەید تەنها کاتێک دەکرێتەوە کە شەرتەکانی confluence جێبەجێ بن:

  mode = "all"      -> هەموو سەرچاوەکان دەبێت هاوڕا بن (AND)
  mode = "any"      -> یەکێکیان بەسە (OR)
  mode = "weighted" -> کۆی خاڵەکان >= confluence_min_score

هەموو دەنگەکان تەنها بۆ ماوەی `confluence_window_sec` بەکاردێن. دەنگی
پێچەوانە دەنگی کۆنی هەمان سەرچاوە دەسڕێتەوە (لۆجیکی flip).
"""
from __future__ import annotations

import json
import time

from . import db

VOTE_SCHEMA = """
CREATE TABLE IF NOT EXISTS votes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    source    TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    action    TEXT NOT NULL,       -- buy|sell
    price     REAL DEFAULT 0,
    sl        REAL DEFAULT 0,
    tp        REAL DEFAULT 0,
    consumed  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_votes_lookup ON votes(symbol, source, consumed, ts);
"""

DEFAULTS = {
    "confluence_enabled": False,
    # {"laol-beta1": 1.0, "laol-beta25": 1.0}
    "confluence_sources": {},
    "confluence_mode": "all",         # all | any | weighted
    "confluence_window_sec": 300,     # ٥ خولەک: ماوەی هاوڕابوون
    "confluence_min_score": 2.0,      # تەنها بۆ weighted
    "confluence_sl_policy": "widest",  # widest | tightest | first | last
    "confluence_tp_policy": "nearest",  # nearest | farthest | first | last
}


def init() -> None:
    from . import laol_adapter

    db.execute_script(VOTE_SCHEMA)
    for k, v in {**DEFAULTS, **laol_adapter.DEFAULTS}.items():
        db.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)",
            (k, json.dumps(v)),
        )


# ---------------------------------------------------------------- helpers
def _cfg() -> dict:
    s = db.get_settings()
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in s:
            out[k] = s[k]
    if isinstance(out["confluence_sources"], str):
        try:
            out["confluence_sources"] = json.loads(out["confluence_sources"])
        except Exception:
            out["confluence_sources"] = {}
    return out


def record_vote(signal) -> None:
    """تۆمارکردنی دەنگی ئیندیکەیتەرێک + سڕینەوەی دەنگی پێچەوانەی هەمان سەرچاوە."""
    db.execute(
        "UPDATE votes SET consumed=1 WHERE source=? AND symbol=? AND consumed=0",
        (signal.strategy, signal.symbol),
    )
    db.execute(
        "INSERT INTO votes(ts, source, symbol, action, price, sl, tp, consumed) "
        "VALUES (?,?,?,?,?,?,?,0)",
        (time.time(), signal.strategy, signal.symbol, signal.action,
         signal.price, signal.sl, signal.tp),
    )


def active_votes(symbol: str) -> list[dict]:
    cfg = _cfg()
    cutoff = time.time() - float(cfg["confluence_window_sec"])
    return db.query(
        "SELECT * FROM votes WHERE symbol=? AND consumed=0 AND ts >= ? ORDER BY ts DESC",
        (symbol, cutoff),
    )


def evaluate(signal) -> tuple[bool, str, dict]:
    """
    گەڕانەوە: (ئایا ترەید بکرێت؟, هۆکار, زانیاری هاوڕابوون)

    ئەگەر confluence ناچالاک بێت، هەموو سیگناڵێک بەتەنیا کاردەکات.
    """
    cfg = _cfg()
    if not cfg["confluence_enabled"]:
        return True, "confluence ناچالاکە", {}

    sources: dict = cfg["confluence_sources"] or {}
    if not sources:
        return True, "هیچ سەرچاوەیەک پێناسە نەکراوە", {}

    record_vote(signal)
    votes = active_votes(signal.symbol)

    # نوێترین دەنگ بۆ هەر سەرچاوەیەک
    latest: dict[str, dict] = {}
    for v in votes:
        if v["source"] not in latest:
            latest[v["source"]] = v

    direction = signal.action  # buy | sell
    agreeing = {s: v for s, v in latest.items()
                if s in sources and v["action"] == direction}
    disagreeing = [s for s, v in latest.items()
                   if s in sources and v["action"] != direction]

    info = {
        "mode": cfg["confluence_mode"],
        "direction": direction,
        "required": list(sources.keys()),
        "agreeing": list(agreeing.keys()),
        "disagreeing": disagreeing,
        "window_sec": cfg["confluence_window_sec"],
    }

    mode = cfg["confluence_mode"]
    if mode == "any":
        ok = len(agreeing) >= 1
        reason = "یەک سەرچاوە پێویستە" if ok else "هیچ سەرچاوەیەک هاوڕا نییە"
    elif mode == "weighted":
        score = sum(float(sources.get(s, 0)) for s in agreeing)
        info["score"] = score
        info["min_score"] = cfg["confluence_min_score"]
        ok = score >= float(cfg["confluence_min_score"])
        reason = (f"خاڵ {score} >= {cfg['confluence_min_score']}" if ok
                  else f"خاڵی ناتەواو {score} < {cfg['confluence_min_score']}")
    else:  # all
        missing = [s for s in sources if s not in agreeing]
        info["missing"] = missing
        ok = not missing
        reason = ("هەموو سەرچاوەکان هاوڕان" if ok
                  else f"چاوەڕوانی: {', '.join(missing)}")

    if ok:
        # دەنگەکان بەکاردەهێنرێن تا دووبارە ترەید نەکرێتەوە
        ids = [str(v["id"]) for v in latest.values()]
        if ids:
            db.execute(f"UPDATE votes SET consumed=1 WHERE id IN ({','.join(ids)})")

    return ok, reason, info


def merge_levels(signal, info: dict) -> tuple[float, float]:
    """SL/TP لە هەموو سەرچاوە هاوڕاکانەوە کۆدەکاتەوە بەپێی سیاسەتی دیاریکراو."""
    cfg = _cfg()
    if not cfg["confluence_enabled"] or not info.get("agreeing"):
        return signal.sl, signal.tp

    cutoff = time.time() - float(cfg["confluence_window_sec"]) - 5
    rows = db.query(
        "SELECT * FROM votes WHERE symbol=? AND ts >= ? AND action=? ORDER BY ts DESC LIMIT 20",
        (signal.symbol, cutoff, signal.action),
    )
    sls = [r["sl"] for r in rows if r["sl"] and r["sl"] > 0]
    tps = [r["tp"] for r in rows if r["tp"] and r["tp"] > 0]
    is_buy = signal.action == "buy"

    sl = signal.sl
    if sls:
        p = cfg["confluence_sl_policy"]
        if p == "widest":
            sl = min(sls) if is_buy else max(sls)   # دوورترین = پارێزراوتر
        elif p == "tightest":
            sl = max(sls) if is_buy else min(sls)
        elif p == "first":
            sl = sls[-1]
        else:
            sl = sls[0]

    tp = signal.tp
    if tps:
        p = cfg["confluence_tp_policy"]
        if p == "nearest":
            tp = min(tps) if is_buy else max(tps)   # وەرگرتنی زووتری قازانج
        elif p == "farthest":
            tp = max(tps) if is_buy else min(tps)
        elif p == "first":
            tp = tps[-1]
        else:
            tp = tps[0]

    return sl, tp


def status(symbol: str = "XAUUSD") -> dict:
    """دۆخی ئێستای هاوڕابوون بۆ داشبۆرد."""
    cfg = _cfg()
    votes = active_votes(symbol)
    latest: dict[str, dict] = {}
    for v in votes:
        if v["source"] not in latest:
            latest[v["source"]] = {
                "action": v["action"],
                "age_sec": int(time.time() - v["ts"]),
                "price": v["price"],
                "sl": v["sl"],
                "tp": v["tp"],
            }
    return {
        "enabled": cfg["confluence_enabled"],
        "mode": cfg["confluence_mode"],
        "window_sec": cfg["confluence_window_sec"],
        "min_score": cfg["confluence_min_score"],
        "sources": cfg["confluence_sources"],
        "live_votes": latest,
    }
