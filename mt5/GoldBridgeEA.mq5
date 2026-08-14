//+------------------------------------------------------------------+
//|                                                 GoldBridgeEA.mq5 |
//|   پردی MetaTrader 5 بۆ GoldBridge — فەرمانەکان لە سێرڤەرەوە      |
//|   وەردەگرێت و جێبەجێیان دەکات (بەبێ هیچ خزمەتگوزارییەکی کرێدار)  |
//|                                                                  |
//|   گرنگ: Tools > Options > Expert Advisors > Allow WebRequest     |
//|          for listed URL  ->  ناونیشانی سێرڤەرەکەت زیاد بکە       |
//+------------------------------------------------------------------+
#property copyright "GoldBridge"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- inputs -------------------------------------------------------
input string  ServerURL      = "http://127.0.0.1:8000"; // ناونیشانی سێرڤەر
input string  EAToken        = "change-me-ea-token";    // EA_TOKEN
input int     PollMs         = 1500;                    // ماوەی پرسیارکردن (میلی چرکە)
input int     HeartbeatSec   = 5;                       // ناردنی دۆخی هەژمار
input long    MagicNumber    = 990011;   // بنەڕەت — ئەگەر سیگناڵ خۆی magic نەنێرێت
input bool    UseSignalMagic = true;     // magicـی سیگناڵ بەکاربهێنە (جیاکردنەوەی 1m/3m)
input int     SlippagePoints = 30;
input bool    EnableTrading  = true;                    // کلیلی ناوخۆیی
input bool    PassthroughMode = true;                   // SL/TP سەرەتایی وەک خۆی لە سیگناڵەوە

//--- سەرچاوەی ڕێکخستنەکان ------------------------------------------
// true  = ژمارەکان لە داشبۆردەوە دێن (لە یەک شوێنەوە بەڕێوە دەبرێن)
// false = ژمارەکانی خوارەوەی ئەم EA ـە بەکاردێن
input bool    UseServerSettings = true;  // ڕێکخستن لە داشبۆردەوە وەربگرە

//--- قەرەبووکردنەوەی سپرێد -----------------------------------------
input bool    SpreadComp     = true;   // سپرێد بخە سەر SL و TP
input double  SpreadExtraPts = 0;      // پۆینتی زیادە لەسەر سپرێد (بەتاڵ = تەنها سپرێد)
input double  SpreadCapPts   = 0;      // زۆرترین سپرێد کە زیاد دەکرێت (0 = بێ سنوور)
input bool    RespectStopsLevel = true; // ئەگەر SL/TP زۆر نزیک بوو، بیپاڵێوە دەرەوە

//--- مەکینەی مەترسی (یاسای ٣) --------------------------------------
input bool    RiskOnBalance  = true;   // مەترسی لەسەر باڵانس (نەک ئیکویتی)

//--- قەبارەی لۆت ---------------------------------------------------
enum ENUM_LOT_MODE
  {
   LOT_FIXED   = 0,  // لۆتی جێگیر
   LOT_PERCENT = 1,  // ڕێژەی سەدی باڵانس (١٪ = 0.01 لۆت)
   LOT_SERVER  = 2   // ئەوەی سێرڤەر دەیڵێت
  };
input ENUM_LOT_MODE LotMode    = LOT_SERVER;  // مۆدی قەبارە
input double  FixedLot        = 0.01;   // مۆدی جێگیر
input double  BalancePercent  = 1.0;    // مۆدی ڕێژەیی: ١٪ی باڵانس = 0.01 لۆت
input double  MaxLotCap       = 0;      // زۆرترین لۆت (0 = بێ سنوور)

//--- بەڕێوەبردنی مامەڵە (یاسای ٤) ----------------------------------
input bool    ProgressionOn   = true;   // Tier 1 + Tier 2 چالاک بێت
input double  Tier1TriggerPct = 30.0;   // لە چەند ٪ی TP دەست پێ بکات
input double  Tier1LockPct    = 1.0;    // SL بخرێتە چەند ٪ی TP قازانج
input double  Tier2TriggerPct = 50.0;   // لە چەند ٪ی TP
input double  Tier2LockPct    = 3.0;    // SL بخرێتە چەند ٪ی TP قازانج
input double  Tier2ClosePct   = 50.0;   // چەند ٪ی لۆت دابخرێت

