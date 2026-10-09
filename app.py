
import os
import time
import math
import re
import requests
from datetime import datetime, timezone, timedelta

# ==========================================
# ⚡ CRYPTO PULSE
# ==========================================

REFRESH = 10
CANDLE = 300
HISTORY_DAYS = 7
MIN_CONFIDENCE = 0.56
MIN_EDGE = 0.06
MIN_ENTRY = 5
MAX_ENTRY = 95
MAX_SPREAD = 15

COINS = {
    "BTC":  {"name": "Bitcoin",  "product": "BTC-USD",  "series": "KXBTC15M", "icon": "₿"},
    "ETH":  {"name": "Ethereum", "product": "ETH-USD",  "series": "KXETH15M", "icon": "Ξ"},
    "XRP":  {"name": "XRP",      "product": "XRP-USD",  "series": "KXXRP15M", "icon": "✕"},
    "SOL":  {"name": "Solana",   "product": "SOL-USD",  "series": "KXSOL15M", "icon": "◎"},
    "DOGE": {"name": "Dogecoin", "product": "DOGE-USD", "series": "KXDOGE15M", "icon": "Ð"},
}

CB = "https://api.exchange.coinbase.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"

# Terminal colors
G = "\033[92m"
R = "\033[91m"
Y = "\033[93m"
C = "\033[96m"
W = "\033[97m"
M = "\033[90m"
B = "\033[1m"
X = "\033[0m"

http = requests.Session()
http.headers.update({"User-Agent": "CryptoPulse/1.0"})


# ==========================================
# DATA
# ==========================================

def get_json(url, params=None):
    response = http.get(url, params=params, timeout=12)
    response.raise_for_status()
    return response.json()


def pct(new, old):
    return (new / old - 1) * 100 if old else 0.0


def fetch_history(product, days=HISTORY_DAYS):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    candles = {}
    cursor = start

    while cursor < now:
        end = min(cursor + timedelta(seconds=CANDLE * 280), now)
        try:
            rows = get_json(
                f"{CB}/products/{product}/candles",
                {
                    "granularity": CANDLE,
                    "start": cursor.isoformat(),
                    "end": end.isoformat()
                }
            )
            for row in rows:
                if len(row) >= 6:
                    candles[int(row[0])] = {
                        "time": int(row[0]),
                        "low": float(row[1]),
                        "high": float(row[2]),
                        "open": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5])
                    }
        except Exception:
            pass

        cursor = end
        time.sleep(0.08)

    cutoff = int(now.timestamp()) // CANDLE * CANDLE
    return [
        candles[t] for t in sorted(candles)
        if t + CANDLE <= cutoff
    ]


def fetch_candles(product):
    try:
        rows = get_json(
            f"{CB}/products/{product}/candles",
            {"granularity": CANDLE}
        )
        cutoff = int(datetime.now(timezone.utc).timestamp()) // CANDLE * CANDLE
        result = []

        for row in rows:
            if len(row) < 6:
                continue
            timestamp = int(row[0])
            if timestamp + CANDLE > cutoff:
                continue

            result.append({
                "time": timestamp,
                "low": float(row[1]),
                "high": float(row[2]),
                "open": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5])
            })

        return sorted(result, key=lambda item: item["time"])
    except Exception:
        return []


def fetch_price(product):
    try:
        data = get_json(f"{CB}/products/{product}/ticker")
        return float(data["price"])
    except Exception:
        return None


def chart_info(candles, live_price):
    if len(candles) < 8 or live_price is None:
        return None

    closes = [c["close"] for c in candles]
    ch5 = pct(live_price, closes[-2])
    ch15 = pct(live_price, closes[-4])
    ch30 = pct(live_price, closes[-7])

    ma3 = sum(closes[-3:]) / 3
    ma7 = sum(closes[-7:]) / 7
    momentum = ch5 * .25 + ch15 * .45 + ch30 * .30

    if ma3 > ma7 and momentum > 0:
        trend = "BULLISH"
    elif ma3 < ma7 and momentum < 0:
        trend = "BEARISH"
    else:
        trend = "MIXED"

    return {
        "price": live_price,
        "ch5": ch5,
        "ch15": ch15,
        "ch30": ch30,
        "trend": trend
    }


# ==========================================
# SIMPLE HISTORICAL MODEL
# ==========================================

