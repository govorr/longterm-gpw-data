#!/usr/bin/env python3
"""Point-in-time TOP15 daily-close signal / next-open execution backtest."""
import csv, json, pathlib, datetime as dt, math, statistics, urllib.request, urllib.parse, time
ROOT=pathlib.Path("data/top15"); OUT=pathlib.Path("backtest/top15"); OUT.mkdir(parents=True,exist_ok=True)
rank=json.loads((ROOT/"historical_rankings.json").read_text())["reports"]
aliases={"11 BIT STUDIOS":"11 BIT","VIGO SYSTEM":"VIGO PHOTONICS","RYVU THERAPUETICS":"RYVU THERAPEUTICS","BRAND 24":"BRAND24","MOBRUK":"MO-BRUK","MAKARONY":"MAKARONY POLSKIE","ENTER":"ENTER AIR","RAINBOW":"RAINBOW TOURS","CREOTECH":"CREOTECH INSTRUMENTS","MOSTOTAL ZABRZE":"MOSTOSTAL ZABRZE"}
status=json.loads((ROOT/"download_status.json").read_text())["companies"]
def read_csv(p):
 with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
prices={}; quality={}; zero_volume={}; raw_holiday_rows={}; corporate_event_flags=[]
for name,meta in status.items():
 if meta["status"]!="ok" or name=="BRAND24":continue
 path=ROOT/"ohlcv"/(meta["ticker"].replace(".","_")+".csv")
 if not path.exists():quality[name]={"error":"CSV missing"};continue
 try:
  rows=read_csv(path); data={}; zv=set()
  for r in rows:
   date=r["date"]; o,h,l,c=[float(r[k]) for k in ("open","high","low","close")]
   if not all(math.isfinite(x) and x>0 for x in (o,h,l,c)) or h<max(o,c,l) or l>min(o,c,h):raise ValueError("Invalid OHLC "+date)
   if date in data:raise ValueError("Duplicate "+date)
   data[date]=(o,h,l,c)
   if float(r.get("volume") or 0)<=0:zv.add(date)
  prices[name]=data;zero_volume[name]=zv
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
prices["TIM"]=tim;zero_volume["TIM"]=set();quality["TIM"]={"bars":len(tim),"first":min(tim),"last":max(tim),"source":"Money.pl; turnover is NOT share volume"}
(OUT/"quality.json").write_text(json.dumps(quality,indent=2,ensure_ascii=False))
# Audit suspicious rows; zero-volume holiday placeholders are NOT real sessions.
raw_holiday_rows={n:sorted(d for d in data if d.endswith("-01-01") or d.endswith("-12-25") or d.endswith("-12-26")) for n,data in prices.items()}
# Reject suspect sessions (e.g. Jan 1) from all series, not just trading signals.
for name,data in prices.items():
 prices[name]={d:v for d,v in data.items() if dt.date.fromisoformat(d).weekday()<5 and not d.endswith("-01-01") and not d.endswith("-12-25") and not d.endswith("-12-26")}
# Verify 22 reports and point-in-time availability
assert len(rank)==22
for r in rank:assert len(r["ranked_companies"])==15,(r["quarter"],len(r["ranked_companies"]))
reports=sorted(rank,key=lambda r:r["published_at_warsaw"])
all_dates=sorted(d for d in set().union(*(set(v) for v in prices.values())) if "2021-06-29"<=d<="2026-10-19")
assert all_dates and all_dates[-1]=="2026-10-19", "Strategy end must match WIG last date"
# Identify discontinuities potentially caused by splits, symbol changes or other corporate events.
for n,series in prices.items():
 ds=sorted(series)
 for prev_d,d in zip(ds,ds[1:]):
  ratio=series[d][3]/series[prev_d][3]
  if ratio>1.7 or ratio<0.6:corporate_event_flags.append({"company":n,"previous_date":prev_d,"date":d,"close_ratio":round(ratio,4),"requires_manual_review":True})
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
  prior20=max(series[x][1] for x in ds[i-20:i])
  f[d]={"ma50":ma50,"ma200":ma200,"buy":series[d][3]>ma200 and ma50>prev_ma50 and breakout,"below50":series[d][3]<ma50,"trend":series[d][3]>ma200 and ma50>prev_ma50,"pullback_pct":100*(prior20-series[d][3])/prior20,"rebound":series[d][3]>series[ds[i-1]][1],"near_ma50":abs(series[d][3]/ma50-1)<=0.05}
 features[name]=f
