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
input long    MagicNumber    = 990011;
input int     SlippagePoints = 30;
input bool    EnableTrading  = true;                    // کلیلی ناوخۆیی

CTrade         trade;
CPositionInfo  pos;
datetime       lastHeartbeat = 0;
int            lastPollTick  = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
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
     }
   ManageOpenPositions();
   PollOrder();
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

//+------------------------------------------------------------------+
//| وەرگرتنی فەرمانی داهاتوو                                          |
//+------------------------------------------------------------------+
void PollOrder()
  {
   string resp = HttpGet(ServerURL + "/api/orders/next?token=" + EAToken);
   if(resp == "" || StringFind(resp, "\"has_order\":true") < 0) return;

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

   string symbol = ResolveSymbol(symbolIn);

   if(!EnableTrading)
     { Report(clientId, "failed", 0, 0, "EA locally disabled"); return; }

   if(action == "close_all")
     { CloseAll(); Report(clientId, "filled", 0, 0, ""); return; }

   if(action == "close")
     { ClosePositionsOn(symbol); Report(clientId, "filled", 0, 0, ""); return; }

   if(symbol == "")
     { Report(clientId, "failed", 0, 0, "symbol not found: " + symbolIn); return; }

   //--- فیلتەری سپرێد
   double spread = (double)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   if(maxSpread > 0 && spread > maxSpread)
     { Report(clientId, "failed", 0, 0, StringFormat("spread too high %.0f", spread)); return; }

   bool isBuy = (action == "buy");
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double ask   = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double bid   = SymbolInfoDouble(symbol, SYMBOL_BID);
   double entry = isBuy ? ask : bid;

   //--- SL/TP ی بنەڕەت ئەگەر سیگناڵ نەیناردبوو
   if(sl <= 0 && defSlPts > 0) sl = isBuy ? entry - defSlPts * point : entry + defSlPts * point;
   if(tp <= 0 && defTpPts > 0) tp = isBuy ? entry + defTpPts * point : entry - defTpPts * point;

   //--- قەبارەی لۆت بەپێی مەترسی
   if(volume <= 0)
     {
      if(riskPct > 0 && sl > 0) volume = LotByRisk(symbol, riskPct, MathAbs(entry - sl));
      else                      volume = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
     }
   volume = NormalizeVolume(symbol, MathMin(volume, maxLot > 0 ? maxLot : volume));
   if(volume <= 0)
     { Report(clientId, "failed", 0, 0, "invalid volume"); return; }

   //--- پێچەوانەکردن
   if(allowRev) CloseOppositePositions(symbol, isBuy);

   bool ok = isBuy ? trade.Buy(volume, symbol, 0.0, NormalizePrice(symbol, sl), NormalizePrice(symbol, tp), clientId)
                   : trade.Sell(volume, symbol, 0.0, NormalizePrice(symbol, sl), NormalizePrice(symbol, tp), clientId);

   if(ok && trade.ResultRetcode() == TRADE_RETCODE_DONE)
      Report(clientId, "filled", (long)trade.ResultOrder(), trade.ResultPrice(), "");
   else
      Report(clientId, "failed", 0, 0, StringFormat("%d %s", trade.ResultRetcode(), trade.ResultRetcodeDescription()));
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
double LotByRisk(string symbol, double riskPct, double slDistance)
  {
   if(slDistance <= 0) return 0;
   double equity   = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskCash = equity * riskPct / 100.0;
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
void ManageOpenPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!pos.SelectByIndex(i)) continue;
      if(pos.Magic() != MagicNumber) continue;
      string sym = pos.Symbol();
      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      double openP = pos.PriceOpen();
      double cur   = pos.PriceCurrent();
      double sl    = pos.StopLoss();
      bool   isBuy = (pos.PositionType() == POSITION_TYPE_BUY);
      double profitPts = isBuy ? (cur - openP) / point : (openP - cur) / point;

      // trailing سادە: 30% ی دووری، تەنها بەرەو پێشەوە
      if(profitPts > 200)
        {
         double newSl = isBuy ? cur - 100 * point : cur + 100 * point;
         newSl = NormalizePrice(sym, newSl);
         bool better = isBuy ? (sl == 0 || newSl > sl + point) : (sl == 0 || newSl < sl - point);
         if(better) trade.PositionModify(pos.Ticket(), newSl, pos.TakeProfit());
        }
     }
  }

void CloseAll()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Magic() == MagicNumber)
         trade.PositionClose(pos.Ticket());
  }

void ClosePositionsOn(string symbol)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(pos.SelectByIndex(i) && pos.Magic() == MagicNumber && pos.Symbol() == symbol)
         trade.PositionClose(pos.Ticket());
  }

void CloseOppositePositions(string symbol, bool wantBuy)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!pos.SelectByIndex(i)) continue;
      if(pos.Magic() != MagicNumber || pos.Symbol() != symbol) continue;
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
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber) return;
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