def features(candles, i):
    if i < 7:
        return None

    closes = [c["close"] for c in candles]
    r1 = pct(closes[i], closes[i-1])
    r3 = pct(closes[i], closes[i-3])
    r6 = pct(closes[i], closes[i-6])

    changes = [
        pct(closes[j], closes[j-1])
        for j in range(i-5, i+1)
    ]
    volatility = math.sqrt(
        sum(v*v for v in changes) / len(changes)
    )

    body = pct(candles[i]["close"], candles[i]["open"])
    recent = candles[i-5:i+1]
    spread = pct(
        max(c["high"] for c in recent),
        min(c["low"] for c in recent)
    )

    return [r1, r3, r6, volatility, body, spread]


class Model:
    def __init__(self):
        self.w = [0.0] * 6
        self.b = 0.0
        self.ready = False
        self.accuracy = None

    def probability(self, f):
        z = self.b + sum(a*b for a, b in zip(self.w, f))
        z = max(-25, min(25, z))
        return 1 / (1 + math.exp(-z))

    def train(self, candles):
        samples = []

        for i in range(7, len(candles)-3):
            f = features(candles, i)
            if f is None:
                continue
            label = int(candles[i+3]["close"] > candles[i]["close"])
            samples.append((f, label))

        if len(samples) < 100:
            return False

        split = int(len(samples) * .8)
        training = samples[:split]
        testing = samples[split:]

        self.w = [0.0] * 6
        self.b = 0.0

        for _ in range(180):
            gw = [0.0] * 6
            gb = 0.0

            for f, label in training:
                error = self.probability(f) - label
                for j in range(6):
                    gw[j] += error * f[j]
                gb += error

            n = max(1, len(training))
            for j in range(6):
                self.w[j] -= .02 * (gw[j]/n + .002*self.w[j])
            self.b -= .02 * gb/n

        if testing:
            correct = sum(
                int((self.probability(f) >= .5) == bool(label))
                for f, label in testing
            )
            self.accuracy = correct / len(testing)

        self.ready = True
        return True

    def predict(self, candles):
        if not self.ready or len(candles) < 8:
            return None
        f = features(candles, len(candles)-1)
        return self.probability(f) if f else None


# ==========================================
# KALSHI
# ==========================================

def markets(series):
    try:
        data = get_json(
            f"{KALSHI}/markets",
            {"series_ticker": series, "status": "open", "limit": 100}
        )
        return data.get("markets", [])
    except Exception:
        return []


def market_description(m):
    return " ".join(str(m.get(k, "")) for k in (
        "title", "subtitle", "yes_sub_title",
        "no_sub_title", "ticker"
    )).lower()


def is_direction_market(m):
    text = re.sub(r"[^a-z0-9]+", " ", market_description(m))
    return (
        "up or down" in text
        or "higher or lower" in text
        or "up down" in text
        or "higher lower" in text
    )


def cents(m, field):
    value = m.get(field + "_dollars")
    if value is not None:
        try:
            return round(float(value) * 100)
        except (ValueError, TypeError):
            pass

    value = m.get(field)
    try:
        return round(float(value)) if value is not None else None
    except (ValueError, TypeError):
        return None


def market_ask(m, side):
    direct = cents(m, side + "_ask")
    if direct is not None:
        return direct

    other = "no" if side == "yes" else "yes"
    opposite_bid = cents(m, other + "_bid")
    return 100 - opposite_bid if opposite_bid is not None else None


def seconds_left(m):
    end = m.get("close_time") or m.get("expiration_time")
    if not end:
        return None
    try:
        dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (dt - datetime.now(timezone.utc)).total_seconds()
    except Exception:
        return None


def get_signal(coin, p_up):
    choices = []

    for m in markets(coin["series"]):
        if not is_direction_market(m):
            continue

        left = seconds_left(m)
        if left is not None and left < 30:
            continue

        for side, prob in (("yes", p_up), ("no", 1-p_up)):
            entry = market_ask(m, side)
            if entry is None or not MIN_ENTRY <= entry <= MAX_ENTRY:
                continue

            bid = cents(m, side + "_bid")
            spread = entry - bid if bid is not None else None
            if spread is not None and not 0 <= spread <= MAX_SPREAD:
                continue

            edge = prob - entry / 100
            if prob >= MIN_CONFIDENCE and edge >= MIN_EDGE:
                choices.append({
                    "status": side.upper(),
                    "entry": entry,
                    "edge": edge,
                    "spread": spread,
                    "left": left,
                    "title": m.get("title", "Directional market")
                })

    if choices:
        return max(choices, key=lambda item: item["edge"])

    return {
        "status": "WAIT",
        "entry": None,
        "edge": None,
        "spread": None,
        "left": None,
        "title": "No qualifying setup"
    }


