#!/usr/bin/env python3
"""Pobiera dzienne OHLCV ze Stooq; tworzy tylko techniczne kandydatury, bez transakcji."""
import csv, io, json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

STOCKS = {
    "CRI":"Creotech Instruments","ASB":"ASBIS","CRQ":"Creotech Quantum",
    "DIG":"Digital Network","LBW":"Lubawa","CLD":"Cloud Technologies",
    "GRN":"Grodno","ELT":"Elektrotim","BCX":"Bioceltix",
    "S2B":"Syn2Bio","DAT":"DataWalk","QNA":"QNA Technology",
    "SEV":"Sevenet","PAS":"Passus","SON":"Sonka"
}
KEY = os.environ.get("STOOQ_API_KEY", "").strip()
if not KEY:
    sys.exit("Brak sekretu STOOQ_API_KEY w GitHub Actions")

def load(symbol):
    url = "https://stooq.pl/q/d/l/?" + urllib.parse.urlencode(
        {"s":symbol.lower(),"i":"d","apikey":KEY}
    )
    req = urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=30) as r:
        raw = r.read(6000000).decode("utf-8-sig",errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    required = {"Date","Open","High","Low","Close","Volume"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("Niepoprawna odpowiedz CSV ze Stooq")
    rows = []
    for row in reader:
        try:
            rows.append({"date":row["Date"],"open":float(row["Open"]),
              "high":float(row["High"]),"low":float(row["Low"]),
              "close":float(row["Close"]),"volume":float(row["Volume"])})
        except (KeyError,ValueError):
            continue
    rows = list({r["date"]:r for r in sorted(rows,key=lambda x:x["date"])}.values())
    if not rows:
        raise ValueError("Brak notowan")
    return rows

def calculate(rows):
    close = [r["close"] for r in rows]
    last = rows[-1]
    result = {"date":last["date"],"close":last["close"],
       "volume":last["volume"],"history_sessions":len(rows),
       "ma50":None,"ma200":None,"atr14":None,
       "previous_20d_high":None,"technical_buy_candidate":False}
    if len(rows)<201:
        result["note"] = "Za krotka historia do MA200: brak sygnalu"
        return result
    ma50=mean(close[-50:]); ma50prev=mean(close[-51:-1])
    ma200=mean(close[-200:])
    tr=[max(r["high"]-r["low"],
            abs(r["high"]-(close[i-1] if i else r["close"])),
            abs(r["low"]-(close[i-1] if i else r["close"]))) for i,r in enumerate(rows)]
    atr14=mean(tr[-14:])
    high20=max(r["high"] for r in rows[-21:-1])
    result.update(ma50=round(ma50,4),ma200=round(ma200,4),
       atr14=round(atr14,4),previous_20d_high=round(high20,4),
       technical_buy_candidate=last["close"]>ma200 and ma50>ma50prev and last["close"]>high20)
    result["note"]="Wylacznie filtr techniczny, nie zlecenie KUP."
    return result

def main():
    result={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
       "source":"Stooq dzienne CSV","stocks":{},"errors":{}}
    for ticker,name in STOCKS.items():
        try:
            x=calculate(load(ticker))
            result["stocks"][ticker]={"name":name,**x}
            print(ticker,x["date"],x["close"],x["technical_buy_candidate"])
        except Exception as e:
            result["errors"][ticker]=str(e)
            print(ticker,"BLAD",e,file=sys.stderr)
    if result["errors"]:
        sys.exit("Przerwano publikacje: braki dla: "+str(result["errors"]))
    dates={x["date"] for x in result["stocks"].values()}
    if len(dates)!=1:
        sys.exit("Przerwano publikacje: rozne daty notowan: "+str(dates))
    Path("docs").mkdir(exist_ok=True)
    Path("docs/latest.json").write_text(
       json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("OK: 15 spol ek, data",next(iter(dates)))

if __name__=="__main__":
    main()
