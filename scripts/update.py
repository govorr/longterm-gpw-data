#!/usr/bin/env python3
"""Daily Yahoo Finance GPW OHLCV screening. Not an order execution system."""
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo
from statistics import mean

STOCKS = {
    "CRI": "Creotech Instruments",
    "ASB": "ASBIS",
    "CRQ": "Creotech Quantum",
    "DIG": "Digital Network",
    "LBW": "Lubawa",
    "CLD": "Cloud Technologies",
    "GRN": "Grodno",
    "ELT": "Elektrotim",
    "BCX": "Bioceltix",
    "S2B": "Syn2Bio",
    "DAT": "DataWalk",
    "QNA": "QNA Technology",
    "SEV": "Sevenet",
    "PAS": "Passus",
    "SON": "Sonka",
}
# Alternative tickers are not silently guessed. Failed lookup blocks publication.
def fetch(symbol):
    ticker = symbol + ".WA"
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + ticker + "?" + urllib.parse.urlencode({
        "range": "2y", "interval": "1d",
    })
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                body = json.load(response)
            result = body["chart"]["result"][0]
            if result["meta"].get("currency") != "PLN":
                raise ValueError("Currency is not PLN")
            quote = result["indicators"]["quote"][0]
            rows = []
            for i, stamp in enumerate(result["timestamp"]):
                fields = [quote[k][i] for k in ("open", "high", "low", "close", "volume")]
                if any(v is None for v in fields):
                    continue
                date = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat()
                rows.append(dict(date=date, open=fields[0], high=fields[1], low=fields[2],
                                 close=fields[3], volume=fields[4]))
            rows = list({row["date"]: row for row in rows}.values())
            rows.sort(key=lambda r: r["date"])
            return rows
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise error
            time.sleep(2 * (attempt + 1))

def metrics(rows):
    if not rows:
        raise ValueError("No OHLCV candles")
    if len(rows) < 201:
        last = rows[-1]
        return {"date": last["date"], "close": round(last["close"], 4),
                "volume": int(last["volume"]), "ma50": None, "ma200": None,
                "atr14": None, "previous_20d_high": None,
                "technical_buy_candidate": False, "history_sessions": len(rows),
                "note": "Insufficient history for MA200; no buy signal"}
    closes = [r["close"] for r in rows]
    true_ranges = []
    for i, r in enumerate(rows):
        previous = closes[i - 1] if i else closes[0]
        true_ranges.append(max(r["high"] - r["low"], abs(r["high"] - previous), abs(r["low"] - previous)))
    ma50 = mean(closes[-50:])
    ma50_prev = mean(closes[-51:-1])
    ma200 = mean(closes[-200:])
    atr14 = mean(true_ranges[-14:])
    prev20_high = max(r["high"] for r in rows[-21:-1])
    last = rows[-1]
    return {
        "date": last["date"],
        "close": round(last["close"], 4),
        "volume": int(last["volume"]),
        "ma50": round(ma50, 4),
        "ma200": round(ma200, 4),
        "atr14": round(atr14, 4),
        "previous_20d_high": round(prev20_high, 4),
        "technical_buy_candidate": bool(last["close"] > ma200 and ma50 > ma50_prev and last["close"] > prev20_high),
        "history_sessions": len(rows),
    }

def main():
    data = {"source": "Yahoo Finance chart API (unofficial)", "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "strategy": "Longterm TOP 15 – technical screen only", "stocks": {}, "errors": {}}
    for symbol, name in STOCKS.items():
        try:
            row = metrics(fetch(symbol))
            data["stocks"][symbol] = {"name": name, "yahoo_ticker": symbol + ".WA", **row}
            print(symbol, row["date"], row["close"], "BUY_SCREEN" if row["technical_buy_candidate"] else "NONE", flush=True)
        except Exception as exc:
            data["errors"][symbol] = str(exc)
            print("ERROR", symbol, type(exc).__name__, exc, file=sys.stderr, flush=True)
    if data["errors"]:
        sys.exit("ERROR: invalid/missing symbols; NOT publishing incomplete snapshot: " + json.dumps(data["errors"]))
    dates = {item["date"] for item in data["stocks"].values()}
    if len(dates) != 1:
        sys.exit("ERROR: inconsistent final bar dates; NOT publishing: " + repr(dates))
    last_day = dt.date.fromisoformat(next(iter(dates)))
    today_warsaw = dt.datetime.now(ZoneInfo("Europe/Warsaw")).date()
    if today_warsaw.weekday() < 5 and last_day != today_warsaw:
        sys.exit("ERROR: latest session not from today; NOT publishing: " + last_day.isoformat())
    if (today_warsaw - last_day).days > 4:
        sys.exit("ERROR: stale data; NOT publishing")
    data["session_date"] = last_day.isoformat()
    pathlib.Path("docs").mkdir(exist_ok=True)
    pathlib.Path("docs/latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SUCCESS: verified data for 15 symbols", data["session_date"])

if __name__ == "__main__":
    main()
