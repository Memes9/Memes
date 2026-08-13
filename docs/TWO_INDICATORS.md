# بەکارهێنانی دوو ئیندیکەیتەر پێکەوە (BETA 1 + BETA 2.5)

## بیرۆکەکە

هەر ئیندیکەیتەرێک **بەجیا** ئەلێرتی خۆی دەنێرێت بۆ URLـێکی جیاواز.
پردەکە هەموو سیگناڵێک وەردەگرێت و **بەبێ هیچ گۆڕانکارییەک** دەیگوازێتەوە بۆ MT5.

```
BETA 1   ──alert──► /webhook/laol/laol-beta1   ──┐
                                                 ├──► Passthrough ──► MT5
BETA 2.5 ──alert──► /webhook/laol/laol-beta25  ──┘
```

**زۆر گرنگ:** لۆجیکی هیچ کام لە ئیندیکەیتەرەکان دەستکاری ناکرێت.
هەردووکیان لە TradingView دەمێننەوە و هەمان ئەنجامی ئێستایان دەبێت.
پردەکە هیچ سیگناڵێک ڕەت ناکاتەوە و هیچ SL/TPـێک ناگۆڕێت.

## فۆرماتی پەیام — یەکسانە لە هەردووکیان

BETA 2.5 پشکنین کرا: **payloadـەکانی دەقاودەق وەک BETA 1ـن**. هەمان ١٠ سیگناڵ،
هەمان خانەکان. بۆیە **هیچ گۆڕانکارییەک لە کۆدی Pine یان لە adapter پێویست نییە**.

سیگناڵی ترەیدکار (٦ دانە) — `id, signal, action, symbol, tf, entry, sl, tp, tp_alt`:

| signal | action |
|---|---|
| `BULL_FORMING` / `BEAR_FORMING` | BUY / SELL |
| `BULL_CONFIRMED` / `BEAR_CONFIRMED` | BUY / SELL |
| `FINAL_ENTRY_BULL` / `FINAL_ENTRY_BEAR` | BUY / SELL |

سیگناڵی زانیاری (٤ دانە) — تەنها `id, signal, symbol, tf`:
`ENTRY_LAOL_BULL_TAKEN`, `ENTRY_LAOL_BEAR_TAKEN`, `ENTRY_FINAL_BULL_TAKEN`, `ENTRY_FINAL_BEAR_TAKEN`.
بە بنەڕەت ترەید ناکەن (چونکە entry/sl/tp لەگەڵ خۆیان نییە)؛ بە
`laol_trade_info_signals` دەتوانرێت بکرێنەوە.

## ڕێکخستنی ئەلێرت لە TradingView

دوو ئەلێرتی جیاواز دروست بکە:

| ئیندیکەیتەر | URL |
|---|---|
| BETA 1 | `https://<domain>/webhook/laol/laol-beta1?secret=<SECRET>` |
| BETA 2.5 | `https://<domain>/webhook/laol/laol-beta25?secret=<SECRET>` |

- Condition: ئیندیکەیتەرەکە → `Any alert() function call`
- Trigger: **Once Per Bar Close**
- Expiration: دوورترین بەروار
- Message: بەتاڵی بهێڵەوە (Pineـەکە خۆی JSONـەکە دەنێرێت)

بەشی `laol-beta1` / `laol-beta25` تەنها ناوی سەرچاوەیە بۆ جیاکردنەوە لە
داشبۆرد و لۆگەکان. `client_id`ـەکە دەبێتە `laol-beta25-BULL_CONFIRMED-<id>`،
بۆیە ئەگەر هەردوو ئیندیکەیتەر لە هەمان چرکەدا هەمان سیگناڵ بنێرن،
**دوو ئۆردەری جیاواز** دەکرێنەوە — نە یەکێکیان دەفەوتێت نە تێکەڵ دەبن.

## دووبارەنەبوونەوە (idempotency)

ئەگەر TradingView هەمان ئەلێرت دوو جار بنێرێت (هەمان `id` + هەمان سەرچاوە)،
دووەمیان ڕەت دەکرێتەوە بە هۆکاری «ئەم سیگناڵە پێشتر جێبەجێکراوە».
ئەمە فیلتەری ستراتیژی نییە — تەنها پاراستنە لە دووبارەبوونەوەی تەکنیکی.

## جیاوازی BETA 2.5 لە BETA 1 (تەنها لۆجیکی ناوەوە)

ئەمانە لە TradingView ڕوودەدەن، پردەکە هەستیان پێ ناکات:

- `soft_start = true`
- `final_entry_require_hcs = true` — FINAL پێویستی بە HCS هەیە
- `show_intra_lv_aligned` و `show_final_intra_lv` کراونەتەوە
- NX-FIX-3: CONFIRMED و FINAL تەنها یەک جار لە هەر گۆڕانێکدا دەتەقنەوە
- NX-FIX-7: ئەگەر FINAL لە هەمان کاندڵدا بێت، CONFIRMED ناتەقێتەوە
- جۆری FU: BIW یان Classic هەڵبژێردراو
- BETA 2.5 خۆی `strategy()`ـە (pyramiding=20) و هەم `strategy.entry/exit`
  هەم `alert()` دەنێرێت — پردەکە **تەنها** `alert()` بەکاردەهێنێت

## تاقیکردنەوەی ئەنجامدراو

| تاقیکردنەوە | ئەنجام |
|---|---|
| ٦ جۆرەکەی BETA 2.5 بەتەنها | ٦/٦ قبوڵکراو |
| هەمان `id` لە هەردوو سەرچاوەوە | دوو ئۆردەری جیاواز ✓ |
| دووبارەکردنەوەی هەمان سیگناڵ | ڕەتکرایەوە (idempotency) ✓ |
| ٦٠ سیگناڵی تێکەڵ (٣٠+٣٠) بە خێرایی | ٦٠/٦٠ پڕکرا، ٠ ڕەتکرا، ٠ بەسەرچوو |
| SL/TP بەراورد لەگەڵ payload | دەقاودەق یەکسان، هیچ نەگۆڕدرا |
| سنووری پۆزیشن | ٦٠ پۆزیشنی کراوە پێکەوە، هیچ سنوورێک نەخرا |

## هاوڕابوون (Confluence)

مەکینەی هاوڕابوون هێشتا لە کۆدەکەدا ماوە بەڵام لە دۆخی passthroughدا
**کارا نییە** — دەنگەکان تۆمار دەکرێن بەڵام هیچ سیگناڵێک ناخنکێنن.
ئەگەر ڕۆژێک بتەوێت بگەڕێیتەوە بۆ «هەردووکیان دەبێت هاوڕا بن»،
`laol_passthrough` بکەرەوە سەر `false`.
