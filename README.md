# GoldBridge — پردی TradingView ⇄ MetaTrader 5

> **📖 [ڕێنمایی تەواو — لێرەوە دەستپێبکە](docs/ڕێنمایی.md)**
> دامەزراندن، ڕێکخستنی TradingView و MT5، هەموو ئۆپشنەکان،
> تاقیکردنەوە، و چارەسەری کێشەکان.

سیستەمێکی تەواوی ترەیدی ئۆتۆماتیکی بۆ ئاڵتون (XAUUSD)، بەبێ پێویستبوون بە هیچ
خزمەتگوزارییەکی کرێدار (وەک TradersPost، PineConnector، WunderTrading).
لۆجیکی ستراتیژیەکەت لە **TradingView** دەمێنێتەوە (وەک خۆی، بەبێ گۆڕانکاری)، و
تەنها **سیگناڵەکان** دەگوازرێنەوە بۆ MetaTrader 5.

```
TradingView Indicator/Strategy
        │  alert() + Webhook (JSON)
        ▼
   GoldBridge Server (FastAPI)      ← داشبۆردی وێب لێرەیە
        │  risk engine + queue + database
        ▼
   GoldBridge EA (MQL5)  →  MetaTrader 5  →  بڕۆکەرەکەت
        │  ڕاپۆرتی جێبەجێکردن + دۆخی هەژمار
        └──────────────► گەڕانەوە بۆ داشبۆرد
```

## تایبەتمەندییەکان

- **وەرگرتنی وێبهۆک** لە TradingView بە پارێزراوی (shared secret)
- **بەڕێوەبردنی مەترسی** پێش هەر ترەیدێک: ڕێژەی مەترسی، زۆرترین لۆت،
  زۆرترین پۆزیشن، زۆرترین زیانی ڕۆژانە، drawdown، فیلتەری سپرێد و سێشن
- **Idempotency** — هەمان سیگناڵ دوو جار ترەید ناکات
- **بەسەرچوونی سیگناڵ** — سیگناڵی کۆنتر لە ٦٠ چرکە جێبەجێ ناکرێت
- **Kill switch / PANIC** — یەک کلیک: هەموو پۆزیشنەکان دادەخرێن
- **داشبۆردی کوردی** — باڵانس، ئیکویتی، پۆزیشنەکان، مێژووی ترەید، ئامارەکان، لۆگ
- **ترەیدی دەستی** لە ڕووکارەکەوە
- **قەبارەی لۆت بە دوو مۆد** — لۆتی جێگیر، یان ڕێژەی سەدی باڵانس
  (١٪ی باڵانس = 0.01 لۆت، بەبێ گوێدان بە SL)
- **Trailing stop** و **break-even** لە ناو EA

### دوو ئیندیکەیتەر پێکەوە (BETA 1 + BETA 2.5)

- هەردووکیان بە **passthrough** کاردەکەن — هەموو سیگناڵێک دەبێتە ئۆردەر
- SL/TP **دەقاودەق** لە ئیندیکەیتەرەکەوە، بەبێ گۆڕانکاری
- **Magic Number جیاواز بۆ هەر تایمفرەیمێک** (١m=990001، ٣m=990003) —
  SL/TP ی لەیئاوتەکان هەرگیز تێکەڵ نابن
- **قەرەبووکردنەوەی سپرێد** — سپرێدی ئەو ساتە دەخرێتە سەر SL و TP
- **فیلتەری زۆرترین SL** — سیگناڵی SL گەورە ڕەت دەکرێتەوە پێش MT5
- **١ سیگناڵ = ١ ئۆردەر** (debounce)
- **Tier 1 / Tier 2** — لە ٣٠٪ی TP: SL بۆ +١٪ • لە ٥٠٪: SL بۆ +٣٪ و
  داخستنی ٥٠٪ی لۆت، بەشی ماوە بەردەوام بۆ TPی تەواو
- **هەموو ژمارەکان گۆڕاون** لە داشبۆردەوە، بەبێ کۆمپایلکردنەوەی EA

وردەکاری تەواو لە [`docs/LAOL_SETUP.md`](docs/LAOL_SETUP.md).

### تاقیکردنەوە

```bash
.venv/bin/python3 tools/verify_all.py        # ٣٥ پشکنین بەرامبەر سێرڤەری کارکەر
.venv/bin/python3 tools/test_progression.py  # سیمولەیشنی Tier 1/2 بەبێ MT5
```

## دامەزراندن

### ١. سێرڤەر

