#!/usr/bin/env python3
"""Point-in-time TOP15 daily-close signal / next-open execution backtest."""
import csv, json, pathlib, datetime as dt, math, statistics, urllib.request, urllib.parse, time
ROOT=pathlib.Path("data/top15"); OUT=pathlib.Path("backtest/top15"); OUT.mkdir(parents=True,exist_ok=True)
rank=json.loads((ROOT/"historical_rankings.json").read_text())["reports"]
aliases={"11 BIT STUDIOS":"11 BIT","VIGO SYSTEM":"VIGO PHOTONICS","RYVU THERAPUETICS":"RYVU THERAPEUTICS","BRAND 24":"BRAND24","MOBRUK":"MO-BRUK","MAKARONY":"MAKARONY POLSKIE","ENTER":"ENTER AIR","RAINBOW":"RAINBOW TOURS","CREOTECH":"CREOTECH INSTRUMENTS","MOSTOTAL ZABRZE":"MOSTOSTAL ZABRZE"}
status=json.loads((ROOT/"download_status.json").read_text())["companies"]
def read_csv(p):
 with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
prices={}; quality={}
for name,meta in status.items():
 if meta["status"]!="ok" or name=="BRAND24":continue
 path=ROOT/"ohlcv"/(meta["ticker"].replace(".","_")+".csv")
 if not path.exists():quality[name]={"error":"CSV missing"};continue
 try:
  rows=read_csv(path); data={}
  for r in rows:
   date=r["date"]; o,h,l,c=[float(r[k]) for k in ("open","high","low","close")]
   if not all(math.isfinite(x) and x>0 for x in (o,h,l,c)) or h<max(o,c,l) or l>min(o,c,h):raise ValueError("Invalid OHLC "+date)
   if date in data:raise ValueError("Duplicate "+date)
   data[date]=(o,h,l,c)
  prices[name]=data
  quality[name]={"bars":len(data),"first":min(data),"last":max(data),"weekend_rows":sum(dt.date.fromisoformat(d).weekday()>4 for d in data),"jan1_rows":sum(d.endswith("-01-01") for d in data)}
 except Exception as e:quality[name]={"error":str(e)}
# TIM archive: money.pl columns are Polish; volume unavailable, never pretend turnover is volume.
tim={}
for r in read_csv(ROOT/"source"/"TIM_moneypl.csv"):
 try:
  d=r["Data"];o=float(r["Otwarcie"]);c=float(r["Zamknięcie"]);h=float(r["Maks."]);l=float(r["Min."])
  if not all(math.isfinite(x) and x>0 for x in (o,h,l,c)) or h<max(o,c,l) or l>min(o,c,h):continue
  tim[d]=(o,h,l,c)
 except (ValueError,KeyError):continue
prices["TIM"]=tim;quality["TIM"]={"bars":len(tim),"first":min(tim),"last":max(tim),"source":"Money.pl; turnover is NOT share volume"}
(OUT/"quality.json").write_text(json.dumps(quality,indent=2,ensure_ascii=False))
# Reject suspect sessions (e.g. Jan 1) from all series, not just trading signals.
for name,data in prices.items():
 prices[name]={d:v for d,v in data.items() if dt.date.fromisoformat(d).weekday()<5 and not d.endswith("-01-01") and not d.endswith("-12-25") and not d.endswith("-12-26")}
# Verify 22 reports and point-in-time availability
assert len(rank)==22
for r in rank:assert len(r["ranked_companies"])==15,(r["quarter"],len(r["ranked_companies"]))
reports=sorted(rank,key=lambda r:r["published_at_warsaw"])
all_dates=sorted(set().union(*(set(v) for v in prices.values())))
import bisect
def active(d):
 i=bisect.bisect_left([r["published_at_warsaw"][:10] for r in reports],d)-1
 # same-day publications can be used after market close only, so start next trading day
 return [aliases.get(x,x) for x in reports[i]["ranked_companies"]] if i>=0 else []
features={}
for name,series in prices.items():
 ds=sorted(series); f={}
 for i,d in enumerate(ds):
  if i<200:continue
  closes=[series[x][3] for x in ds[i-200:i+1]]
  ma50=sum(closes[-50:])/50
  prev_ma50=sum(closes[-51:-1])/50
  ma200=sum(closes[-200:])/200
  breakout=series[d][3]>max(series[x][1] for x in ds[i-20:i])
  f[d]={"ma50":ma50,"ma200":ma200,"buy":series[d][3]>ma200 and ma50>prev_ma50 and breakout,"below50":series[d][3]<ma50}
 features[name]=f
