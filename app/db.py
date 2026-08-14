"""SQLite storage layer for GoldBridge."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

DB_PATH = os.getenv("DB_PATH", "data/goldbridge.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    source        TEXT NOT NULL DEFAULT 'tradingview',
    raw           TEXT NOT NULL,
    symbol        TEXT,
    action        TEXT,
    status        TEXT NOT NULL DEFAULT 'received',   -- received|rejected|queued
    reason        TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    signal_id     INTEGER,
    client_id     TEXT UNIQUE,          -- idempotency key -> magic/comment on MT5
    symbol        TEXT NOT NULL,
    action        TEXT NOT NULL,        -- buy|sell|close|close_all|modify
    order_type    TEXT NOT NULL DEFAULT 'market',
    volume        REAL DEFAULT 0,
    price         REAL DEFAULT 0,
    sl            REAL DEFAULT 0,
    tp            REAL DEFAULT 0,
    risk_pct      REAL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending',    -- pending|sent|filled|failed|expired
    ticket        INTEGER DEFAULT 0,
    fill_price    REAL DEFAULT 0,
    error         TEXT,
    updated_ts    REAL
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    login         TEXT,
    broker        TEXT,
    currency      TEXT,
    balance       REAL,
    equity        REAL,
    margin        REAL,
    free_margin   REAL,
    margin_level  REAL,
    open_positions TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    ticket        INTEGER,
    symbol        TEXT,
    side          TEXT,
    volume        REAL,
    open_price    REAL,
    close_price   REAL,
    profit        REAL,
    closed_ts     REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    level         TEXT NOT NULL,
    message       TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "trading_enabled": True,        # کلیلی سەرەکی (kill switch)
    # ── قەبارەی لۆت: دوو مۆد ──────────────────────────────────────
    #: "fixed"   = لۆتێکی جێگیر کە ترەیدەر خۆی دایدەنێت
    #: "percent" = هەر ١٪ی باڵانس = 0.01 لۆت (SL هیچ ڕۆڵێکی نییە)
    "lot_mode": "percent",
    "fixed_lot": 0.01,              # مۆدی fixed
    "balance_pct": 1.0,             # مۆدی percent — ١٪ی باڵانس
    "risk_pct": 1.0,                # (کۆن) مەترسی بەپێی دووری SL
    "max_lot": 1.0,
    "max_open_positions": 2,
    "max_trades_per_day": 10,
    "max_daily_loss_pct": 3.0,      # ڕاگرتنی ڕۆژانە
    "max_total_drawdown_pct": 10.0,
    "max_spread_points": 40,        # فیلتەری سپرێد بۆ ئاڵتون
    "signal_max_age_sec": 60,       # سیگناڵی کۆن ڕەت دەکرێتەوە
    "session_filter_enabled": False,
    "session_start_utc": "07:00",
    "session_end_utc": "20:00",
    "allow_reverse": True,          # داخستنی پۆزیشنی پێچەوانە پێش کردنەوەی نوێ
    "default_sl_points": 0,         # 0 = تەنها SL ی سیگناڵ بەکاربهێنە
    "default_tp_points": 0,
    "trailing_enabled": False,
    "trailing_start_points": 200,
    "trailing_step_points": 100,
    "break_even_points": 0,

    # ── یاسای ٣: مەکینەی مەترسی جێگیرکراو ──────────────────────────
    #: زۆرترین دووری SL بە پیپ. ئەگەر SL ی سیگناڵ لەمە گەورەتر بێت،
    #: ئۆردەرەکە پێش ئەوەی بگاتە MT5 ڕەت دەکرێتەوە. 0 = ناچالاک.
    "max_sl_pips": 51.0,
    #: ژمارەی پۆینت لە هەر پیپێکدا (ئاڵتون: 1 پیپ = 10 پۆینت = 0.10$)
    "pip_points": 10.0,
    #: ١ سیگناڵ = ١ ئۆردەر — ماوەی ڕاگرتنی سیگناڵی دووبارە بە چرکە.
    #: 0 = تەنها پشکنینی client_id (وەک پێشوو).
    "debounce_sec": 2.0,
}


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_conn = _connect()


#: ستوونە نوێکان کە دواتر زیادکراون — بەبێ لەدەستدانی داتای کۆن
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("orders", "magic", "INTEGER DEFAULT 0"),
    ("orders", "tf", "TEXT DEFAULT ''"),
]


def _migrate() -> None:
    """زیادکردنی ستوونە نوێکان ئەگەر نەبن (سەلامەتە ئەگەر چەند جار بانگ بکرێت)."""
    for table, col, decl in _MIGRATIONS:
        cols = {r[1] for r in _conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db() -> None:
    with _lock:
        _conn.executescript(SCHEMA)
        _migrate()
        for k, v in DEFAULT_SETTINGS.items():
            _conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (k, json.dumps(v)),
            )
        _conn.commit()


def execute_script(sql: str) -> None:
    with _lock:
        _conn.executescript(sql)
        _conn.commit()


def query(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        cur = _conn.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


def execute(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid or 0


# ---------- settings ----------
def get_settings() -> dict:
    rows = query("SELECT key, value FROM settings")
    out = dict(DEFAULT_SETTINGS)
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except json.JSONDecodeError:
            out[r["key"]] = r["value"]
    return out


def set_settings(patch: dict) -> dict:
    known = set(DEFAULT_SETTINGS) | {r["key"] for r in query("SELECT key FROM settings")}
    for k, v in patch.items():
        if k not in known:
            continue
        execute(
            "INSERT INTO settings(key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, json.dumps(v)),
        )
    return get_settings()


def log_event(level: str, message: str) -> None:
    execute("INSERT INTO events(ts, level, message) VALUES (?,?,?)", (time.time(), level, message))
