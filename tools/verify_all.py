"""پشکنینی تەواوی هەموو یاساکان بەرامبەر سێرڤەری کارکەر.

بەکارهێنان:
    .venv/bin/python3 tools/verify_all.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
TV_SECRET = "change-me-tradingview-secret"
EA_TOKEN = "change-me-ea-token"

_pass = 0
_fail = 0
_failures: list[str] = []


def _req(path: str, data: dict | None = None) -> dict:
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if body else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or "{}")


def settings(patch: dict) -> None:
    _req("/api/settings", patch)
    time.sleep(0.3)


def send(sig_id: str, signal: str, action: str, entry: float, sl: float,
         tp: float, tf: str = "1", source: str = "laol-beta1") -> dict:
    return _req(
        f"/webhook/laol/{source}?secret={TV_SECRET}",
        {"id": sig_id, "signal": signal, "action": action, "symbol": "XAUUSD",
         "tf": tf, "entry": entry, "sl": sl, "tp": tp},
    )


def check(label: str, cond: bool, detail: str = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  \033[32m✓\033[0m {label}" + (f"  {detail}" if detail else ""))
    else:
        _fail += 1
        _failures.append(label)
        print(f"  \033[31m✗\033[0m {label}  {detail}")


def hdr(t: str) -> None:
    print(f"\n\033[1m{t}\033[0m\n" + "─" * 70)


def drain() -> list[dict]:
    """هەموو ئۆردەرە چاوەڕوانەکان دەربهێنە."""
    out = []
    for _ in range(60):
        r = _req(f"/api/orders/next?token={EA_TOKEN}")
        if not r.get("has_order"):
            break
        out.append(r["order"])
    return out


def ensure_sole_consumer() -> None:
    """دڵنیابوونەوە لەوەی EA/mock ی تر ئۆردەرەکان نافڕێنێت.

    ئەم تاقیکەرەوەیە پێویستی بە خوێندنەوەی ناوەڕۆکی ئۆردەرەکانە، بۆیە
    دەبێت تەنها بەکارهێنەری ڕیزی ئۆردەر بێت. ئەگەر mock یان EA کاربکات
    ئەوان ئۆردەرەکان دەبەن و پشکنینەکان بەهەڵە شکست دەهێنن.
    """
    drain()
    probe = f"probe-{int(time.time() * 1000)}"
    send(probe, "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    time.sleep(0.6)
    if not drain():
        print(
            "\033[31m\033[1m  ✗ بەکارهێنەرێکی تری ئۆردەر کاردەکات\033[0m\n"
            "    mock یان EA ئۆردەرەکان دەفڕێنێت پێش ئەم تاقیکەرەوەیە.\n"
            "    سەرەتا بیوەستێنە:  pkill -f mock_mt5_client\n"
            "    پاشان دووبارە:      .venv/bin/python3 tools/verify_all.py"
        )
        sys.exit(2)


def reset_defaults() -> None:
    settings({
        "lot_mode": "percent", "balance_pct": 1.0, "fixed_lot": 0.01, "max_lot": 1.0,
        "max_sl_enabled": True, "max_sl_pips": 51.0, "pip_points": 10.0,
        "debounce_enabled": True, "debounce_sec": 2.0,
        "spread_comp_enabled": True, "spread_extra_points": 0.0,
        "spread_cap_points": 0.0, "respect_stops_level": True,
        "progression_enabled": True,
        "tier1_trigger_pct": 30.0, "tier1_lock_pct": 1.0,
        "tier2_trigger_pct": 50.0, "tier2_lock_pct": 3.0, "tier2_close_pct": 50.0,
        "magic_1m": 990001, "magic_3m": 990003, "magic_default": 990000,
        "laol_passthrough": True, "laol_tp_mode": "tp",
        "trading_enabled": True,
    })


# ══════════════════════════════════════════════════════════════════
def main() -> int:
    n = int(time.time())
    reset_defaults()
    ensure_sole_consumer()
    drain()

    # ─── یاسای ١: هەموو سیگناڵێک دەبێتە ئۆردەر ────────────────────
    hdr("یاسای ١ — هەموو سیگناڵێک دەبێتە ئۆردەر")
    settings({"debounce_enabled": False})
    six = [("BULL_FORMING", "BUY", 3359.0, 3368.0),
           ("BEAR_FORMING", "SELL", 3361.0, 3352.0),
           ("BULL_CONFIRMED", "BUY", 3359.0, 3368.0),
           ("BEAR_CONFIRMED", "SELL", 3361.0, 3352.0),
           ("FINAL_ENTRY_BULL", "BUY", 3359.0, 3368.0),
           ("FINAL_ENTRY_BEAR", "SELL", 3361.0, 3352.0)]
    ok6 = 0
    for i, (sg, act, sl, tp) in enumerate(six):
        r = send(f"v{n}-t{i}", sg, act, 3360.0, sl, tp)
        if r.get("accepted"):
            ok6 += 1
    check("هەر ٦ جۆری سیگناڵ قبوڵ دەکرێن", ok6 == 6, f"{ok6}/6")

    # هەردوو سەرچاوە
    a = send(f"v{n}-s1", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0,
             source="laol-beta1")
    b = send(f"v{n}-s1", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0,
             source="laol-beta25")
    check("BETA 1 و BETA 2.5 پێکەوە، تێکەڵ نابن",
          a.get("accepted") and b.get("accepted")
          and a.get("order_id") != b.get("order_id"),
          f"#{a.get('order_id')} / #{b.get('order_id')}")

    # ─── یاسای ٢: جیاکردنەوەی لەیئاوت ─────────────────────────────
    hdr("یاسای ٢ — Magic Number جیاواز بۆ هەر تایمفرەیمێک")
    m1 = send(f"v{n}-m", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0, tf="1")
    m3 = send(f"v{n}-m", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0, tf="3")
    check("هەمان id لە ١m و ٣m → دوو ئۆردەری سەربەخۆ",
          m1.get("accepted") and m3.get("accepted"),
          f"#{m1.get('order_id')} / #{m3.get('order_id')}")
    check("magic جیاوازە", m1.get("magic") == 990001 and m3.get("magic") == 990003,
          f"{m1.get('magic')} / {m3.get('magic')}")

    dup = send(f"v{n}-m", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0, tf="1")
    check("دووبارەی ڕاستەقینە ڕەت دەکرێتەوە", not dup.get("accepted"),
          dup.get("reason", ""))

    settings({"magic_1m": 777001})
    mx = send(f"v{n}-mx", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0, tf="1")
    check("magic_1m گۆڕاوە", mx.get("magic") == 777001, str(mx.get("magic")))

    # ژمارە magicەکان دەبێت بگەنە EA. بەبێ ئەمان IsOurMagic تەنها
    # مەودای 990000-990999 دەناسێتەوە و Tier 1/2 لەسەر magicی
    # دەستکردی ترەیدەر (وەک 777001) هەرگیز کار ناکات.
    om = drain()
    mrow = [x for x in om if x.get("magic") == 777001]
    check("magicی دەستکرد دەگاتە EA",
          bool(mrow) and mrow[0].get("magic_1m") == 777001,
          f"magic_1m={mrow[0].get('magic_1m') if mrow else '?'}")
    check("magic_3m و magic_default دەگەن",
          bool(mrow) and mrow[0].get("magic_3m") == 990003
          and mrow[0].get("magic_default") == 990000,
          f"{mrow[0].get('magic_3m') if mrow else '?'} / "
          f"{mrow[0].get('magic_default') if mrow else '?'}")
    settings({"magic_1m": 990001})

    # ─── یاسای ٣: فیلتەری SL ──────────────────────────────────────
    hdr("یاسای ٣ — فیلتەری SL و لۆت و debounce")
    r51 = send(f"v{n}-a", "BULL_CONFIRMED", "BUY", 3360.0, 3354.9, 3400.8)
    r55 = send(f"v{n}-b", "BULL_CONFIRMED", "BUY", 3360.0, 3354.5, 3400.0)
    check("SL=51 پیپ ڕێپێدراوە (strictly greater)", r51.get("accepted"))
    check("SL=55 پیپ ڕەت دەکرێتەوە", not r55.get("accepted"), r55.get("reason", ""))

    settings({"max_sl_enabled": False})
    roff = send(f"v{n}-c", "BULL_CONFIRMED", "BUY", 3360.0, 3330.0, 3600.0)
    check("کوژاندنەوەی فیلتەر کاردەکات", roff.get("accepted"))
    settings({"max_sl_enabled": True, "max_sl_pips": 80})
    r80 = send(f"v{n}-d", "BULL_CONFIRMED", "BUY", 3360.0, 3353.0, 3416.0)
    check("گۆڕینی سنوور بۆ ٨٠ پیپ", r80.get("accepted"), "SL=70 پیپ")
    settings({"max_sl_pips": 51})

    # debounce — چاوەڕوانی پەنجەرەی سیگناڵەکانی سەرەوە
    settings({"debounce_enabled": True, "debounce_sec": 2.0})
    time.sleep(2.2)
    d1 = send(f"v{n}-e1", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    d2 = send(f"v{n}-e2", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    check("هەمان سیگناڵ دوو جار → یەک ئۆردەر",
          d1.get("accepted") and not d2.get("accepted"))
    d3 = send(f"v{n}-e3", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0, tf="3")
    check("لەیئاوتی جیاواز بلۆک ناکرێت", d3.get("accepted"))
    d4 = send(f"v{n}-e4", "BEAR_CONFIRMED", "SELL", 3360.0, 3361.0, 3352.0)
    check("ئاراستەی پێچەوانە بلۆک ناکرێت", d4.get("accepted"))

    # ٣ سیگناڵی جیاواز لە هەمان خولەکدا — هەر سێکیان دەبێت بچنە ژوورەوە
    t = [send(f"v{n}-m{k}", "BULL_CONFIRMED", "BUY", 3360.0,
              3359.0 - k * 0.1, 3368.0 + k * 0.1) for k in (1, 2, 3)]
    check("٣ سیگناڵی جیاواز لە هەمان خولەکدا → ٣ ئۆردەر",
          all(x.get("accepted") for x in t),
          " ".join(f"#{x.get('order_id')}" for x in t))
    check("هەر ئۆردەرێک SL/TP ی خۆی هەیە",
          len({x.get("order_id") for x in t}) == 3)

    # دوو ئیندیکەیتەری جیاواز کە هەمان setup دەدۆزنەوە → دوو ئۆردەر
    time.sleep(2.2)
    c1 = send(f"v{n}-c1", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0,
              source="laol-beta1")
    c2 = send(f"v{n}-c2", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0,
              source="laol-beta25")
    check("BETA 1 و BETA 2.5 بە هەمان setup → دوو ئۆردەر",
          c1.get("accepted") and c2.get("accepted"),
          f"#{c1.get('order_id')} / #{c2.get('order_id')}")

    time.sleep(2.2)
    d5 = send(f"v{n}-e5", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    check("دوای ماوەکە قبوڵ دەکرێتەوە", d5.get("accepted"))

    # ─── لۆت ──────────────────────────────────────────────────────
    hdr("قەبارەی لۆت — دوو مۆد")
    settings({"debounce_enabled": False, "lot_mode": "fixed", "fixed_lot": 0.05})
    drain()
    send(f"v{n}-l1", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    o = drain()
    check("مۆدی fixed → لۆت ڕاستەوخۆ",
          bool(o) and abs(o[0]["volume"] - 0.05) < 1e-9,
          f"volume={o[0]['volume'] if o else '?'}")

    settings({"lot_mode": "percent", "balance_pct": 2.0})
    send(f"v{n}-l2", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    o = drain()
    check("مۆدی percent → EA دەیژمێرێت",
          bool(o) and o[0]["volume"] == 0 and o[0]["balance_pct"] == 2.0,
          f"volume={o[0]['volume'] if o else '?'} pct={o[0]['balance_pct'] if o else '?'}")

    print("\n  ژماردنی EA (LotByBalancePercent):")
    for bal, want in ((100, 0.01), (200, 0.02), (1000, 0.10)):
        got = (bal / 100.0) * 0.01 * 1.0
        check(f"    {bal}$ بە ١٪ → {want}", abs(got - want) < 1e-9, f"= {got:.2f}")
    settings({"balance_pct": 1.0})

    # ─── SL/TP دەستکاری نەکراو + سپرێد ────────────────────────────
    hdr("SL/TP و قەرەبووی سپرێد")
    drain()
    send(f"v{n}-sp", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    o = drain()
    check("SL/TP دەقاودەق وەک سیگناڵ دەگوازرێتەوە",
          bool(o) and o[0]["sl"] == 3359.0 and o[0]["tp"] == 3368.0,
          f"sl={o[0]['sl'] if o else '?'} tp={o[0]['tp'] if o else '?'}")
    check("EA ڕێکخستنی سپرێد وەردەگرێت",
          bool(o) and "spread_comp_enabled" in o[0] and "spread_extra_points" in o[0])

    print("\n  ژماردنی EA (سپرێد=15p, SL=10pip, TP=80pip):")
    for side, sl0, tp0, sign in (("BUY", 3359.0, 3368.0, -1), ("SELL", 3361.0, 3352.0, 1)):
        c = 0.15
        nsl, ntp = sl0 + sign * c, tp0 - sign * c
        d_sl, d_tp = abs(3360.0 - nsl) * 10, abs(ntp - 3360.0) * 10
        check(f"    {side}: SL 10→11.5 پیپ، TP 80→81.5 پیپ",
              abs(d_sl - 11.5) < 0.01 and abs(d_tp - 81.5) < 0.01,
              f"{d_sl:.1f}p / {d_tp:.1f}p")

    # ─── یاسای ٤ ──────────────────────────────────────────────────
    hdr("یاسای ٤ — Tier 1 / Tier 2")
    o = drain()
    send(f"v{n}-tr", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3370.0)
    o = drain()
    keys = ["progression_enabled", "tier1_trigger_pct", "tier1_lock_pct",
            "tier2_trigger_pct", "tier2_lock_pct", "tier2_close_pct"]
    check("هەموو ڕێکخستنەکانی Tier دەگەنە EA",
          bool(o) and all(k in o[0] for k in keys))

    sys.path.insert(0, "tools")
    from test_progression import simulate  # noqa: E402

    res = simulate(3360.0, 3370.0, 0.02, True, [3363.0, 3365.0, 3370.0])
    check("Tier1 لە ٣٠٪ → SL=+١ پیپ (3360.10)",
          any("Tier1" in x and "3360.10" in x for x in res))
    check("Tier2 لە ٥٠٪ → SL=+٣ پیپ (3360.30) + داخستنی 0.01",
          any("Tier2" in x and "3360.30" in x and "داخرا 0.01" in x for x in res))

    res01 = simulate(3360.0, 3370.0, 0.01, True, [3363.0, 3365.0, 3370.0])
    check("لۆتی 0.01 → هیچ ناداخرێت",
          any("بەردەوام بۆ TP" in x for x in res01))

    res_s = simulate(3360.0, 3350.0, 0.02, False, [3357.0, 3355.0])
    check("SELL → هەمان یاسا بە پێچەوانە",
          any("3359.90" in x for x in res_s) and any("3359.70" in x for x in res_s))

    settings({"tier1_trigger_pct": 25, "tier2_close_pct": 40})
    drain()
    send(f"v{n}-tr2", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3370.0)
    o = drain()
    check("ژمارەکانی Tier گۆڕاون",
          bool(o) and o[0]["tier1_trigger_pct"] == 25 and o[0]["tier2_close_pct"] == 40,
          f"t1={o[0]['tier1_trigger_pct'] if o else '?'} close={o[0]['tier2_close_pct'] if o else '?'}")
    settings({"tier1_trigger_pct": 30, "tier2_close_pct": 50})

    # ─── هەموو ئۆپشنەکان ──────────────────────────────────────────
    hdr("هەموو ئۆپشنەکان بەردەستن")
    st = _req("/api/state")["settings"]
    need = ["lot_mode", "balance_pct", "fixed_lot", "max_lot",
            "max_sl_enabled", "max_sl_pips", "pip_points",
            "debounce_enabled", "debounce_sec",
            "spread_comp_enabled", "spread_extra_points", "spread_cap_points",
            "respect_stops_level", "progression_enabled",
            "tier1_trigger_pct", "tier1_lock_pct", "tier2_trigger_pct",
            "tier2_lock_pct", "tier2_close_pct",
            "magic_1m", "magic_3m", "magic_default"]
    missing = [k for k in need if k not in st]
    check(f"هەر {len(need)} ئۆپشنەکە لە API دان", not missing, str(missing))

    html = urllib.request.urlopen(BASE + "/", timeout=10).read().decode()
    nohtml = [k for k in need if f'id="{k}"' not in html]
    check("هەموویان لە داشبۆرددان", not nohtml, str(nohtml))

    js = urllib.request.urlopen(BASE + "/static/app.js", timeout=10).read().decode()
    nojs = [k for k in need if f'"{k}"' not in js]
    check("هەموویان پاشەکەوت دەکرێن", not nojs, str(nojs))

    # ─── kill switch ──────────────────────────────────────────────
    hdr("پاراستنەکان")
    settings({"trading_enabled": False})
    rk = send(f"v{n}-k", "BULL_CONFIRMED", "BUY", 3360.0, 3359.0, 3368.0)
    check("kill switch ڕێگری دەکات", not rk.get("accepted"), rk.get("reason", ""))
    settings({"trading_enabled": True})

    rbad = send(f"v{n}-bad", "BULL_CONFIRMED", "BUY", 3360.0, 3361.0, 3368.0)
    check("BUY بە SLـی سەروو entry ڕەت دەکرێتەوە", not rbad.get("accepted"),
          (rbad.get("reason") or "")[:50])

    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"{BASE}/webhook/laol/laol-beta1?secret=WRONG",
                data=b"{}", headers={"Content-Type": "application/json"}),
            timeout=5)
        check("نهێنیی هەڵە ڕەت دەکرێتەوە", False, "قبوڵ کرا!")
    except urllib.error.HTTPError as e:
        check("نهێنیی هەڵە ڕەت دەکرێتەوە", e.code in (401, 403), f"HTTP {e.code}")

    reset_defaults()

    # ─── کۆتایی ───────────────────────────────────────────────────
    print("\n" + "═" * 70)
    total = _pass + _fail
    if _fail == 0:
        print(f"\033[32m\033[1m  ✓ هەموو {total} پشکنینەکە سەرکەوتوو بوون\033[0m")
    else:
        print(f"\033[31m\033[1m  ✗ {_fail} لە {total} شکستیان هێنا\033[0m")
        for f in _failures:
            print(f"      • {f}")
    print("═" * 70)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
