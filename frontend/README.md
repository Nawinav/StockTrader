# Stock Suggestion Frontend (Next.js 14)

## Local dev

```bash
cd frontend
npm install
cp .env.example .env.local
# edit NEXT_PUBLIC_API_BASE_URL to point at your FastAPI backend
npm run dev
```

Open http://localhost:3000.

## Pages

- `/` — dashboard with Intraday / Long-term toggle, top 10 ranked cards, 10-minute auto-refresh countdown.
- `/watchlist` — add/remove NSE symbols, attach a note.

## Deploy to Vercel

1. Import the repo in Vercel; set the root directory to `frontend`.
2. Set the environment variable `NEXT_PUBLIC_API_BASE_URL` to your Render backend URL, e.g. `https://stock-suggestion-api.onrender.com`.
3. Vercel auto-detects Next.js — no other config needed.

After the first deploy, copy the Vercel URL and set `CORS_ORIGINS` on the Render backend to it.