```bash
git clone <this-repo> && cd Memes
cp .env.example .env      # نهێنییەکان بگۆڕە!
./run.sh                  # http://0.0.0.0:8000
```

بۆ تاقیکردنەوە بەبێ MetaTrader:

```bash
.venv/bin/python tools/mock_mt5_client.py
```

### ٢. TradingView

1. کۆدی `pine/alert_template.pine` بخە ناو ئیندیکەیتەرەکەتەوە
   (تەنها بەشی `f_msg` و `alert()`).
2. Alert دروست بکە → Condition = ئیندیکەیتەرەکەت → *Any alert() function call*.
3. لە Notifications دا Webhook URL دابنێ:
   `https://your-domain.com/webhook/tradingview`
4. Trigger = **Once Per Bar Close** (بۆ نەبوونی repaint).

> **تێبینی:** وێبهۆک تەنها لە پلانی **Essential** بەرەوژوور بەردەستە و
> پێویستی بە HTTPS ی گشتی هەیە (TradingView ناچێتە سەر `localhost`).

### ٣. MetaTrader 5

1. فایلی `mt5/GoldBridgeEA.mq5` کۆپی بکە بۆ `MQL5/Experts/`.
2. لە MetaEditor دا کۆمپایلی بکە (F7).
3. **Tools → Options → Expert Advisors → Allow WebRequest for listed URL**
   → ناونیشانی سێرڤەرەکەت زیاد بکە (نموونە `https://your-domain.com`).
4. EA بخە سەر چارتی XAUUSD و `ServerURL` + `EAToken` ڕێک بخە.
5. دڵنیابە **AutoTrading** کارایە.

## APIـەکان

| Method | Route | کار |
|---|---|---|
| POST | `/webhook/tradingview` | وەرگرتنی سیگناڵ لە TradingView |
| GET  | `/api/orders/next?token=` | EA فەرمانی داهاتوو وەردەگرێت |
| POST | `/api/orders/report` | ڕاپۆرتی جێبەجێکردن |
| POST | `/api/account/report` | heartbeat ی هەژمار |
| POST | `/api/trades/closed` | ترەیدی داخراو |
| GET  | `/api/state` | هەموو دۆخی سیستەم (داشبۆرد) |
| POST | `/api/settings` | نوێکردنەوەی ڕێکخستنەکان |
| POST | `/api/panic` | ڕاگرتنی خێرا |
| POST | `/api/manual-order` | ترەیدی دەستی |

## نموونەی پەیامی وێبهۆک

```json
{
  "secret": "your-secret",
  "action": "buy",
  "symbol": "XAUUSD",
  "price": 3350.25,
  "sl": 3340.00,
  "tp": 3380.00,
  "risk_pct": 0.5,
  "strategy": "gold-v1",
  "signal_id": "gold-v1-1699999999-buy",
  "time": "2026-08-13T12:00:00Z"
}
```

`action` دەتوانێت `buy`, `sell`, `close`, `close_all` بێت.

## پێویستییەکانی بەرهەمهێنان (production)

- **VPS** نزیک لە سێرڤەری بڕۆکەرەکەت (لەندەن/نیویۆرک) — MT5 و سێرڤەرەکە پێکەوە.
- **HTTPS** بە Caddy یان Nginx + Let's Encrypt (TradingView تەنها HTTPS قبوڵ دەکات).
- IP ـەکانی TradingView تەنها ڕێگەپێبدە لە فایەرواڵ:
  `52.89.214.238`, `34.212.75.30`, `54.218.53.128`, `52.32.178.7`.
- **هەمیشە یەکەم جار لەسەر هەژماری Demo تاقی بکەرەوە.**

## ئاگاداری

ئەم کۆدە بۆ مەبەستی فێربوون و ئۆتۆماتیککردنی کەسییە. ترەیدینگ مەترسیدارە و
لەوانەیە هەموو سەرمایەکەت لەدەست بدەیت. هیچ گرەنتییەک نییە.

---

## ئیندیکەیتەرەکانی LAOL

ئیندیکەیتەرەکانی BETA 1 / BETA 2.5 پێشتر `alert()` ی JSON یان تێدایە،
بۆیە **هیچ گۆڕانکارییەک لە Pine پێویست نییە**. تەنها ئەم URL بەکاربهێنە:

```
https://your-server.com/webhook/laol/laol-beta1?secret=YOUR_SECRET
https://your-server.com/webhook/laol/laol-beta25?secret=YOUR_SECRET
```

وردەکاری تەواو لە `docs/LAOL_SETUP.md`.
