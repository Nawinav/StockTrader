# Stock Suggestion API (FastAPI)

## Endpoints

- `GET /api/suggestions/intraday` - top 10 intraday ideas
- `GET /api/suggestions/longterm` - top 10 long-term ideas
- `GET /api/stocks/{symbol}` - full technical + fundamental breakdown
- `GET /api/watchlist` - list watchlist
- `POST /api/watchlist` - add `{ "symbol": "RELIANCE", "note": "..." }`
- `DELETE /api/watchlist/{symbol}` - remove entry
- Swagger UI at `/docs`

Responses are cached for 10 minutes (configurable via `SUGGESTIONS_TTL_SECONDS`).

## Local dev

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs

## Swapping the data provider

`DATA_PROVIDER=mock` uses deterministic synthetic OHLCV (fine for UI work).
`DATA_PROVIDER=upstox` pulls real NSE candles and LTP via the Upstox v2
API. See the "Upstox setup" section below.

## Upstox setup

Prerequisites: an Upstox developer app (https://upstox.com/developer/).
Register the redirect URL `http://localhost:8000/auth/upstox/callback`
during app creation, then grab the API Key + API Secret.

1. Fill in `backend/.env`:
   ```
   DATA_PROVIDER=upstox
   UPSTOX_API_KEY=<your key>
   UPSTOX_API_SECRET=<your secret>
   UPSTOX_REDIRECT_URI=http://localhost:8000/auth/upstox/callback
   ```
2. Start the API (`uvicorn app.main:app --reload --port 8000`).
3. Open http://localhost:8000/auth/upstox/login in a browser. You will
   be redirected to Upstox, log in, approve, and bounce back to
   `/auth/upstox/callback`. The handler writes the daily access token
   to `backend/upstox_token.json`.
4. Verify with `curl http://localhost:8000/auth/upstox/status` — it
   should report `"ready": true`.
5. Hit `curl http://localhost:8000/api/stocks/RELIANCE` — the `close`
   price in the response should match the live NSE quote.

Upstox tokens expire around 03:30 IST every day; re-run step 3 after
expiry. While `PAPER_TRADING=true` (the default) the client refuses to
place real orders — only market data is live.

If any symbol's ISIN in `app/data/instruments.py` is stale, download
the Upstox instruments CSV and point at it via
`UPSTOX_INSTRUMENTS_PATH=/path/to/complete.csv` to override.

## Deploy to Render

A `render.yaml` is included. Either:

1. Connect the repo in the Render dashboard and click "New from Blueprint".
2. Or point a new Web Service at this folder, set build =
   `pip install -r requirements.txt` and start =
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

After deployment set `CORS_ORIGINS` to your Vercel URL.