# ==========================================
# CLEAN DASHBOARD
# ==========================================

def money(price):
    if price >= 1000:
        return f"${price:,.0f}"
    if price >= 1:
        return f"${price:,.2f}"
    return f"${price:.4f}"


def dashboard(results, errors, models):
    print("\033[2J\033[H", end="")

    print(C + B + "╭──────────────────────────────╮")
    print("│         ⚡ CRYPTO PULSE       │")
    print("╰──────────────────────────────╯" + X)
    print(M + "          15-MIN SIGNAL SCANNER" + X)
    print(f"  🕒 {datetime.now().strftime('%H:%M:%S')}  •  {G}● LIVE{X}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    for symbol, coin in COINS.items():
        item = results.get(symbol)

        if not item:
            print(f"  {coin['icon']}  {B}{symbol}{X}")
            print(f"     {Y}🟡 WAIT{X}  {M}{errors.get(symbol, 'Loading...')[:35]}{X}")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            continue

        status = item["signal"]["status"]
        chart = item["chart"]

        if status == "YES":
            color, emoji, trend = G, "🟢", "↗"
        elif status == "NO":
            color, emoji, trend = R, "🔴", "↘"
        else:
            color, emoji, trend = Y, "🟡", "→"

        print(color + "╭──────────────────────────────╮" + X)
        print(color + f"│ {coin['icon']} {symbol:<5}      {emoji} {status:<6}     │" + X)
        print(color + "├──────────────────────────────┤" + X)
        print(color + f"│  {money(chart['price']):<14} {trend} {chart['trend']:<8} │" + X)
        print(color + f"│  15m change  {chart['ch15']:+.2f}%".ljust(31) + "│" + X)

        signal = item["signal"]
        if signal["entry"] is not None:
            line = f"│  Entry {signal['entry']}¢  •  Edge {signal['edge']*100:+.0f}%"
        else:
            line = "│  Entry —  •  No setup"

        print(color + line.ljust(31) + "│" + X)
        print(color + "╰──────────────────────────────╯" + X)

    print()
    print(M + f"  ↻ Refreshes every {REFRESH} seconds" + X)
    print(M + "  Signal estimates only • No auto-trading" + X)
    print(M + "  Prices/signals require a live connection." + X)


# ==========================================
# MAIN LOOP
# ==========================================

def main():
    models = {}
    trained = {}

    print("⚡ CRYPTO PULSE")
    print("Training models from historical candles...\n")

    for symbol, coin in COINS.items():
        model = Model()
        try:
            history = fetch_history(coin["product"])
            if model.train(history):
                models[symbol] = model
                trained[symbol] = time.time()
                print(f"✓ {symbol} ready")
            else:
                models[symbol] = None
                print(f"! {symbol}: insufficient history")
        except Exception as e:
            models[symbol] = None
            print(f"! {symbol}: {str(e)[:60]}")

    while True:
        results = {}
        errors = {}

        for symbol, coin in COINS.items():
            try:
                candles = fetch_candles(coin["product"])
                price = fetch_price(coin["product"])
                chart = chart_info(candles, price)
                model = models.get(symbol)

                if chart is None:
                    errors[symbol] = "Chart data unavailable"
                    continue

                if model is None or not model.ready:
                    errors[symbol] = "Model needs more history"
                    continue

                p_up = model.predict(candles)
                if p_up is None:
                    errors[symbol] = "Prediction unavailable"
                    continue

                signal = get_signal(coin, p_up)
                results[symbol] = {"chart": chart, "signal": signal}

                if time.time() - trained.get(symbol, 0) > 21600:
                    updated = Model()
                    history = fetch_history(coin["product"])
                    if updated.train(history):
                        models[symbol] = updated
                        trained[symbol] = time.time()

            except Exception as e:
                errors[symbol] = f"{type(e).__name__}: {str(e)[:40]}"

        dashboard(results, errors, models)
        time.sleep(REFRESH)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCrypto Pulse stopped.")
