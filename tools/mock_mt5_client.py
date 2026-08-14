"""
Mock MT5 executor — هەمان پرۆتۆکۆلی EA بەکاردێنێت بەڵام ترەیدی خەیاڵی دەکات.
بۆ تاقیکردنەوەی سیستەمەکە بەبێ MetaTrader.

    python tools/mock_mt5_client.py --url http://127.0.0.1:8000 --token change-me-ea-token
"""
from __future__ import annotations

import argparse
import random
import time

import httpx

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8000")
p.add_argument("--token", default="change-me-ea-token")
args = p.parse_args()

BASE, TOKEN = args.url.rstrip("/"), args.token

LONG_POLL_MS = 800   # چاوەڕوانی سێرڤەر بۆ سیگناڵی نوێ (وەک EA)
POLL_SEC = 0.1       # ماوەی سووڕ کاتێک long-poll هیچی نەگەڕاندەوە
balance, equity = 10_000.0, 10_000.0
positions: list[dict] = []
next_ticket = 500_001
price = 3_350.0


def tick() -> float:
    global price
    price = round(price + random.uniform(-1.5, 1.5), 2)
    return price


last_hb = 0.0


def main() -> None:
    c = httpx.Client(timeout=8)
    print(f"Mock MT5 executor -> {BASE}")
    while True:
        try:
            _cycle(c)
        except httpx.HTTPError as e:
            # سێرڤەر ڕیستارت کراوە یان تۆڕ کەوتووە — دووبارە هەوڵ بدەرەوە
            print(f"  ! پەیوەندی نەبوو ({type(e).__name__}) — دووبارە هەوڵ دەدەم")
            time.sleep(1.0)


def _cycle(c: httpx.Client) -> None:
        global next_ticket, balance, equity, last_hb
        px = tick()
        for pos in positions:
            sign = 1 if pos["side"] == "buy" else -1
            pos["profit"] = round((px - pos["open_price"]) * sign * pos["volume"] * 100, 2)
        equity = balance + sum(p_["profit"] for p_ in positions)

        if time.time() - last_hb > 4:
            c.post(f"{BASE}/api/account/report", json={
                "token": TOKEN, "login": "12345678", "broker": "Mock-Demo", "currency": "USD",
                "balance": round(balance, 2), "equity": round(equity, 2), "margin": 120.0,
                "free_margin": round(equity - 120, 2), "margin_level": 850.0,
                "spread_points": 22, "positions": positions,
            })
            last_hb = time.time()

        for _i in range(10):
            # long-polling لە یەکەم داواکاریدا — وەک EA ی ڕاستەقینە
            params = {"token": TOKEN}
            if _i == 0:
                params["wait_ms"] = LONG_POLL_MS
            r = c.get(f"{BASE}/api/orders/next", params=params).json()
            if not r.get("has_order"):
                break
            o = r["order"]
            cid, act = o["client_id"], o["action"]
            print(f"  -> order {cid}: {act} {o['symbol']} sl={o['sl']} tp={o['tp']}")
            if act in ("close", "close_all"):
                for pos in list(positions):
                    balance += pos["profit"]
                    c.post(f"{BASE}/api/trades/closed", json={
                        "token": TOKEN, "ticket": pos["ticket"], "symbol": pos["symbol"],
                        "side": pos["side"], "volume": pos["volume"],
                        "open_price": pos["open_price"], "close_price": px,
                        "profit": pos["profit"], "closed_ts": time.time()})
                    positions.remove(pos)
                c.post(f"{BASE}/api/orders/report", json={
                    "token": TOKEN, "client_id": cid, "status": "filled"})
            else:
                vol = o["volume"] or round(max(0.01, equity * (o["risk_pct"] or 0.5) / 100 / 300), 2)
                pos = {"ticket": next_ticket, "symbol": o["symbol"] or "XAUUSD", "side": act,
                       "volume": vol, "open_price": px, "profit": 0.0}
                next_ticket += 1
                positions.append(pos)
                c.post(f"{BASE}/api/orders/report", json={
                    "token": TOKEN, "client_id": cid, "status": "filled",
                    "ticket": pos["ticket"], "fill_price": px})
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
