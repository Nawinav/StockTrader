# Stock Suggestion Dashboard

Top-10 intraday and long-term NSE stock ideas, refreshed every 10 minutes, based on a blended technical + fundamental score. The app includes a watchlist and a paper-trading flow, with Upstox integration available later when you want to move beyond the free demo setup.

## Architecture

```text
Frontend (Next.js 14 on Vercel)
  -> calls ->
Backend (FastAPI on Render)
  -> uses ->
Scoring engine + mock/live data provider
```

## Layout

```text
stock-trading/
|-- backend/     FastAPI service
|-- frontend/    Next.js app
|-- DEPLOYMENT.md
`-- ROADMAP.md
```

## Quickstart

```bash
# 1. Backend
cd backend
python -m venv .venv
# Activate the virtual environment for your shell
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Visit `http://localhost:3000`.

## Free deployment preset

For a zero-cost deployment, use:

- `backend/.env.render.example` for the Render backend environment
- `frontend/.env.vercel.example` for the Vercel frontend environment

This preset keeps the app on:

- `DATA_PROVIDER=mock`
- `ANALYZER_PROVIDER=stub`
- `PAPER_TRADING=true`

So you can deploy without paid APIs or broker credentials.

## How the scoring works

For every stock in the universe the engine computes:

- `Technical score (0..100)` from RSI, MACD cross, SMA trend stack, volume ratio, and ATR volatility
- `Fundamental score (0..100)` from ROE, growth, P/E, debt-to-equity, dividend yield, and promoter holding
- `Composite score` with horizon-specific weighting

Intraday ranking surfaces the strongest directional conviction. Long-term ranking favors the highest absolute composite score.

## See also

- [DEPLOYMENT.md](./DEPLOYMENT.md) - detailed free deployment guide for Render + Vercel
- [ROADMAP.md](./ROADMAP.md) - Upstox integration, paper trading, and live-capital path
- [backend/README.md](./backend/README.md)
- [frontend/README.md](./frontend/README.md)

## Disclaimer

This is a personal learning and prototyping project.
It is not investment advice.
Keep `PAPER_TRADING=true` until you have reviewed the live-trading flow end-to-end.
