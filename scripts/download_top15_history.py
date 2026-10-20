#!/usr/bin/env python3
"""Download point-in-time TOP15 universe daily OHLCV. Do not silently map uncertain symbols."""
import csv,io,json,time,pathlib,urllib.request,urllib.parse,datetime as dt
NAMES=["11 BIT","4MASS","AMICA","ANSWEAR","ARCTIC PAPER","ARTIFEX MUNDI","ASBIS","BIOCELTIX","BRAND24","BUDIMEX","CAPTOR THERAPEUTICS","CD PROJEKT","CELON PHARMA","CLOUD TECHNOLOGIES","CONSOLEWAY","CREEPY JAR","CREOTECH INSTRUMENTS","CREOTECH QUANTUM","DATAWALK","DEKPOL","DIGITAL NETWORK","ELEKTROTIM","ENTER AIR","EUROTEL","EXCELLENCE","GENOMTEC","GRODNO","GRUPA KĘTY","JSW","K2HOLDING","KINO POLSKA","KRUK","LUBAWA","MAKARONY POLSKIE","MIRBUD","MO-BRUK","MOLECURE","MOSTOSTAL ZABRZE","MOVIE GAMES","NOCTILUCA","NTT SYSTEM","ONCOARENDI THERAPEUTICS","OT LOGISTICS","PASSUS","PLAYWAY","POINTPACK","PRESIDENT STUDIO","PURE BIOLOGICS","QNA TECHNOLOGY","QUERCUS TFI","RAINBOW TOURS","RYVU THERAPEUTICS","SCANWAY","SEVENET","SONKA","SPYROSOFT","STS HOLDING","SUNTECH","SYN2BIO","TIM","TORPOL","VERCOM","VIGO PHOTONICS","WITTCHEN","ŻABKA"]
ALIASES={"11 BIT STUDIOS":"11 BIT","BRAND 24":"BRAND24","CREOTECH":"CREOTECH INSTRUMENTS","ENTER":"ENTER AIR","MAKARONY":"MAKARONY POLSKIE","MOBRUK":"MO-BRUK","MOSTOTAL ZABRZE":"MOSTOSTAL ZABRZE","RAINBOW":"RAINBOW TOURS","RYVU THERAPUETICS":"RYVU THERAPEUTICS","VIGO SYSTEM":"VIGO PHOTONICS"}
KNOWN={"11 BIT":"11B.WA","SONKA":"SOK.WA","CD PROJEKT":"CDR.WA","AMICA":"AMC.WA","BUDIMEX":"BDX.WA","JSW":"JSW.WA","KRUK":"KRU.WA","ASBIS":"ASB.WA","ELEKTROTIM":"ELT.WA","ENTER AIR":"ENT.WA","MIRBUD":"MRB.WA","DATAWALK":"DAT.WA","VERCOM":"VRC.WA","RAINBOW TOURS":"RBW.WA","PLAYWAY":"PLW.WA","CREEPY JAR":"CRJ.WA","TORPOL":"TOR.WA","DEKPOL":"DEK.WA","MO-BRUK":"MBR.WA","ARCTIC PAPER":"ATC.WA","WITTCHEN":"WTN.WA","KINO POLSKA":"KPL.WA","BRAND24":"B24.WA","BIOCELTIX":"BCX.WA","PASSUS":"PAS.WA","CLOUD TECHNOLOGIES":"CLD.WA","CREOTECH INSTRUMENTS":"CRI.WA","SCANWAY":"SCW.WA","LUBAWA":"LBW.WA","GRODNO":"GRN.WA","NTT SYSTEM":"NTT.WA","QUERCUS TFI":"QRS.WA","VIGO PHOTONICS":"VGO.WA","GRUPA KĘTY":"KTY.WA","ARTIFEX MUNDI":"ART.WA","MAKARONY POLSKIE":"MAK.WA","OT LOGISTICS":"OTS.WA","CELON PHARMA":"CLN.WA","MOVIE GAMES":"MOV.WA","SPYROSOFT":"SPR.WA","SUNTECH":"SUN.WA","PURE BIOLOGICS":"PUR.WA","ANSWEAR":"ANR.WA","EUROTEL":"ETL.WA","NOCTILUCA":"NCL.WA","GENOMTEC":"GMT.WA","QNA TECHNOLOGY":"QNA.WA","RYVU THERAPEUTICS":"RVU.WA","DIGITAL NETWORK":"DIG.WA","MOSTOSTAL ZABRZE":"MSZ.WA","4MASS":"4MS.WA","POINTPACK":"PNT.WA","SEVENET":"SEV.WA","PRESIDENT STUDIO":"PST.WA","CAPTOR THERAPEUTICS":"CTX.WA","K2HOLDING":"FAB.WA","MOLECURE":"MOC.WA","TIM":"TIM.WA","STS HOLDING":"STS.WA","ONCOARENDI THERAPEUTICS":"MOC.WA"}
START="2020-01-01"
END="2026-10-21"
def get_json(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
 with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
def fetch(symbol):
 start=int(dt.datetime.fromisoformat(START).replace(tzinfo=dt.timezone.utc).timestamp())
 end=int(dt.datetime.fromisoformat(END).replace(tzinfo=dt.timezone.utc).timestamp())
 url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?period1="+str(start)+"&period2="+str(end)+"&interval=1d"
 obj=get_json(url)["chart"]["result"][0];q=obj["indicators"]["quote"][0]
 rows=[]
 for i,ts in enumerate(obj.get("timestamp",[])):
  vals=[q.get(k,[None]*len(obj["timestamp"]))[i] for k in ("open","high","low","close","volume")]
  if any(v is None for v in vals):continue
  day=dt.datetime.fromtimestamp(ts,dt.timezone.utc).date().isoformat()
  if START<=day<END:rows.append([day,*vals])
 return rows
KNOWN.update({"CONSOLEWAY":"CWA.WA","EXCELLENCE":"EXC.WA","ŻABKA":"ZAB.WA","CREOTECH QUANTUM":"CRQ.WA","SYN2BIO":"S2B.WA","PRESIDENT STUDIO":"PRE.WA"})
def main():
 root=pathlib.Path("data/top15/ohlcv");root.mkdir(parents=True,exist_ok=True)
 status={}
 for name in NAMES:
  symbol=KNOWN.get(name)
  if not symbol:
   status[name]={"status":"unresolved_ticker","reason":"Manual ticker confirmation required"};continue
  try:
   rows=fetch(symbol)
   if len(rows)<20:raise ValueError("Too few bars: "+str(len(rows)))
   with (root/(symbol.replace(".","_")+".csv")).open("w",newline="") as f:
    writer=csv.writer(f);writer.writerow(["date","open","high","low","close","volume"]);writer.writerows(rows)
   status[name]={"status":"ok","ticker":symbol,"bars":len(rows),"first":rows[0][0],"last":rows[-1][0]}
  except Exception as e:status[name]={"status":"error","ticker":symbol,"reason":str(e)}
  print(name,status[name],flush=True);time.sleep(.3)
 pathlib.Path("data/top15/download_status.json").write_text(json.dumps({"start":START,"end_exclusive":END,"aliases":ALIASES,"companies":status},ensure_ascii=False,indent=2)+"\n")
 print("SUCCESS",sum(v["status"]=="ok" for v in status.values()),"OF",len(status))
if __name__=="__main__":main()
