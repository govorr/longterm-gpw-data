#!/usr/bin/env python3
"""Research only: compare exit rules. No orders; current-constituent/survivorship bias."""
import json
import pathlib
from statistics import mean
from update import STOCKS, fetch

INITIAL=10000.0
FEE=0.002
MAX_WEIGHT=0.20
MAX_HOLDINGS=5
MODES=("tp30","ma50","half_tp30_ma50")

def prepare(rows):
    for i, r in enumerate(rows):
        if i<200: continue
        r["ma50"]=mean(x["close"] for x in rows[i-49:i+1])
        r["ma50_prev"]=mean(x["close"] for x in rows[i-50:i])
        r["ma200"]=mean(x["close"] for x in rows[i-199:i+1])
        r["high20"]=max(x["high"] for x in rows[i-20:i])
        r["signal"]=r["close"]>r["ma200"] and r["ma50"]>r["ma50_prev"] and r["close"]>r["high20"]

def simulate(history,mode,dates):
    cash=INITIAL
    positions={}
    deals=[]
    equity=[]
    peak=INITIAL
    max_dd=0.0
    for day in dates:
        today={s:hist[day] for s,hist in history.items() if day in hist}
        # All entries/exits are decided from the previous completed session.
        for s in sorted(list(positions)):
            p=positions[s]
            row=today.get(s)
            if row is None: continue
            prev=row.get("prev")
            if mode!="tp30" and prev and prev.get("ma50") is not None and prev["close"]<prev["ma50"]:
                qty=p["qty"]
                proceeds=qty*row["open"]*(1-FEE)
                cash+=proceeds
                deals.append({"symbol":s,"entry":p["entry_date"],"exit":day,"reason":"MA50","pnl":round(proceeds-p["cost"],2)})
                del positions[s]
        # Current open equity and holdings limit, with no leverage or fractional shares.
        open_equity=cash+sum(p["qty"]*today[s]["open"] for s,p in positions.items())
        for s in sorted(today):
            if len(positions)>=MAX_HOLDINGS: break
            row=today[s]
            prev=row.get("prev")
            if s in positions or not prev or not prev.get("signal"): continue
            price=row["open"]
            if price<=0: continue
            allocation=min(cash,MAX_WEIGHT*open_equity)
            qty=int(allocation/(price*(1+FEE)))
            if qty<1: continue
            cost=qty*price*(1+FEE)
            cash-=cost
            positions[s]={"qty":qty,"entry_price":price,"entry_date":day,"cost":cost,"tp_done":False}
        # TP fills at target, or at open if a gap crosses it.
        if mode!="ma50":
            for s in sorted(list(positions)):
                p=positions[s]
                row=today.get(s)
                if row is None or p["tp_done"]: continue
                target=p["entry_price"]*1.30
                if row["high"]<target: continue
                sell_qty=p["qty"] if mode=="tp30" else max(1,p["qty"]//2)
                sell_price=max(target,row["open"])
                proceeds=sell_qty*sell_price*(1-FEE)
                cost_part=p["cost"]*sell_qty/p["qty"]
                cash+=proceeds
                deals.append({"symbol":s,"entry":p["entry_date"],"exit":day,"reason":"TP30","pnl":round(proceeds-cost_part,2)})
                p["qty"]-=sell_qty
                p["cost"]-=cost_part
                p["tp_done"]=True
                if p["qty"]==0: del positions[s]
        value=cash+sum(p["qty"]*today[s]["close"] for s,p in positions.items())
        peak=max(peak,value)
        max_dd=min(max_dd,value/peak-1)
        equity.append({"date":day,"value":round(value,2)})
        if cash < -0.000001: raise RuntimeError("Negative cash")
        if len(positions)>MAX_HOLDINGS: raise RuntimeError("Holdings limit exceeded")
    final=equity[-1]["value"]
    open_value=sum(p["qty"]*history[s][dates[-1]]["close"] for s,p in positions.items())
    unrealized=round(sum(p["qty"]*history[s][dates[-1]]["close"]-p["cost"] for s,p in positions.items()),2)
    return {"mode":mode,"start":dates[0],"end":dates[-1],"initial":INITIAL,
        "final_equity":round(final,2),"return_pct":round((final/INITIAL-1)*100,2),
        "max_drawdown_pct":round(100*max_dd,2),"closed_trades":len(deals),
        "closed_win_rate_pct":round(100*sum(t["pnl"]>0 for t in deals)/len(deals),2) if deals else None,
        "realized_pnl":round(sum(t["pnl"] for t in deals),2),
        "unrealized_pnl":unrealized,"cash":round(cash,2),"open_value":round(open_value,2),
        "open_positions":len(positions),"open_symbols":sorted(positions),
        "max_holding_count":MAX_HOLDINGS,"max_new_allocation_pct":20,
        "trades":deals,"equity_curve":equity}

def main():
    history={}
    excluded={}
    for symbol in STOCKS:
        try:
            rows=fetch(symbol)
            if len(rows)<230:
                excluded[symbol]="Insufficient history: "+str(len(rows))+" sessions"
                continue
            prepare(rows)
            indexed={r["date"]:dict(r) for r in rows}
            prev=None
            for day in sorted(indexed):
                indexed[day]["prev"]=prev
                prev=indexed[day]
            history[symbol]=indexed
        except Exception as e:
            excluded[symbol]=str(e)
    if len(history)<8: raise RuntimeError("Insufficient valid stocks: "+str(excluded))
    common=sorted(set.intersection(*(set(h) for h in history.values())))
    dates=[day for day in common if all(history[s][day].get("ma200") is not None and
           (history[s][day].get("prev") or {}).get("ma200") is not None for s in history)]
    if len(dates)<30: raise RuntimeError("Insufficient common sessions")
    result={"method":"Exploratory current-constituent historical screen; survivorship and selection bias. Unadjusted Yahoo OHLC; no dividends or taxes. 0.2% friction each side, next-session open execution, TP using daily high (optimistic intraday fill), 5 simultaneous holdings maximum, new allocation <=20% of equity, no forced sale after appreciation, no fractional shares. No benchmark or out-of-sample validation.",
      "symbols":sorted(history),"excluded_symbols":excluded,"sessions":len(dates),
      "results":[simulate(history,mode,dates) for mode in MODES]}
    pathlib.Path("docs").mkdir(exist_ok=True)
    pathlib.Path("docs/backtest_top15_v2.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for r in result["results"]:
        print(r["mode"],"return",r["return_pct"],"max_dd",r["max_drawdown_pct"],"open",r["open_positions"],"unrealized",r["unrealized_pnl"],flush=True)
if __name__=="__main__": main()