//--- پێشوەختە ڕاگەیاندن (MQL5 پێویستی پێیەتی پێش بەکارهێنان)
bool PollOrder();
void ManageOpenPositions();
void SendAccountReport();
void CloseAll();
void ClosePositionsOn(string symbol);
void Report(string clientId, string status, long ticket, double fillPrice, string err);
string ResolveSymbol(string want);
double LotByBalancePercent(double pct);
bool IsOurMagic(long m);
bool IsSameLayout(long m, long want);
void CloseOppositePositions(string symbol, bool wantBuy, long layoutMagic);
bool MoveSlForward(ulong ticket, string sym, double newSl, double tp,
                   bool isBuy, double point, string tag);
bool IsTierDone(ulong ticket, int tier);
void MarkTierDone(ulong ticket, int tier);
void PruneTierMemory();
double NormalizePrice(string symbol, double price);
double NormalizeVolume(string symbol, double vol);

//--- ڕێکخستنە کارپێکراوەکان (لە سێرڤەر یان لە inputەکانەوە) ---------
bool   g_spreadComp;
double g_spreadExtra, g_spreadCap;
bool   g_respectStops;
bool   g_progressionOn;
double g_t1Trigger, g_t1Lock, g_t2Trigger, g_t2Lock, g_t2Close;

//--- دانانی بەهای بنەڕەت لە inputەکانەوە
void ResetEffectiveSettings()
  {
   g_spreadComp    = SpreadComp;
   g_spreadExtra   = SpreadExtraPts;
   g_spreadCap     = SpreadCapPts;
   g_respectStops  = RespectStopsLevel;
   g_progressionOn = ProgressionOn;
   g_t1Trigger     = Tier1TriggerPct;
   g_t1Lock        = Tier1LockPct;
   g_t2Trigger     = Tier2TriggerPct;
   g_t2Lock        = Tier2LockPct;
   g_t2Close       = Tier2ClosePct;
  }

