# Deployment Guide

This repository is already structured for the simplest free deployment split:

- `frontend/` -> Vercel Hobby
- `backend/` -> Render Free Web Service

That is the recommended no-cost setup for this codebase because:

- the frontend is a standard Next.js 14 app
- the backend is a real FastAPI server with background tasks
- the backend writes local state files (`watchlist.json`, `trading_state.json`, `upstox_token.json`)

## What the free deployment will include

The free-safe production preset in this repo keeps the app in a low-cost, no-secrets-required mode:

- `DATA_PROVIDER=mock`
- `ANALYZER_PROVIDER=stub`
- `PAPER_TRADING=true`

That means:

- the dashboard deploys and works without Upstox credentials
- the analyzer works without Anthropic billing
- no real trades are placed

## Important limitations before you deploy

The backend currently stores watchlist and trading state in local JSON files.
On Render free services, the filesystem is ephemeral, so these files reset whenever the service restarts, redeploys, or spins down.

For this reason, the free deployment is best treated as:

- a demo deployment
- a personal preview
- a paper-trading sandbox

It is not durable storage.

## Files added for deployment

Use these templates when filling the hosting dashboards:

- `backend/.env.render.example`
- `frontend/.env.vercel.example`

## Step 1: Push the repo to GitHub

Both Vercel and Render deploy from Git repositories, so first make sure this project is in GitHub.

Example:

```bash
git init
git add .
git commit -m "Prepare stock trading app for free deployment"
```

Then create a GitHub repository and push this folder.

## Step 2: Deploy the backend to Render

### Recommended method: Render Blueprint

This repo already contains `backend/render.yaml`.

In Render:

1. Sign in to Render.
2. Click `New`.
3. Choose `Blueprint`.
4. Connect your GitHub account if Render asks.
5. Select this repository.
6. Render will detect `backend/render.yaml`.
7. Confirm the new service creation.

Render will create one Python web service with:

- root directory: `backend`
- plan: `free`
- build command: `pip install -r requirements.txt`
- start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- health check path: `/health`

### Environment values to set in Render

Open the created service, then go to `Environment`.

Set or confirm these values:

```env
ENVIRONMENT=production
SUGGESTIONS_TTL_SECONDS=600
DATA_PROVIDER=mock
PAPER_TRADING=true
ANALYZER_PROVIDER=stub
WATCHLIST_PATH=watchlist.json
APP_FRONTEND_URL=https://your-project-name.vercel.app
```

Leave these blank for the free deploy path:

```env
UPSTOX_API_KEY=
UPSTOX_API_SECRET=
UPSTOX_REDIRECT_URI=
UPSTOX_ACCESS_TOKEN=
UPSTOX_MOBILE=
UPSTOX_PIN=
UPSTOX_TOTP_SECRET=
ANTHROPIC_API_KEY=
NTFY_TOPIC=
```

### About `CORS_ORIGINS`

The backend already allows any `https://*.vercel.app` origin through `allow_origin_regex` in `backend/app/main.py`.

So if you use the default Vercel domain, you can leave `CORS_ORIGINS` empty.

Only set `CORS_ORIGINS` when:

- you attach a custom frontend domain later
- you want to explicitly restrict allowed origins

Example for a custom domain:

```env
CORS_ORIGINS=https://stocks.example.com
```

### Get the backend URL

Once Render finishes deploying, copy the public URL. It will look like:

```text
https://stock-suggestion-api.onrender.com
```

Test it in the browser or with curl:

```bash
curl https://stock-suggestion-api.onrender.com/health
```

Expected response:

```json
{"status":"ok"}
```

## Step 3: Deploy the frontend to Vercel

In Vercel:

1. Sign in to Vercel.
2. Click `Add New`.
3. Choose `Project`.
4. Import the GitHub repository.
5. Set `Root Directory` to `frontend`.
6. Let Vercel detect the framework as Next.js.

### Environment value to set in Vercel

Before clicking deploy, add:

```env
NEXT_PUBLIC_API_BASE_URL=https://your-backend-name.onrender.com
```

Use the exact Render URL from Step 2.

Then deploy.

Vercel will give you a production URL like:

```text
https://your-project-name.vercel.app
```

## Step 4: Final backend environment update

Go back to Render and update:

```env
APP_FRONTEND_URL=https://your-project-name.vercel.app
```

This value is used in notification deep-links and should match the real frontend URL.

If you stay on the default `*.vercel.app` domain, you do not need any CORS change.

After saving, Render may trigger a redeploy. That is normal.

## Step 5: Verify the live application

Check the API directly first:

```bash
curl https://your-backend-name.onrender.com/
curl https://your-backend-name.onrender.com/health
curl https://your-backend-name.onrender.com/api/suggestions/intraday
curl https://your-backend-name.onrender.com/api/suggestions/longterm
```

Then open the Vercel site and verify:

1. The homepage loads.
2. Intraday suggestions render.
3. Long-term suggestions render.
4. A stock details page opens.
5. The watchlist add/remove flow works.

## Step 6: Understand the free-tier behavior

### Render free backend

On the current Render free offering:

- the service spins down after 15 minutes of inactivity
- the next request may take around 1 minute to wake it up
- local file changes are lost on spin-down, restart, or redeploy

In this project, that means:

- watchlist entries may disappear after the backend sleeps or redeploys
- paper trading state may reset
- stored Upstox token files do not persist reliably

### Vercel Hobby frontend

The frontend is a good fit for Vercel Hobby because it is a standard Next.js app and only needs one public environment variable: the backend URL.

## Step 7: Optional upgrades later

Once the free deployment is working, the next meaningful improvements are:

1. Move watchlist and trading state into a real database.
2. Add real market data by switching `DATA_PROVIDER=upstox`.
3. Add `ANTHROPIC_API_KEY` only if you want live Claude analysis.
4. Install Playwright browsers on Render only if you want headless Upstox auto-login.

If you later enable headless Upstox auto-login on Render, update `backend/render.yaml`:

```yaml
buildCommand: pip install -r requirements.txt && playwright install chromium --with-deps
```

## Quick value checklist

### Render

```env
ENVIRONMENT=production
SUGGESTIONS_TTL_SECONDS=600
DATA_PROVIDER=mock
PAPER_TRADING=true
ANALYZER_PROVIDER=stub
WATCHLIST_PATH=watchlist.json
APP_FRONTEND_URL=https://your-project-name.vercel.app
```

### Vercel

```env
NEXT_PUBLIC_API_BASE_URL=https://your-backend-name.onrender.com
```

## Recommended first deployment order

1. Deploy backend on Render.
2. Copy the Render URL.
3. Deploy frontend on Vercel using that Render URL.
4. Copy the Vercel URL.
5. Set `APP_FRONTEND_URL` in Render.
6. Re-test both services.
