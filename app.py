from flask import Flask, jsonify, Response

import requests

from datetime import datetime, timedelta, timezone

app = Flask(__name__)

COINS = {

    "BTC": "BTC-USD",

    "ETH": "ETH-USD",

    "XRP": "XRP-USD",

    "SOL": "SOL-USD",

    "DOGE": "DOGE-USD",

}

SESSION = requests.Session()

SESSION.headers.update({"User-Agent": "CryptoPulse/1.0"})

PAGE = """

<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta name="viewport" content="width=device-width, initial-scale=1">

<meta name="theme-color" content="#090e19">

<title>Crypto Pulse</title>

<style>

*{box-sizing:border-box}

body{margin:0;background:#090e19;color:#f4f7ff;

font-family:-apple-system,BlinkMacSystemFont,Arial,sans-serif;padding:22px}

header,main,footer{max-width:900px;margin-left:auto;margin-right:auto}

header{padding-top:12px}

.eyebrow{color:#58e6ae;font-size:12px;font-weight:800;letter-spacing:2px}

h1{font-size:30px;margin:10px 0}

.sub{color:#95a5bc;font-size:14px;line-height:1.6}

.topline{display:flex;justify-content:space-between;align-items:center;gap:10px}

button{background:#20334b;color:white;border:1px solid #354963;

border-radius:10px;padding:11px 14px;font-weight:700}

.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));

gap:12px;margin-top:24px}

.card{background:#131c2b;border:1px solid #29384d;border-radius:17px;

padding:16px;min-width:0}

.coin{font-size:13px;font-weight:800;color:#a8bad0}

.price{font-size:clamp(20px,5vw,28px);font-weight:800;

margin:15px 0 7px;overflow-wrap:anywhere}

.change{font-size:13px;color:#a8bad0;line-height:1.5}

.badge{display:inline-block;margin-top:17px;padding:8px 11px;

border-radius:8px;font-size:12px;font-weight:900;letter-spacing:1px}

.YES{background:#123d32;color:#64e8b4}

.NO{background:#48212a;color:#ff929e}

.WAIT{background:#3d331d;color:#ffdb7b}

.err{color:#ff929e;font-size:12px;margin-top:8px}

footer{color:#8595ac;font-size:12px;line-height:1.7;margin-top:24px}

@media(min-width:650px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}

</style>

</head>

<body>

<header>

  <div class="topline">

    <div class="eyebrow">● MARKET WATCH</div>

    <button onclick="refreshData()">Refresh ↻</button>

  </div>

  <h1>CRYPTO PULSE</h1>

  <div class="sub">Live spot prices · 15-minute momentum · No automatic trading</div>

</header>

<main>

  <div class="grid" id="grid">

    <section class="card">Loading market data…</section>

  </div>

</main>

<footer>

  <div id="updated">Connecting to Coinbase…</div>

  <p>YES means upward momentum; NO means downward momentum;

  WAIT means the movement is small or data is unavailable.</p>

  <p>Signals are experimental and are not predictions or financial advice.

  These are Coinbase spot prices, not Kalshi contract quotes or probabilities.

  No trades are placed.</p>

</footer>

<script>

function usd(n){

  return n.toLocaleString("en-US",{

    style:"currency",currency:"USD",

    minimumFractionDigits:n<1?4:2,maximumFractionDigits:n<1?6:2

  });

}

async function refreshData(){

  const grid=document.getElementById("grid");

  try{

    const response=await fetch("/api/data",{cache:"no-store"});

    if(!response.ok) throw new Error("Data request failed");

    const result=await response.json();

    grid.innerHTML=result.items.map(c=>`

      <section class="card">

        <div class="coin">${c.coin} <span style="color:#687c96">/ USD</span></div>

        <div class="price">${c.price===null?"Unavailable":usd(c.price)}</div>

        <div class="change">${

          c.change===null?"15m change unavailable":

          (c.change>0?"+":"")+c.change.toFixed(3)+"% over 15m"

        }</div>

        <div class="badge ${c.signal}">${c.signal}</div>

        ${c.error?'<div class="err">Price feed temporarily unavailable</div>':""}

      </section>

    `).join("");

    document.getElementById("updated").textContent=

      "Last checked: "+new Date().toLocaleTimeString();

  }catch(e){

    document.getElementById("updated").textContent=

      "Could not load data. Retrying automatically.";

  }

}

refreshData();

setInterval(refreshData,10000);

</script>

</body>

</html>

"""

@app.get("/")

def home():

    return Response(PAGE, mimetype="text/html")

def coin_data(coin, product):

    try:

        now = datetime.now(timezone.utc)

        start = now - timedelta(minutes=20)

        url = f"https://api.exchange.coinbase.com/products/{product}"

        ticker_response = SESSION.get(url + "/ticker", timeout=8)

        ticker_response.raise_for_status()

        price = float(ticker_response.json()["price"])

        candles_response = SESSION.get(

            url + "/candles",

            params={

                "start": start.isoformat(timespec="seconds"),

                "end": now.isoformat(timespec="seconds"),

                "granularity": 60,

            },

            timeout=8,

        )

        candles_response.raise_for_status()

        candles = candles_response.json()

        # Coinbase candle rows: [time, low, high, open, close, volume]

        candles = [

            row for row in candles

            if isinstance(row, list) and len(row) >= 5

        ]

        change = None

        if candles:

            target = int((now - timedelta(minutes=15)).timestamp())

            candle = min(candles, key=lambda row: abs(row[0] - target))

            old_price = float(candle[4])

            if old_price > 0:

                change = (price / old_price - 1) * 100

        if change is None:

            signal = "WAIT"

        elif change >= 0.10:

            signal = "YES"

        elif change <= -0.10:

            signal = "NO"

        else:

            signal = "WAIT"

        return {

            "coin": coin,

            "price": price,

            "change": change,

            "signal": signal,

            "error": False,

        }

    except (requests.RequestException, ValueError, KeyError, TypeError):

        return {

            "coin": coin,

            "price": None,

            "change": None,

            "signal": "WAIT",

            "error": True,

        }

@app.get("/api/data")

def api_data():

    return jsonify({

        "items": [

            coin_data(coin, product)

            for coin, product in COINS.items()

        ]

    })

if __name__ == "__main__":

    app.run(host="0.0.0.0", port=10000)