CTrade         trade;
CPositionInfo  pos;
datetime       lastHeartbeat = 0;
int            lastPollTick  = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   ResetEffectiveSettings();   // بەهای بنەڕەت پێش یەکەم پەیوەندی
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(SlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   EventSetMillisecondTimer(PollMs);
   Print("GoldBridge EA started -> ", ServerURL);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
void OnTimer()
  {
   if(TimeCurrent() - lastHeartbeat >= HeartbeatSec)
     {
      SendAccountReport();
      lastHeartbeat = TimeCurrent();
      PruneTierMemory();   // پاککردنەوەی تیکێتە داخراوەکان
     }
   ManageOpenPositions();

   // لە مۆدی passthrough دا ڕەنگە چەند سیگناڵێک پێکەوە بێن.
   // تا ١٠ فەرمان لە هەر سووڕێکدا جێبەجێ دەکەین تا هیچیان دوا نەکەوێت.
   for(int k = 0; k < 10; k++)
      if(!PollOrder())
         break;
  }

//+------------------------------------------------------------------+
//| HTTP helpers                                                     |
//+------------------------------------------------------------------+
string HttpGet(string url)
  {
   char post[], result[];
   string headers = "";
   int timeout = 5000;
   ResetLastError();
   int code = WebRequest("GET", url, headers, timeout, post, result, headers);
   if(code == -1) { Print("WebRequest GET error ", GetLastError(), " url=", url); return ""; }
   return CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
  }

string HttpPost(string url, string body)
  {
   char post[], result[];
   string headers = "Content-Type: application/json\r\n";
   StringToCharArray(body, post, 0, StringLen(body), CP_UTF8);
   ArrayResize(post, StringLen(body)); // بێ NULL ی کۆتایی
   int timeout = 5000;
   ResetLastError();
   int code = WebRequest("POST", url, headers, timeout, post, result, headers);
   if(code == -1) { Print("WebRequest POST error ", GetLastError(), " url=", url); return ""; }
   return CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
  }

//--- خوێندنەوەی سادەی JSON (بەبێ کتێبخانەی دەرەکی) ----------------
string JsonStr(string json, string key)
  {
   string pat = "\"" + key + "\":";
   int p = StringFind(json, pat);
   if(p < 0) return "";
   p += StringLen(pat);
   while(p < StringLen(json) && StringGetCharacter(json, p) == ' ') p++;
   if(StringGetCharacter(json, p) == '"')
     {
      p++;
      int e = StringFind(json, "\"", p);
      return StringSubstr(json, p, e - p);
     }
   int e2 = p;
   while(e2 < StringLen(json))
     {
      ushort c = StringGetCharacter(json, e2);
      if(c == ',' || c == '}' || c == ']') break;
      e2++;
     }
   string v = StringSubstr(json, p, e2 - p);
   StringTrimLeft(v); StringTrimRight(v);
   return v;
  }

double JsonNum(string json, string key) { return StringToDouble(JsonStr(json, key)); }
bool   JsonBool(string json, string key) { string v = JsonStr(json, key); return (v == "true" || v == "1"); }
bool   JsonHas(string json, string key)  { return (StringFind(json, "\"" + key + "\"") >= 0); }

//+------------------------------------------------------------------+
//| وەرگرتنی فەرمانی داهاتوو                                          |
//+------------------------------------------------------------------+
bool PollOrder()
  {
   string resp = HttpGet(ServerURL + "/api/orders/next?token=" + EAToken);
   if(resp == "" || StringFind(resp, "\"has_order\":true") < 0) return false;

   string clientId  = JsonStr(resp, "client_id");
   string action    = JsonStr(resp, "action");
   string symbolIn  = JsonStr(resp, "symbol");
   double volume    = JsonNum(resp, "volume");
   double sl        = JsonNum(resp, "sl");
   double tp        = JsonNum(resp, "tp");
   double riskPct   = JsonNum(resp, "risk_pct");
   double maxLot    = JsonNum(resp, "max_lot");
   double maxSpread = JsonNum(resp, "max_spread_points");
   bool   allowRev  = JsonBool(resp, "allow_reverse");
   double defSlPts  = JsonNum(resp, "default_sl_points");
   double defTpPts  = JsonNum(resp, "default_tp_points");
   long   sigMagic  = (long)JsonNum(resp, "magic");
   string sigTf     = JsonStr(resp, "tf");
   string srvLotMode = JsonStr(resp, "lot_mode");
   double srvBalPct  = JsonNum(resp, "balance_pct");

   //--- ڕێکخستنەکان لە داشبۆردەوە (ئەگەر ڕێگەپێدراو بێت)
   ResetEffectiveSettings();
   if(UseServerSettings)
     {
      if(JsonHas(resp, "spread_comp_enabled"))
        {
         g_spreadComp   = JsonBool(resp, "spread_comp_enabled");
         g_spreadExtra  = JsonNum(resp, "spread_extra_points");
         g_spreadCap    = JsonNum(resp, "spread_cap_points");
         g_respectStops = JsonBool(resp, "respect_stops_level");
        }
      if(JsonHas(resp, "progression_enabled"))
        {
         g_progressionOn = JsonBool(resp, "progression_enabled");
         g_t1Trigger     = JsonNum(resp, "tier1_trigger_pct");
         g_t1Lock        = JsonNum(resp, "tier1_lock_pct");
         g_t2Trigger     = JsonNum(resp, "tier2_trigger_pct");
         g_t2Lock        = JsonNum(resp, "tier2_lock_pct");
         g_t2Close       = JsonNum(resp, "tier2_close_pct");
        }
     }

   //--- جیاکردنەوەی لەیئاوتەکان: هەر تایمفرەیمێک magicـی خۆی
   long useMagic = (UseSignalMagic && sigMagic > 0) ? sigMagic : MagicNumber;
   trade.SetExpertMagicNumber(useMagic);

   string symbol = ResolveSymbol(symbolIn);

   if(!EnableTrading)
     { Report(clientId, "failed", 0, 0, "EA locally disabled"); return true; }

   if(action == "close_all")
     { CloseAll(); Report(clientId, "filled", 0, 0, ""); return true; }

   if(action == "close")
     { ClosePositionsOn(symbol); Report(clientId, "filled", 0, 0, ""); return true; }

   if(symbol == "")
     { Report(clientId, "failed", 0, 0, "symbol not found: " + symbolIn); return true; }

   //--- فیلتەری سپرێد
   double spread = (double)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   if(maxSpread > 0 && spread > maxSpread)
     { Report(clientId, "failed", 0, 0, StringFormat("spread too high %.0f", spread)); return true; }

   bool isBuy = (action == "buy");
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double ask   = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double bid   = SymbolInfoDouble(symbol, SYMBOL_BID);
   double entry = isBuy ? ask : bid;

   //--- SL/TP ی بنەڕەت ئەگەر سیگناڵ نەیناردبوو
   if(sl <= 0 && defSlPts > 0) sl = isBuy ? entry - defSlPts * point : entry + defSlPts * point;
   if(tp <= 0 && defTpPts > 0) tp = isBuy ? entry + defTpPts * point : entry - defTpPts * point;

   //--- قەرەبووی سپرێد: هەمان بڕ دەخرێتە سەر SL و TP، ڕێژەی R:R نەگۆڕ دەمێنێتەوە
   double compPts = 0;
   if(g_spreadComp)
     {
      compPts = spread + g_spreadExtra;
      if(g_spreadCap > 0 && compPts > g_spreadCap) compPts = g_spreadCap;
      if(compPts < 0) compPts = 0;
      double comp = compPts * point;
      if(sl > 0) sl = isBuy ? sl - comp : sl + comp;
      if(tp > 0) tp = isBuy ? tp + comp : tp - comp;
     }

   //--- کەمترین دووری ڕێپێدراوی بڕۆکەر (پاراستنی تەکنیکی، نەک فیلتەری ستراتیژی)
   if(g_respectStops)
     {
      double minDist = (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
      if(minDist > 0)
        {
         if(sl > 0)
           {
            if(isBuy  && entry - sl < minDist) sl = entry - minDist;
            if(!isBuy && sl - entry < minDist) sl = entry + minDist;
           }
         if(tp > 0)
           {
            if(isBuy  && tp - entry < minDist) tp = entry + minDist;
            if(!isBuy && entry - tp < minDist) tp = entry - minDist;
           }
        }
     }

   //--- قەبارەی لۆت
   //    ئەگەر EA بە LOT_SERVER بێت، ئەوەی سێرڤەر دەیڵێت جێبەجێ دەکرێت،
   //    بەپێچەوانەوە ڕێکخستنی خودی EA پێشەنگە.
   double slDist  = MathAbs(entry - sl);
   string lotNote = "";
   if(volume <= 0)
     {
      ENUM_LOT_MODE mode = LotMode;
      double pct = BalancePercent;
      if(mode == LOT_SERVER)
        {
         mode = (srvLotMode == "fixed") ? LOT_FIXED : LOT_PERCENT;
         if(srvBalPct > 0) pct = srvBalPct;
        }

      if(mode == LOT_FIXED)
        {
         volume  = FixedLot;
         lotNote = StringFormat("جێگیر=%.2f", FixedLot);
        }
      else
        {
         volume  = LotByBalancePercent(pct);
         lotNote = StringFormat("%.1f%%ی باڵانس(%.0f$)", pct, AccountInfoDouble(ACCOUNT_BALANCE));
        }

      if(volume <= 0)
        {
         volume  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
         lotNote = "کەمترین";
        }
     }
   else lotNote = "لە سیگناڵەوە";

   double lotCap = MaxLotCap > 0 ? MaxLotCap : maxLot;
   if(lotCap > 0 && volume > lotCap) volume = lotCap;
   volume = NormalizeVolume(symbol, volume);
   if(volume <= 0)
     { Report(clientId, "failed", 0, 0, "invalid volume"); return true; }

   //--- پێچەوانەکردن
   if(allowRev) CloseOppositePositions(symbol, isBuy, useMagic);

   int dg = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   PrintFormat("%s %s tf%s magic=%d | سپرێد=%.0fp+%.0fp | SL=%.*f TP=%.*f | دووری=%.1fp | لۆت=%.2f (%s)",
               clientId, symbol, sigTf, useMagic, spread, compPts,
               dg, sl, dg, tp, slDist / point, volume, lotNote);

   bool ok = isBuy ? trade.Buy(volume, symbol, 0.0, NormalizePrice(symbol, sl), NormalizePrice(symbol, tp), clientId)
                   : trade.Sell(volume, symbol, 0.0, NormalizePrice(symbol, sl), NormalizePrice(symbol, tp), clientId);

   if(ok && trade.ResultRetcode() == TRADE_RETCODE_DONE)
      Report(clientId, "filled", (long)trade.ResultOrder(), trade.ResultPrice(), "");
   else
      Report(clientId, "failed", 0, 0, StringFormat("%d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription()));

   return true;
  }

//+------------------------------------------------------------------+
//| دۆزینەوەی سیمبولی دروست (XAUUSD.m, GOLD, ...)                    |
//+------------------------------------------------------------------+
string ResolveSymbol(string want)
  {
   if(want == "" || want == "ALL") return _Symbol;
   if(SymbolSelect(want, true) && SymbolInfoDouble(want, SYMBOL_BID) > 0) return want;
   for(int i = 0; i < SymbolsTotal(false); i++)
     {
      string s = SymbolName(i, false);
      if(StringFind(s, want) == 0) { SymbolSelect(s, true); return s; }
     }
   return _Symbol; // پاشەکەوت: چارتی ئێستا
  }

double NormalizePrice(string symbol, double price)
  {
   if(price <= 0) return 0;
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   return NormalizeDouble(price, digits);
  }

double NormalizeVolume(string symbol, double vol)
  {
   double mn = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(st <= 0) st = 0.01;
   vol = MathFloor(vol / st) * st;
   vol = MathMax(mn, MathMin(mx, vol));
   return NormalizeDouble(vol, 2);
  }

//--- قەبارە بەپێی ڕێژەی مەترسی لە ئیکویتی --------------------------
//+------------------------------------------------------------------+
//| قەبارە بەپێی ڕێژەی سەدی باڵانس                                   |
//| هەر ١٪ی باڵانس = 0.01 لۆت. دووری SL هیچ ڕۆڵێکی نییە.            |
//|   100$ balance @ 1%  → 0.01 لۆت                                  |
//|   200$ balance @ 1%  → 0.02 لۆت                                  |
//|   200$ balance @ 2%  → 0.04 لۆت                                  |
//+------------------------------------------------------------------+
double LotByBalancePercent(double pct)
  {
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   if(bal <= 0 || pct <= 0) return 0;
   return (bal / 100.0) * 0.01 * pct;
  }

double LotByRisk(string symbol, double riskPct, double slDistance)
  {
   if(slDistance <= 0) return 0;
   // یاسای ٣: مەترسی لەسەر باڵانسی ئێستا (نەک ئیکویتی) دەژمێردرێت
   double base     = RiskOnBalance ? AccountInfoDouble(ACCOUNT_BALANCE)
                                   : AccountInfoDouble(ACCOUNT_EQUITY);
   double riskCash = base * riskPct / 100.0;
   double tickVal  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0) return 0;
   double lossPerLot = (slDistance / tickSize) * tickVal;
   if(lossPerLot <= 0) return 0;
   return riskCash / lossPerLot;
  }

//+------------------------------------------------------------------+
//| بەڕێوەبردنی پۆزیشنەکان: break-even + trailing                    |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| یاسای ٤ — بەڕێوەبردنی داینامیکی مامەڵە                           |
//|                                                                  |
//|  هەموو ژمارەکان ڕێژەیین لە دووری TP ەوە — گرنگ نییە ٥٠ پیپ بێت  |
//|  یان ٢٥٠ پیپ.                                                    |
//|                                                                  |
//|  Tier 1 — لە ٣٠٪ی TP:  SL → +١٪ی TP قازانج                      |
//|  Tier 2 — لە ٥٠٪ی TP:  SL → +٣٪ی TP قازانج                      |
//|                        + داخستنی ٥٠٪ی لۆت                        |
//|                        + بەشی ماوە بەردەوام بۆ TP ی تەواو        |
//|                                                                  |
//|  ئەگەر لۆت = کەمترینی بڕۆکەر بێت (0.01)، نیوە ناکرێت —          |
//|  تەنها SL دەگۆڕدرێت و پۆزیشنەکە بەردەوام دەبێت.                 |
//+------------------------------------------------------------------+
void ManageOpenPositions()
  {
   if(!g_progressionOn) return;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!pos.SelectByIndex(i)) continue;
      if(!IsOurMagic(pos.Magic())) continue;

      string sym   = pos.Symbol();
      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      double openP = pos.PriceOpen();
      double cur   = pos.PriceCurrent();
      double sl    = pos.StopLoss();
      double tp    = pos.TakeProfit();
      bool   isBuy = (pos.PositionType() == POSITION_TYPE_BUY);
      ulong  tk    = pos.Ticket();

      // بەبێ TP ڕێژەکان بێواتان
      if(tp <= 0) continue;

      double tpDist = MathAbs(tp - openP);
      if(tpDist <= 0) continue;

      // چەند لە ڕێگاکە بڕیوە؟
      double moved = isBuy ? (cur - openP) : (openP - cur);
      double pctDone = moved / tpDist * 100.0;
      if(pctDone <= 0) continue;

      //--- Tier 2 (سەرەتا دەپشکنرێت — پێشەنگە بەسەر Tier 1)
      if(pctDone >= g_t2Trigger && !IsTierDone(tk, 2))
        {
         double lockDist = tpDist * g_t2Lock / 100.0;
         double newSl = isBuy ? openP + lockDist : openP - lockDist;
         MoveSlForward(tk, sym, newSl, tp, isBuy, point, "Tier2");

         // داخستنی ڕێژەیەک لە لۆتەکە
         double vol  = pos.Volume();
         double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
         double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
         if(step <= 0) step = 0.01;

         double want = vol * g_t2Close / 100.0;
         double part = MathFloor(want / step) * step;
         part = NormalizeDouble(part, 2);

         // دەبێت هەم بەشی داخراو هەم بەشی ماوە لە کەمترین کەمتر نەبن
         if(part >= vmin && (vol - part) >= vmin)
           {
            if(trade.PositionClosePartial(tk, part))
               PrintFormat("Tier2 #%d %s | %.1f%%ی TP | داخرا %.2f لە %.2f | ماوە %.2f | SL→+%.1f%%",
                           tk, sym, pctDone, part, vol, vol - part, g_t2Lock);
            else
               PrintFormat("Tier2 #%d داخستنی بەشەکی سەرکەوتوو نەبوو: %d %s",
                           tk, trade.ResultRetcode(), trade.ResultRetcodeDescription());
           }
         else
           {
            PrintFormat("Tier2 #%d %s | %.1f%%ی TP | لۆت=%.2f بچووکە بۆ داخستنی نیوە — بەردەوام بۆ TP | SL→+%.1f%%",
                        tk, sym, pctDone, vol, g_t2Lock);
           }

         MarkTierDone(tk, 2);
         continue;
        }

      //--- Tier 1
      if(pctDone >= g_t1Trigger && !IsTierDone(tk, 1))
        {
         double lockDist = tpDist * g_t1Lock / 100.0;
         double newSl = isBuy ? openP + lockDist : openP - lockDist;
         if(MoveSlForward(tk, sym, newSl, tp, isBuy, point, "Tier1"))
            PrintFormat("Tier1 #%d %s | %.1f%%ی TP | SL→+%.1f%% (%.*f)",
                        tk, sym, pctDone, g_t1Lock,
                        (int)SymbolInfoInteger(sym, SYMBOL_DIGITS), newSl);
         MarkTierDone(tk, 1);
        }
     }
  }

//+------------------------------------------------------------------+
//| جوڵاندنی SL — تەنها بەرەو پێشەوە، هەرگیز بەرەو دواوە             |
//+------------------------------------------------------------------+
bool MoveSlForward(ulong ticket, string sym, double newSl, double tp,
                   bool isBuy, double point, string tag)
  {
   newSl = NormalizePrice(sym, newSl);

   // ڕێزگرتن لە کەمترین دووری بڕۆکەر
   double minDist = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * point;
   double cur = isBuy ? SymbolInfoDouble(sym, SYMBOL_BID) : SymbolInfoDouble(sym, SYMBOL_ASK);
   if(minDist > 0)
     {
      if(isBuy  && cur - newSl < minDist) newSl = NormalizePrice(sym, cur - minDist);
      if(!isBuy && newSl - cur < minDist) newSl = NormalizePrice(sym, cur + minDist);
     }

   if(!pos.SelectByTicket(ticket)) return false;
   double oldSl = pos.StopLoss();

   // تەنها ئەگەر باشتر بێت
   bool better = isBuy ? (oldSl == 0 || newSl > oldSl + point / 2)
                       : (oldSl == 0 || newSl < oldSl - point / 2);
   if(!better) return false;

   if(trade.PositionModify(ticket, newSl, tp)) return true;

   PrintFormat("%s #%d گۆڕینی SL سەرکەوتوو نەبوو: %d %s",
               tag, ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
   return false;
  }

//+------------------------------------------------------------------+
//| تۆمارکردنی ئەوەی کام قۆناغ بۆ کام تیکێت جێبەجێ کراوە             |
//| (بۆ ئەوەی هەر قۆناغێک تەنها یەک جار کار بکات)                    |
//+------------------------------------------------------------------+
ulong g_tierTickets[];
int   g_tierLevels[];

bool IsTierDone(ulong ticket, int tier)
  {
   for(int i = 0; i < ArraySize(g_tierTickets); i++)
      if(g_tierTickets[i] == ticket && g_tierLevels[i] >= tier) return true;
   return false;
  }

void MarkTierDone(ulong ticket, int tier)
  {
   for(int i = 0; i < ArraySize(g_tierTickets); i++)
      if(g_tierTickets[i] == ticket)
        {
         if(tier > g_tierLevels[i]) g_tierLevels[i] = tier;
         return;
        }
   int n = ArraySize(g_tierTickets);
   ArrayResize(g_tierTickets, n + 1);
   ArrayResize(g_tierLevels,  n + 1);
   g_tierTickets[n] = ticket;
   g_tierLevels[n]  = tier;
  }

//--- سڕینەوەی تیکێتە داخراوەکان لە لیستەکە (نەهێشتنی گەورەبوونی بێکۆتایی)
void PruneTierMemory()
  {
   for(int i = ArraySize(g_tierTickets) - 1; i >= 0; i--)
      if(!PositionSelectByTicket(g_tierTickets[i]))
        {
         int last = ArraySize(g_tierTickets) - 1;
         g_tierTickets[i] = g_tierTickets[last];
         g_tierLevels[i]  = g_tierLevels[last];
         ArrayResize(g_tierTickets, last);
         ArrayResize(g_tierLevels,  last);
        }
  }

//+------------------------------------------------------------------+
//| ئایا ئەم پۆزیشنە هی ئێمەیە؟                                      |
//| هەموو ژمارە جادووییەکانی 9900xx هی ئەم پردەن (هەر تایمفرەیمێک    |
//| ژمارەی خۆی هەیە) — بۆیە پۆزیشنی دەستی یان EA ی تر دەست لێ نادرێت.|
//+------------------------------------------------------------------+
bool IsOurMagic(long m)
  {
   if(m == MagicNumber) return true;
   if(!UseSignalMagic)  return false;
   return (m >= 990000 && m <= 990999);
  }

//--- تەنها پۆزیشنەکانی یەک لەیئاوت (بۆ جیاکردنەوەی تەواو)
bool IsSameLayout(long m, long want)
  {
   return (m == want);
  }

void CloseAll()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(pos.SelectByIndex(i) && IsOurMagic(pos.Magic()))
         trade.PositionClose(pos.Ticket());
  }

void ClosePositionsOn(string symbol)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(pos.SelectByIndex(i) && IsOurMagic(pos.Magic()) && pos.Symbol() == symbol)
         trade.PositionClose(pos.Ticket());
  }

