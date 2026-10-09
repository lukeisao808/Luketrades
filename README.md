# Luketrades Crypto Pulse web app

## Render settings
- Runtime: Python 3
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

## Files
- `app.py`
- `requirements.txt`
- `templates/index.html`

The app displays Coinbase spot prices and a simple short-term momentum indicator. It does not fetch Kalshi contract prices or place trades. Signals are experimental and not financial advice.
