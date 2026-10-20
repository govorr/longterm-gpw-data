#!/usr/bin/env python3
"""Extended TOP15 research, 10y data, chronological holdout, WIG and buy-and-hold."""
import csv, io, json, pathlib, urllib.request, urllib.parse, datetime as dt
from backtest_top15 import prepare, simulate, INITIAL, FEE, MODES
from update import STOCKS

def yahoo(symbol):
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol,safe="")+"?range=10y&interval=1d"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as resp: result=json.load(resp)["chart"]["result"][0]
    quote=result["indicators"]["quote"][0]
    out=[]
    for i,t in enumerate(result["timestamp"]):
        vals=[quote[k][i] for k in ("open","high","low","close","volume")]
        if any(v is None for v in vals): continue
        day=dt.datetime.fromtimestamp(t,dt.timezone.utc).date().isoformat()
        if day>dt.date.today().isoformat(): continue
        out.append(dict(zip(("date","open","high","low","close","volume"),(day,*vals))))
    return sorted({r["date"]:r for r in out}.values(),key=lambda x:x["date"])

def index_history():
    failures={}
    for symbol in ("%5EWIG","WIG.WA"):
        try:
            bars=yahoo(urllib.parse.unquote(symbol))
            if len(bars)>=600: return {r["date"]:r["close"] for r in bars},"Yahoo "+symbol
            failures[symbol]="Only "+str(len(bars))+" bars"
        except Exception as e: failures[symbol]=str(e)
    try:
        url="https://stooq.pl/q/d/l/?s=wig&i=d"
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=30) as resp: content=resp.read().decode("utf-8-sig")
        rows=list(csv.DictReader(io.StringIO(content)))
        prices={r.get("Date",r.get("Data")):float(r.get("Close",r.get("Zamkniecie"))) for r in rows}
        if len(prices)>=600: return prices,"Stooq WIG"
        failures["Stooq"]="Only "+str(len(prices))+" bars"
    except Exception as e: failures["Stooq"]=str(e)
    return {},failures

def buyhold(history,dates):
    first=dates[0]
    eligible=[s for s in sorted(history) if first in history[s] and history[s][first]["open"]>0]
    # Deterministic alphabetic choice of up to 5 eligible stocks; no future returns used.
    selected=eligible[:5]
    cash=INITIAL
    shares={}
    for s in selected:
        price=history[s][first]["open"]
        qty=int(min(cash,INITIAL*0.20)/(price*(1+FEE)))
        if qty:
            cash-=qty*price*(1+FEE)
            shares[s]=qty
    values=[]
    for day in dates:
        val=cash+sum(q*history[s][day]["close"] for s,q in shares.items())
        values.append(val)
    peak=INITIAL;dd=0
    for v in values:
        peak=max(peak,v);dd=min(dd,v/peak-1)
    return {"selection":"Alphabetical first five eligible at start; fixed, no rebalance","symbols":list(shares),"return_pct":round((values[-1]/INITIAL-1)*100,2),"max_drawdown_pct":round(dd*100,2),"final_equity":round(values[-1],2)}

def wig_return(wig,dates):
    valid=[d for d in dates if d in wig]
    if len(valid)<int(len(dates)*0.95): return {"error":"Insufficient aligned WIG sessions","coverage":len(valid)}
    start,end=valid[0],valid[-1]
    prices=[wig[d] for d in valid]
    peak=prices[0];dd=0
    for p in prices:
        peak=max(peak,p);dd=min(dd,p/peak-1)
    return {"start":start,"end":end,"return_pct":round((prices[-1]/prices[0]-1)*100,2),"max_drawdown_pct":round(dd*100,2),"sessions":len(valid),"dividends":"WIG is total return index"}

def main():
    history={};excluded={}
    for s in STOCKS:
        try:
            rows=yahoo(s+".WA")
            if len(rows)<250:
                excluded[s]="Only "+str(len(rows))+" daily bars";continue
            prepare(rows)
            ix={r["date"]:dict(r) for r in rows}
            prev=None
            for d in sorted(ix):
                ix[d]["prev"]=prev;prev=ix[d]
            history[s]=ix
            print("Fetched",s,len(rows),flush=True)
        except Exception as e: excluded[s]=str(e)
    if len(history)<8: raise RuntimeError("Too few stocks "+str(excluded))
    wig,wig_source=index_history()
    # Use dates common to all included securities; report the coverage loss explicitly.
    common=sorted(set.intersection(*(set(h) for h in history.values())))
    dates=[d for d in common if all(history[s][d].get("ma200") is not None and (history[s][d].get("prev") or {}).get("ma200") is not None for s in history)]
    if len(dates)<300: raise RuntimeError("Insufficient common history "+str(len(dates)))
    split=int(len(dates)*0.65)
    periods={"full":dates,"development":dates[:split],"holdout":dates[split:]}
    results={}
    for name,ds in periods.items():
        results[name]={"start":ds[0],"end":ds[-1],"sessions":len(ds),
                       "strategies":[{k:v for k,v in simulate(history,m,ds).items() if k not in ("trades","equity_curve")} for m in MODES],
                       "buy_hold":buyhold(history,ds),
                       "wig":wig_return(wig,ds) if wig else {"error":"WIG unavailable"}}
    out={"limitations":["Present-day constituents applied historically (survivorship and look-ahead selection bias)","Development/holdout split is chronological but constituents are not point-in-time","Unadjusted Yahoo OHLC; corporate actions and dividends not normalized","Daily-high TP fills optimistic; no queue/volume constraints","No tax; 0.2% per-side assumed friction","Common-date intersection reduces historical sample","Buy-hold picks first five alphabetical stocks, not an optimized benchmark"],
         "symbols":sorted(history),"excluded":excluded,"wig_source":wig_source,"periods":results}
    pathlib.Path("docs").mkdir(exist_ok=True)
    pathlib.Path("docs/backtest_top15_extended.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for k,v in results.items():
        print(k,v["start"],v["end"],"WIG",v["wig"],"BUYHOLD",v["buy_hold"]["return_pct"],[(x["mode"],x["return_pct"],x["max_drawdown_pct"]) for x in v["strategies"]],flush=True)
if __name__=="__main__":main()