//--- پێچەوانەکردن: تەنها لەناو هەمان لەیئاوتدا (١m بەسەر ٣m دا نەڕوات)
void CloseOppositePositions(string symbol, bool wantBuy, long layoutMagic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!pos.SelectByIndex(i)) continue;
      if(!IsSameLayout(pos.Magic(), layoutMagic) || pos.Symbol() != symbol) continue;
      bool isBuy = (pos.PositionType() == POSITION_TYPE_BUY);
      if(isBuy != wantBuy) trade.PositionClose(pos.Ticket());
     }
  }

//+------------------------------------------------------------------+
//| ڕاپۆرتەکان                                                       |
//+------------------------------------------------------------------+
void Report(string clientId, string status, long ticket, double fillPrice, string err)
  {
   StringReplace(err, "\"", "'");
   string body = StringFormat(
      "{\"token\":\"%s\",\"client_id\":\"%s\",\"status\":\"%s\",\"ticket\":%d,\"fill_price\":%.5f,\"error\":\"%s\"}",
      EAToken, clientId, status, ticket, fillPrice, err);
   HttpPost(ServerURL + "/api/orders/report", body);
  }

void SendAccountReport()
  {
   string positions = "[";
   bool first = true;
   for(int i = 0; i < PositionsTotal(); i++)
     {
      if(!pos.SelectByIndex(i)) continue;
      if(!first) positions += ",";
      positions += StringFormat(
         "{\"ticket\":%d,\"symbol\":\"%s\",\"side\":\"%s\",\"volume\":%.2f,\"open_price\":%.5f,\"profit\":%.2f}",
         pos.Ticket(), pos.Symbol(),
         pos.PositionType() == POSITION_TYPE_BUY ? "buy" : "sell",
         pos.Volume(), pos.PriceOpen(), pos.Profit());
      first = false;
     }
   positions += "]";

   string body = StringFormat(
      "{\"token\":\"%s\",\"login\":\"%d\",\"broker\":\"%s\",\"currency\":\"%s\","
      "\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,\"free_margin\":%.2f,"
      "\"margin_level\":%.2f,\"spread_points\":%d,\"positions\":%s}",
      EAToken, AccountInfoInteger(ACCOUNT_LOGIN), AccountInfoString(ACCOUNT_COMPANY),
      AccountInfoString(ACCOUNT_CURRENCY), AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY), AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE), AccountInfoDouble(ACCOUNT_MARGIN_LEVEL),
      (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD), positions);

   HttpPost(ServerURL + "/api/account/report", body);
  }

//+------------------------------------------------------------------+
//| ناردنی ترەیدە داخراوەکان بۆ سێرڤەر                                |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(!IsOurMagic(HistoryDealGetInteger(trans.deal, DEAL_MAGIC))) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT) return;

   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);

   string body = StringFormat(
      "{\"token\":\"%s\",\"ticket\":%d,\"symbol\":\"%s\",\"side\":\"%s\",\"volume\":%.2f,"
      "\"close_price\":%.5f,\"profit\":%.2f,\"closed_ts\":%d}",
      EAToken, HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID),
      HistoryDealGetString(trans.deal, DEAL_SYMBOL),
      HistoryDealGetInteger(trans.deal, DEAL_TYPE) == DEAL_TYPE_SELL ? "buy" : "sell",
      HistoryDealGetDouble(trans.deal, DEAL_VOLUME),
      HistoryDealGetDouble(trans.deal, DEAL_PRICE), profit,
      (long)HistoryDealGetInteger(trans.deal, DEAL_TIME));

   HttpPost(ServerURL + "/api/trades/closed", body);
  }
//+------------------------------------------------------------------+
