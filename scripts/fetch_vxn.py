#!/usr/bin/env python3
"""Fetch latest VXN close from Yahoo Finance and write vxn.json"""
import json, urllib.request, os, sys
from datetime import datetime, timezone

def get_yahoo_price(symbol):
    """Fetch latest close from Yahoo Finance v8 chart API"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    result = data["chart"]["result"][0]
    meta = result.get("meta", {})

    price = meta.get("regularMarketPrice")
    ts = meta.get("regularMarketTime")

    if price is None:
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        closes = quotes.get("close", [])
        timestamps = result.get("timestamp", [])
        for i in range(len(closes) - 1, -1, -1):
            if closes[i] is not None:
                price = closes[i]
                ts = timestamps[i] if i < len(timestamps) else None
                break

    if price is None:
        price = meta.get("chartPreviousClose")
        ts = None

    if price is None:
        raise ValueError("No price found")

    date = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "unknown"
    return round(price, 2), date


def main():
    vxn, date, source = None, None, None

    # 1. Try ^VXN
    try:
        vxn, date = get_yahoo_price("%5EVXN")
        source = "yahoo_^VXN"
        print(f"VXN={vxn} ({date})")
    except Exception as e:
        print(f"VXN failed: {e}")

    # 2. Fallback: ^VIX + estimate
    if vxn is None:
        try:
            vix, date = get_yahoo_price("%5EVIX")
            vxn = round(vix + 4.0, 1)
            source = "yahoo_^VIX+estimate"
            print(f"VIX={vix} -> VXN≈{vxn} ({date})")
        except Exception as e:
            print(f"All sources failed: {e}")
            sys.exit(0)  # Exit cleanly, no update

    # 3. Write vxn.json
    output = {
        "vxn": vxn, "date": date,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source
    }
    with open("vxn.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"Written: VXN={vxn}")


if __name__ == "__main__":
    main()