def simulate(mode,top_n=15,entry="BREAKOUT"):
 cash=10000.; positions={}; orders=[]; equity=[]; trades=[]; skipped=0
 for i,d in enumerate(all_dates):
  if i==0:continue
  prev=all_dates[i-1]
  # execute yesterday's signals at today's opening price, never today's close
  for name,p in list(positions.items()):
   if d not in prices[name] or d in zero_volume.get(name,set()):continue
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
  universe=active(prev)[:top_n]
  for name in universe:
   if len(positions)>=5:break
   if name=="BRAND24" or name in positions or name not in prices:continue
   if prev not in features[name] or d not in prices[name] or d in zero_volume.get(name,set()):continue
   sig=features[name][prev]
   if entry=="BREAKOUT":eligible=sig["buy"]
   elif entry=="PULLBACK_8_15":eligible=sig["trend"] and 8<=sig["pullback_pct"]<=15 and sig["near_ma50"] and sig["rebound"]
   elif entry=="DEEP_15_25":eligible=sig["trend"] and 15<=sig["pullback_pct"]<=25 and sig["near_ma50"] and sig["rebound"]
   else:raise ValueError("Unknown entry: "+entry)
   if not eligible:continue
   # ensure previous day is actual series trading day, not stale data
   if prev not in prices[name] or prev in zero_volume.get(name,set()):continue
   eq=cash+sum(p["qty"]*prices[n].get(prev,(0,0,0,p["last"]))[3] for n,p in positions.items())
   budget=min(cash,eq*.2);op=prices[name][d][0];qty=int(budget//op)
   if qty<1:skipped+=1;continue
   cash-=qty*op;positions[name]={"qty":qty,"entry":op,"last":op,"half":False}
   trades.append({"date":d,"name":name,"action":"BUY","shares":qty,"price":op,"reason":entry+" MA200 rising MA50","pnl":""})
  value=cash
  for name,p in positions.items():
   if d in prices[name]:p["last"]=prices[name][d][3]
   value+=p["qty"]*p["last"]
  equity.append((d,round(value,2)))
 # Mark residual positions at end, not fictional closing trades
 peak=10000;maxdd=0
 for _,v in equity:peak=max(peak,v);maxdd=min(maxdd,v/peak-1)
 return {"mode":mode,"entry":entry,"top_n":top_n,"start_capital":10000,"end_equity":equity[-1][1],"return_pct":round((equity[-1][1]/10000-1)*100,2),"max_drawdown_pct":round(maxdd*100,2),"buy_orders":sum(t["action"]=="BUY" for t in trades),"sell_orders":sum(t["action"]=="SELL" for t in trades),"open_positions":{k:v["qty"] for k,v in positions.items()},"skipped_small_orders":skipped},trades,equity
results=[]
for top_n in (3,5,10,15):
 for mode in ("TP30","MA50","HALF"):
  summary,trades,equity=simulate(mode,top_n);results.append(summary)
  for filename,rows,fields in [(mode+"_TOP"+str(top_n)+"_trades.csv",trades,["date","name","action","shares","price","reason","pnl"]),(mode+"_TOP"+str(top_n)+"_equity.csv",[dict(date=d,equity=v) for d,v in equity],["date","equity"])]:
   with (OUT/filename).open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
entry_results=[]
for entry in ("BREAKOUT","PULLBACK_8_15","DEEP_15_25"):
 summary,trades,equity=simulate("MA50",10,entry);entry_results.append(summary)
 for filename,rows,fields in [(entry+"_TOP10_MA50_trades.csv",trades,["date","name","action","shares","price","reason","pnl"]),(entry+"_TOP10_MA50_equity.csv",[dict(date=d,equity=v) for d,v in equity],["date","equity"])]:
  with (OUT/filename).open("w",newline="") as f:
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
(OUT/"entry_comparison.json").write_text(json.dumps({"strategies":entry_results,"rules":{"PULLBACK_8_15":"8-15% below previous 20-day high; close within 5% of MA50; close above prior session high; close > MA200; rising MA50","DEEP_15_25":"Same but 15-25% correction","BREAKOUT":"Original TOP10 MA50 breakout"},"limitations":["Exploratory parameters, not independently validated","No costs, dividends or complete corporate-action adjustment"]},ensure_ascii=False,indent=2))
# Independent WIG benchmark from Stooq. Do not silently substitute WIG20.
def wig_benchmark():
 local=ROOT/"benchmark"/"WIG_daily_2021_2026.csv"
 if local.exists():
  rows=read_csv(local);vals={}
  for row in rows:
   if row.get("<TICKER>")!="WIG" or row.get("<PER>")!="D":continue
   raw=row["<DATE>"];d=raw[:4]+"-"+raw[4:6]+"-"+raw[6:8]
   val=float(row["<CLOSE>"])
   if val>0:vals[d]=val
  dates=sorted(d for d in vals if "2021-06-29"<=d<="2026-10-19")
  if len(dates)<1200:raise ValueError("Uploaded WIG benchmark missing sessions")
  first,last=dates[0],dates[-1]
  return {"status":"ok","source":"User-supplied WIG daily archive","first":first,"last":last,"bars":len(dates),"first_close":vals[first],"last_close":vals[last],"return_pct":round((vals[last]/vals[first]-1)*100,2),"end_equity_10000":round(10000*vals[last]/vals[first],2),"method":"WIG total-return index buy-and-hold, first full session after first ranking through last available WIG close"}
 urls=["https://stooq.pl/q/d/l/?s=wig&d1=20210601&d2=20261021&i=d","https://stooq.com/q/d/l/?s=wig&d1=20210601&d2=20261021&i=d"]
 errors=[]
 for url in urls:
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/csv"})
   with urllib.request.urlopen(req,timeout=25) as resp:raw=resp.read().decode("utf-8-sig")
   rows=list(csv.DictReader(raw.splitlines()))
   values={}
   for row in rows:
    d=row.get("Date") or row.get("Data");v=row.get("Close") or row.get("Zamkniecie")
    if d and v:values[d]=float(v)
   dates=sorted(d for d in values if d>="2021-06-28" and d<="2026-10-20")
   if len(dates)<900:raise ValueError("WIG coverage too short: "+str(len(dates)))
   start=dates[0];end=dates[-1]
   return {"status":"ok","source":url,"first":start,"last":end,"bars":len(dates),"first_close":values[start],"last_close":values[end],"return_pct":round((values[end]/values[start]-1)*100,2),"end_equity_10000":round(10000*values[end]/values[start],2)}
  except Exception as e:errors.append(str(e))
 # Yahoo index fallback (validated exchange index, not WIG20)
 try:
  start=int(dt.datetime(2021,6,1,tzinfo=dt.timezone.utc).timestamp())
  end=int(dt.datetime(2026,10,21,tzinfo=dt.timezone.utc).timestamp())
  url="https://query1.finance.yahoo.com/v8/finance/chart/WIG.WA?period1="+str(start)+"&period2="+str(end)+"&interval=1d"
  req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
  with urllib.request.urlopen(req,timeout=30) as resp:obj=json.load(resp)["chart"]["result"][0]
  from zoneinfo import ZoneInfo
  vals={}
  for ts,close in zip(obj["timestamp"],obj["indicators"]["quote"][0]["close"]):
   if close is None:continue
   day=dt.datetime.fromtimestamp(ts,ZoneInfo("Europe/Warsaw")).date().isoformat()
   vals[day]=float(close)
  dates=sorted(d for d in vals if "2021-06-28"<=d<="2026-10-20")
  if len(dates)<900:raise ValueError("Yahoo WIG coverage too short: "+str(len(dates)))
  first,last=dates[0],dates[-1]
  return {"status":"ok","source":"Yahoo Finance WIG.WA","first":first,"last":last,"bars":len(dates),"first_close":vals[first],"last_close":vals[last],"return_pct":round((vals[last]/vals[first]-1)*100,2),"end_equity_10000":round(10000*vals[last]/vals[first],2)}
 except Exception as e:errors.append("Yahoo WIG.WA: "+str(e))
 return {"status":"unavailable","errors":errors}
benchmark=wig_benchmark()
audit={"backtest_start":all_dates[0],"backtest_end":all_dates[-1],"raw_holiday_rows":sum(len(v) for v in raw_holiday_rows.values()),"holiday_rows_remaining":sum(1 for v in prices.values() for d in v if d.endswith("-01-01") or d.endswith("-12-25") or d.endswith("-12-26")),"corporate_event_flags":corporate_event_flags,"rankings":len(reports),"ranking_size_valid":all(len(r["ranked_companies"])==15 for r in reports),"universe":len(prices),"suspect_january_1_rows":sum(q.get("jan1_rows",0) for q in quality.values()),"suspect_january_1_rows_remaining":sum(1 for v in prices.values() for d in v if d.endswith("-01-01")),"excluded":["BRAND24"],"zero_volume_rows":{k:len(v) for k,v in zero_volume.items() if v},"limitations":["Raw Yahoo files contain holiday placeholders; holiday rows removed from simulation, timestamp alignment still needs independent cross-source verification","TIM has turnover not share volume; zero-turnover sessions not independently identified","Corporate action discontinuities flagged for review, not automatically adjusted; TIM cash settlement not independently verified","No fees, slippage or dividends; WIG is total-return and stock strategies are price-only"]}
(OUT/"audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2))

(OUT/"results.json").write_text(json.dumps({"strategies":results,"benchmark_wig":benchmark,"audit":audit,"caveats":["No fees, slippage or dividend reinvestment; corporate actions flagged but not fully adjusted","Historical rank mapping and Yahoo price adjustments need independent audit","TIM delisting proxy uses last close, not verified cash settlement","Brand24 omitted by user decision","Signals evaluated at prior close; orders filled next opening","Yahoo zero-volume sessions blocked for buys and sells; TIM turnover is not share volume","Yahoo price dates and holiday rows require validation"]},indent=2,ensure_ascii=False))
print(json.dumps(results,indent=2))