def simulate(mode):
 cash=10000.; positions={}; orders=[]; equity=[]; trades=[]; skipped=0
 for i,d in enumerate(all_dates):
  if i==0:continue
  prev=all_dates[i-1]
  # execute yesterday's signals at today's opening price, never today's close
  for name,p in list(positions.items()):
   if d not in prices[name]:continue
   op=prices[name][d][0]; sig=features[name].get(prev)
   if not sig:continue
   qty=0;reason=""
   if mode=="TP30" and prices[name][prev][3]>=p["entry"]*1.3:qty=p["qty"];reason="TP30 close signal"
   elif mode=="MA50" and sig["below50"]:qty=p["qty"];reason="MA50 close signal"
   elif mode=="HALF" and not p["half"] and prices[name][prev][3]>=p["entry"]*1.3:qty=max(1,p["qty"]//2);reason="TP30 half";p["half"]=True
   elif mode=="HALF" and sig["below50"]:qty=p["qty"];reason="MA50 remainder"
   if qty:
    qty=min(qty,p["qty"]);cash+=qty*op;p["qty"]-=qty
    trades.append({"date":d,"name":name,"action":"SELL","shares":qty,"price":op,"reason":reason,"pnl":round(qty*(op-p["entry"]),2)})
    if p["qty"]==0:del positions[name]
  # forced delisting settlement at last available close; conservative simplification, flagged
  if d=="2024-06-04" and "TIM" in positions:
   p=positions.pop("TIM");cash+=p["qty"]*prices["TIM"][d][3]
   trades.append({"date":d,"name":"TIM","action":"SELL","shares":p["qty"],"price":prices["TIM"][d][3],"reason":"DELISTING PROXY last close; corporate cash settlement not verified","pnl":round(p["qty"]*(prices["TIM"][d][3]-p["entry"]),2)})
  universe=active(prev)
  for name in universe:
   if len(positions)>=5:break
   if name=="BRAND24" or name in positions or name not in prices:continue
   if prev not in features[name] or not features[name][prev]["buy"] or d not in prices[name]:continue
   # ensure previous day is actual series trading day, not stale data
   if prev not in prices[name]:continue
   eq=cash+sum(p["qty"]*prices[n].get(prev,(0,0,0,p["last"]))[3] for n,p in positions.items())
   budget=min(cash,eq*.2);op=prices[name][d][0];qty=int(budget//op)
   if qty<1:skipped+=1;continue
   cash-=qty*op;positions[name]={"qty":qty,"entry":op,"last":op,"half":False}
   trades.append({"date":d,"name":name,"action":"BUY","shares":qty,"price":op,"reason":"MA200 rising MA50 20-day breakout","pnl":""})
  value=cash
  for name,p in positions.items():
   if d in prices[name]:p["last"]=prices[name][d][3]
   value+=p["qty"]*p["last"]
  equity.append((d,round(value,2)))
 # Mark residual positions at end, not fictional closing trades
 peak=10000;maxdd=0
 for _,v in equity:peak=max(peak,v);maxdd=min(maxdd,v/peak-1)
 return {"mode":mode,"start_capital":10000,"end_equity":equity[-1][1],"return_pct":round((equity[-1][1]/10000-1)*100,2),"max_drawdown_pct":round(maxdd*100,2),"buy_orders":sum(t["action"]=="BUY" for t in trades),"sell_orders":sum(t["action"]=="SELL" for t in trades),"open_positions":{k:v["qty"] for k,v in positions.items()},"skipped_small_orders":skipped},trades,equity
results=[]
for mode in ("TP30","MA50","HALF"):
 summary,trades,equity=simulate(mode);results.append(summary)
 for filename,rows,fields in [(mode+"_trades.csv",trades,["date","name","action","shares","price","reason","pnl"]),(mode+"_equity.csv",[dict(date=d,equity=v) for d,v in equity],["date","equity"])]:
  with (OUT/filename).open("w",newline="") as f:
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
# Benchmark requires independent WIG daily index dataset; do not invent benchmark.
benchmark={"status":"not_calculated","reason":"WIG daily price series not included in repository; benchmark pending validated dataset"}
(OUT/"results.json").write_text(json.dumps({"strategies":results,"benchmark_wig":benchmark,"caveats":["No fees, slippage, dividends or corporate actions modeled","Historical rank mapping and Yahoo price adjustments need independent audit","TIM delisting proxy uses last close, not verified cash settlement","Brand24 omitted by user decision","Signals evaluated at prior close; orders filled next opening","No trading at zero-volume sessions is not yet enforced for Yahoo data","Yahoo price dates and holiday rows require validation"]},indent=2,ensure_ascii=False))
print(json.dumps(results,indent=2))
