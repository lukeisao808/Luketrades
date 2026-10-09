import os
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template

app = Flask(__name__)

COINS = [
    {"symbol": "BTC", "name": "Bitcoin", "product": "BTC-USD"},
    {"symbol": "ETH", "name": "Ethereum", "product": "ETH-USD"},
    {"symbol": "XRP", "name": "XRP", "product": "XRP-USD"},
    {"symbol": "SOL", "name": "Solana", "product": "SOL-USD"},
    {"symbol": "DOGE", "name": "Dogecoin", "product": "DOGE-USD"},
]
COINBASE = "https://api.exchange.coinbase.com"
CACHE_SECONDS = 8
_cache = {"at": 0, "data": None}


def get_coin_data(coin):
    headers = {"User-Agent": "LuketradesDashboard/1.0"}
    product = coin["product"]
    ticker = requests.get(
        f"{COINBASE}/products/{product}/ticker",
        headers=headers,
        timeout=8,
    )
    ticker.raise_for_status()
    current = float(ticker.json()["price"])

    candles_response = requests.get(
        f"{COINBASE}/products/{product}/candles",
        params={"granularity": 60},
        headers=headers,
        timeout=8,
    )
    candles_response.raise_for_status()
    candles = candles_response.json()
    # Coinbase returns candles newest first: [time, low, high, open, close, volume]
    closes = [float(row[4]) for row in sorted(candles, key=lambda row: row[0])]
    if len(closes) >= 6 and closes[-6] != 0:
        change = (current - closes[-6]) / closes[-6] * 100
    elif len(closes) >= 2 and closes[-2] != 0:
        change = (current - closes[-2]) / closes[-2] * 100
    else:
        change = 0.0

    if change > 0.04:
        signal = "YES"
        detail = "Short-term momentum up"
    elif change < -0.04:
        signal = "NO"
        detail = "Short-term momentum down"
    else:
        signal = "WAIT"
        detail = "No clear short-term move"

    return {
        "symbol": coin["symbol"],
        "name": coin["name"],
        "price": current,
        "change": change,
        "signal": signal,
        "detail": detail,
        "source": "Coinbase",
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/data")
def api_data():
    now = time.time()
    if _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return jsonify(_cache["data"])

    results = []
    errors = []
    for coin in COINS:
        try:
            results.append(get_coin_data(coin))
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append(f'{coin["symbol"]}: price feed temporarily unavailable')
            results.append({
                "symbol": coin["symbol"],
                "name": coin["name"],
                "price": None,
                "change": None,
                "signal": "WAIT",
                "detail": "Waiting for price feed",
                "source": "Coinbase",
            })

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "coins": results,
        "notice": "Signals are simple momentum indicators, not predictions or financial advice. They are not Kalshi prices or verified probabilities.",
        "errors": errors,
    }
    _cache["at"] = now
    _cache["data"] = payload
    return jsonify(payload)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
