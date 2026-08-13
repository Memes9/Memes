"""Pydantic schemas exchanged between TradingView, the server and the MT5 executor."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class TVSignal(BaseModel):
    """پەیامی وێبهۆکی TradingView."""

    secret: str = Field(..., description="نهێنی هاوبەش - پێویستە لەگەڵ TV_WEBHOOK_SECRET بگونجێت")
    action: Literal["buy", "sell", "close", "close_all", "modify"] = "buy"
    symbol: str = "XAUUSD"
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    risk_pct: Optional[float] = None
    volume: Optional[float] = None
    order_type: Literal["market", "limit", "stop"] = "market"
    strategy: str = "default"
    signal_id: Optional[str] = None      # بۆ idempotency (دووبارە نەکردنەوەی ترەید)
    time: Optional[str] = None           # {{timenow}} لە TradingView
    comment: str = ""


class OrderOut(BaseModel):
    """فەرمانێک کە EA لە سێرڤەرەوە وەریدەگرێت."""

    id: int
    client_id: str
    symbol: str
    action: str
    order_type: str
    volume: float
    price: float
    sl: float
    tp: float
    risk_pct: float
    comment: str = ""


class ExecReport(BaseModel):
    """ڕاپۆرتی جێبەجێکردن لە EA / Executor ەوە."""

    token: str
    client_id: str
    status: Literal["filled", "failed", "sent"]
    ticket: int = 0
    fill_price: float = 0.0
    error: str = ""


class AccountReport(BaseModel):
    """دۆخی هەژمار لە MT5 ەوە (heartbeat)."""

    token: str
    login: str = ""
    broker: str = ""
    currency: str = "USD"
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    margin_level: float = 0.0
    spread_points: float = 0.0
    positions: list[dict] = []
