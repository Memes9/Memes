"""سیمولەیشنی یاسای ٤ — Tier 1 / Tier 2 بەبێ پێویستی بە MT5.

هەمان ژمێرکاریی ManageOpenPositions() لە GoldBridgeEA.mq5 دووبارە دەکاتەوە
تاکو بتوانرێت پێش دانانی EA لەسەر هەژماری ڕاستەقینە تاقی بکرێتەوە.
"""
from __future__ import annotations

T1_TRIGGER, T1_LOCK = 30.0, 1.0
T2_TRIGGER, T2_LOCK, T2_CLOSE = 50.0, 3.0, 50.0

VOL_MIN, VOL_STEP = 0.01, 0.01


def simulate(entry: float, tp: float, lot: float, is_buy: bool,
             path: list[float], point: float = 0.01) -> list[str]:
    """بەسەر ڕێڕەوی نرخدا دەڕوات و کردارەکان دەگەڕێنێتەوە."""
    tp_dist = abs(tp - entry)
    sl = None
    vol = lot
    done = 0
    out: list[str] = []

    for price in path:
        moved = (price - entry) if is_buy else (entry - price)
        pct = moved / tp_dist * 100.0
        if pct <= 0:
            continue

        # Tier 2 پێشەنگە
        if pct >= T2_TRIGGER and done < 2:
            lock = tp_dist * T2_LOCK / 100.0
            sl = entry + lock if is_buy else entry - lock
            want = vol * T2_CLOSE / 100.0
            part = round((want // VOL_STEP) * VOL_STEP, 2)
            if part >= VOL_MIN and round(vol - part, 2) >= VOL_MIN:
                vol = round(vol - part, 2)
                out.append(f"Tier2 @{pct:5.1f}%  SL→+{T2_LOCK}% ({sl:.2f})  "
                           f"داخرا {part:.2f}  ماوە {vol:.2f}")
            else:
                out.append(f"Tier2 @{pct:5.1f}%  SL→+{T2_LOCK}% ({sl:.2f})  "
                           f"لۆت={vol:.2f} بچووکە — بەردەوام بۆ TP")
            done = 2
            continue

        if pct >= T1_TRIGGER and done < 1:
            lock = tp_dist * T1_LOCK / 100.0
            sl = entry + lock if is_buy else entry - lock
            out.append(f"Tier1 @{pct:5.1f}%  SL→+{T1_LOCK}% ({sl:.2f})  لۆت {vol:.2f}")
            done = 1

    return out


def _hdr(t: str) -> None:
    print(f"\n{'=' * 68}\n{t}\n{'=' * 68}")


if __name__ == "__main__":
    _hdr("نموونەی خودی ترەیدەر: TP=100 پیپ، لۆت=0.02، BUY")
    entry, tp = 3360.00, 3370.00          # 100 پیپ = 10.00$
    print(f"entry={entry}  tp={tp}  (دووری {abs(tp-entry)*10:.0f} پیپ)")
    for line in simulate(entry, tp, 0.02, True,
                         [3361.0, 3363.0, 3365.0, 3368.0, 3370.0]):
        print("  " + line)
    print("  چاوەڕوانکراو: Tier1 لە 30 پیپ (SL=+1 پیپ)، "
          "Tier2 لە 50 پیپ (SL=+3 پیپ، 0.01 دادەخرێت)")

    _hdr("لۆتی 0.01 — نابێت هیچ دابخرێت")
    for line in simulate(entry, tp, 0.01, True, [3363.0, 3365.0, 3370.0]):
        print("  " + line)

    _hdr("SELL — هەمان یاسا بە پێچەوانە")
    for line in simulate(3360.00, 3350.00, 0.02, False,
                         [3357.0, 3355.0, 3350.0]):
        print("  " + line)

    _hdr("TPـی جیاواز — ڕێژەکان هەمیشە هەمان")
    print(f"{'TP پیپ':>9}{'Tier1 لە':>11}{'SL':>9}{'Tier2 لە':>11}{'SL':>9}")
    print("-" * 50)
    for tp_pips in (50, 100, 250, 800):
        d = tp_pips * 0.10
        print(f"{tp_pips:>9}{tp_pips*0.30:>10.1f}p{tp_pips*0.01:>8.1f}p"
              f"{tp_pips*0.50:>10.1f}p{tp_pips*0.03:>8.1f}p")

    _hdr("لۆتە گەورەکان — داخستنی نیوە بۆ VOLUME_STEP ڕێک دەخرێت")
    for lot in (0.02, 0.05, 0.43, 1.07):
        want = lot * 0.5
        part = round((want // VOL_STEP) * VOL_STEP, 2)
        rest = round(lot - part, 2)
        ok = part >= VOL_MIN and rest >= VOL_MIN
        print(f"  لۆت={lot:>5.2f} → دادەخرێت {part:>5.2f}  دەمێنێتەوە {rest:>5.2f}"
              f"  {'✓' if ok else '✗ بەردەوام بۆ TP'}")
