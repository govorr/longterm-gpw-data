#!/usr/bin/env python3
"""Research-only historical comparison; no brokerage orders."""
import csv, datetime as dt, json, math, pathlib
from statistics import mean
from update import STOCKS, fetch

INITIAL = 10000.0
FEE = 0.002  # conservative assumed friction per side; not actual XTB commission
MODES = ("tp30", "ma50", "half_tp30_ma50")

def indicators(rows):
    for i in range(200, len(rows)):
        r = rows[i]
        r["ma50"] = mean(x["close"] for x in rows[i-49:i+1])
        r["ma50_prev"] = mean(x["close"] for x in rows[i-50:i])
        r["ma200"] = mean(x["close"] for x in rows[i-199:i+1])
        r["high20"] = max(x["high"] for x in rows[i-20:i])
        r["signal"] = r["close"] > r["ma200"] and r["ma50"] > r["ma50_prev"] and r["close"] > r["high20"]

def simulate(history, mode, dates):
    cash = INITIAL
    positions = {}
    deals = []
    equity = []
    peak = INITIAL
    max_dd = 0.0
    for day in dates:
        available = {s: index[day] for s, index in history.items() if day in index}
        # All signals are based on the previous trading session; execute next open.
        for symbol in list(positions):
            pos = positions[symbol]
            row = available.get(symbol)
            if not row:
                continue
            prev = pos.get("prev")
            if prev and prev.get("ma50") is not None and prev["close"] < prev["ma50"]:
                if mode != "tp30":
                    price = row["open"]
                    qty = pos["qty"]
                    cash += qty * price * (1-FEE)
                    deals.append({"symbol":symbol,"entry":pos["entry_date"],"exit":day,"reason":"MA50","pnl":round(qty*price*(1-FEE)-pos["cost_remaining"],2)})
                    del positions[symbol]
        # Entry decisions based only on prior session; no fractional shares.
        total_at_open = cash + sum(p["qty"] * available[s]["open"] for s,p in positions.items() if s in available)
        for symbol in sorted(available):
            row = available[symbol]
            prev = row.get("prev")
            if symbol in positions or not prev or not prev.get("signal"):
                continue
            budget = min(cash, total_at_open*0.20)
            price = row["open"]
            qty = int(budget/(price*(1+FEE))) if price > 0 else 0
            if qty < 1: continue
            cost = qty*price*(1+FEE)
            cash -= cost
            positions[symbol] = {"qty":qty,"entry_price":price,"entry_date":day,"cost_remaining":cost,"tp_done":False}
        # Intraday limit fills. If open gaps above TP, assume open fill.
        if mode != "ma50":
            for symbol in list(positions):
                row = available.get(symbol)
                if not row: continue
                pos = positions[symbol]
                if pos["tp_done"]: continue
                target = pos["entry_price"]*1.30
                if row["high"] < target: continue
                qty = pos["qty"] if mode=="tp30" else max(1,pos["qty"]//2)
                price = max(target,row["open"])
                proceeds = qty*price*(1-FEE)
                cost_part = pos["cost_remaining"]*qty/pos["qty"]
                cash += proceeds
                deals.append({"symbol":symbol,"entry":pos["entry_date"],"exit":day,"reason":"TP30","pnl":round(proceeds-cost_part,2)})
                pos["qty"] -= qty
                pos["cost_remaining"] -= cost_part
                pos["tp_done"] = True
                if pos["qty"]==0: del positions[symbol]
        for symbol, pos in positions.items():
            if symbol in available: pos["prev"] = available[symbol]
        value = cash + sum(p["qty"] * (available[s]["close"] if s in available else p.get("last_close",p["entry_price"])) for s,p in positions.items())
        for s,p in positions.items():
            if s in available: p["last_close"]=available[s]["close"]
        peak=max(peak,value)
        max_dd=min(max_dd,value/peak-1)
        equity.append({"date":day,"value":round(value,2)})
    final=equity[-1]["value"]
    return {"mode":mode,"start":dates[0],"end":dates[-1],"initial":INITIAL,"final_equity":final,"return_pct":round((final/INITIAL-1)*100,2),"max_drawdown_pct":round(max_dd*100,2),"closed_trades":len(deals),"win_rate_pct":round(100*sum(d["pnl"]>0 for d in deals)/len(deals),2) if deals else None,"open_positions":len(positions),"open_symbols":sorted(positions),"fees_per_side_assumed":FEE,"trades":deals,"equity_curve":equity}

def main():
    history={}
    errors={}
    for s in STOCKS:
        try:
            rows=fetch(s)
            if len(rows)<230:
                errors[s]="Too few observations: "+str(len(rows))
                continue
            indicators(rows)
            index={r["date"]:dict(r) for r in rows}
            previous=None
            for day in sorted(index):
                index[day]["prev"]=previous
                previous=index[day]
            history[s]=index
        except Exception as e: errors[s]=str(e)
    if errors: raise RuntimeError("Incomplete historical data: "+json.dumps(errors))
    common=sorted(set.intersection(*(set(x) for x in history.values())))
    # At least 200 prior bars for every stock. Start at first common date with valid MA200.
    dates=[d for d in common if all(history[s][d].get("ma200") is not None and history[s][d].get("prev",{}).get("ma200") is not None for s in history)]
    if len(dates)<30: raise RuntimeError("Not enough common trading sessions for unbiased comparison")
    result={"method":"Longterm TOP15 current-constituent research; survivorship bias; unadjusted Yahoo OHLC; 0.2% per side assumed; no dividends, taxes or slippage beyond fee; next-open signals; daily high TP fill; cash allowed","symbols":list(STOCKS),"sessions":len(dates),"results":[simulate(history,m,dates) for m in MODES]}
    pathlib.Path("docs").mkdir(exist_ok=True)
    pathlib.Path("docs/backtest_top15.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    for x in result["results"]:
        print(x["mode"],"return",x["return_pct"],"drawdown",x["max_drawdown_pct"],"closed",x["closed_trades"],flush=True)
if __name__=="__main__": main()
