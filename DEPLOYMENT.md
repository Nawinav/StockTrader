# Deployment Guide — Stock Trading App

**Stack:** FastAPI backend on **Render** (free) + Next.js frontend on **Vercel** (free)
**Time needed:** ~30 minutes on first deploy

---

## What you need before starting

| Requirement | Where to get it | Free? |
|---|---|---|
| GitHub account | github.com | ✅ |
| Render account | render.com | ✅ |
| Vercel account | vercel.com | ✅ |
| Git installed locally | git-scm.com | ✅ |
| Upstox developer app | upstox.com/developer | ✅ (optional, for live data) |

---

## Overview

```
Your code (GitHub)
       │
       ├──► Render (backend API)     https://your-api.onrender.com
       │         FastAPI + Uvicorn
       │         Python 3.11
       │
       └──► Vercel (frontend)        https://your-app.vercel.app
                 Next.js 14
```

Both Render and Vercel watch your GitHub repo and **auto-redeploy on every push**.

The free deploy works out-of-the-box with **mock stock data** — no Upstox account needed to get it running. You add Upstox credentials later to switch to live NSE prices.

---

## Step 1 — Push the code to GitHub

Open a terminal inside the `stock-trading` folder:

```bash
# Initialise git (skip if you already have a repo)
git init
git add .
git commit -m "Initial deploy"

# Create a new GitHub repo and push
# Option A: using the GitHub CLI
gh repo create stock-trading --public --source=. --push

# Option B: without the CLI
# 1. Go to github.com → New repository → name it stock-trading → Create
# 2. Run the two commands GitHub shows you ("push an existing repository")
```

> ⚠️ Make sure `.env` and `.env.local` are NOT committed.
> Run `git status` — you should NOT see those files listed.
> The `.gitignore` already excludes them.

---

## Step 2 — Deploy the backend on Render

### 2.1 — Create a Render account

Go to **render.com** → **Get Started for Free** → sign up with GitHub (recommended — Render can then see your repos directly).

### 2.2 — Create a new Web Service

1. In the Render dashboard click **New +** → **Web Service**.
2. Click **Connect a repository** → select your `stock-trading` repo → click **Connect**.
3. Fill in the service settings exactly as shown:

| Field | Value |
|---|---|
| **Name** | `stock-trading-api` |
| **Region** | Singapore `(ap-southeast-1)` — closest to India |
| **Branch** | `main` |
| **Root Directory** | `backend` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Instance Type** | **Free** |

### 2.3 — Add environment variables

Still on the same page, scroll down to **Environment Variables** and click **Add Environment Variable** for each:

| Key | Value | Notes |
|---|---|---|
| `ENVIRONMENT` | `production` | |
| `DATA_PROVIDER` | `mock` | Live data: change to `upstox` later (Step 5) |
| `PAPER_TRADING` | `true` | Always keep `true` |
| `SUGGESTIONS_TTL_SECONDS` | `600` | 10-min cache, reduces load on free tier |
| `WATCHLIST_PATH` | `watchlist.json` | |
| `ANALYZER_PROVIDER` | `stub` | No API cost. Change to `anthropic` if you want Claude AI analysis |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Only used if ANALYZER_PROVIDER=anthropic |
| `NTFY_SERVER` | `https://ntfy.sh` | Push notifications server |
| `CORS_ORIGINS` | *(leave blank for now)* | Fill in after Step 3 |
| `APP_FRONTEND_URL` | *(leave blank for now)* | Fill in after Step 3 |

4. Click **Create Web Service** at the bottom.

### 2.4 — Wait for the first build

Render clones your repo and runs `pip install`. This takes **3–5 minutes** the first time.

Watch the **Logs** tab. A successful startup looks like:

```
==> Build successful 🎉
==> Starting service with 'uvicorn app.main:app --host 0.0.0.0 --port 10000'
INFO:     Started server process
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:10000
```

### 2.5 — Verify the backend

Once the status badge turns **Live** (green), copy your backend URL from the top of the page.
It looks like: `https://stock-trading-api.onrender.com`

Test it — open this in your browser:
```
https://stock-trading-api.onrender.com/health
```
Expected: `{"status":"ok"}`

Also test the suggestions endpoint:
```
https://stock-trading-api.onrender.com/api/suggestions/intraday
```
Expected: JSON with 10 mock stock suggestions.

---

## Step 3 — Deploy the frontend on Vercel

### 3.1 — Create a Vercel account

Go to **vercel.com** → **Start Deploying** → sign up with GitHub.

### 3.2 — Import the project

1. In the Vercel dashboard click **Add New → Project**.
2. Find your `stock-trading` repo → click **Import**.
3. On the configuration screen, change **one important setting**:

| Field | Value |
|---|---|
| **Framework Preset** | Next.js *(auto-detected, leave it)* |
| **Root Directory** | **`frontend`** ← click Edit and type this |
| **Build Command** | `next build` *(leave as default)* |
| **Install Command** | `npm install` *(leave as default)* |

4. Under **Environment Variables**, add:

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://stock-trading-api.onrender.com` |

   Replace with your actual Render URL from Step 2.5. No trailing slash.

5. Click **Deploy**.

### 3.3 — Wait for the frontend build

Vercel builds are fast — usually **1–2 minutes**.

A successful build ends with:
```
✓ Compiled successfully
✓ Generating static pages (X/X)
✓ Finalizing page optimization
```

### 3.4 — Note your frontend URL

Vercel shows your URL after deploy. It looks like:
`https://stock-trading-abc123.vercel.app`

You can customise this in **Settings → Domains → Edit**.

---

## Step 4 — Connect the two services

Now update the backend with your Vercel URL so CORS is properly configured and push notification links work.

### 4.1 — Update environment variables on Render

1. Go to **Render → your service → Environment**.
2. Find `CORS_ORIGINS` → click the pencil icon → set the value to your Vercel URL:
   ```
   https://stock-trading-abc123.vercel.app
   ```
3. Find `APP_FRONTEND_URL` → set to the same Vercel URL.
4. Click **Save Changes** — Render auto-redeploys (takes ~1 minute).

> **Note:** The backend already allows any `*.vercel.app` domain via a regex rule.
> Setting `CORS_ORIGINS` explicitly is best practice but not strictly required
> if you're on the default Vercel domain.

### 4.2 — Full stack smoke test

Open your Vercel URL in a browser. You should see:

- ✅ Dashboard loads with 10 mock stock suggestions
- ✅ Trading page shows paper portfolio (₹1,00,000 starting capital)
- ✅ Markets page shows sector heatmap
- ✅ No "Failed to load" errors
- ✅ No CORS errors in browser DevTools console

If you see a CORS error in the console, double-check:
1. `NEXT_PUBLIC_API_BASE_URL` on Vercel — must exactly match your Render URL (no trailing slash, `https://`)
2. `CORS_ORIGINS` on Render — must exactly match your Vercel URL

---

## Step 5 — Connect live Upstox data (optional)

The app works with mock data by default. Do this section to get real NSE prices.

### 5.1 — Create an Upstox developer app

1. Log in to **upstox.com** → click your name (top right) → **Developer**.
2. Click **My Apps → Create New App**.
3. Fill in:
   - **App Name**: `Stock Trading App` (anything)
   - **Redirect URL**: `https://stock-trading-api.onrender.com/auth/upstox/callback`
   - **Description**: anything
4. Click **Create**. Copy the **API Key** and **API Secret** shown.

### 5.2 — Add Upstox credentials to Render

Go to **Render → your service → Environment** and add:

| Key | Value |
|---|---|
| `UPSTOX_API_KEY` | *(your API Key from step 5.1)* |
| `UPSTOX_API_SECRET` | *(your API Secret from step 5.1)* |
| `UPSTOX_REDIRECT_URI` | `https://stock-trading-api.onrender.com/auth/upstox/callback` |
| `DATA_PROVIDER` | `upstox` |

Click **Save Changes** → Render redeploys.

### 5.3 — Complete the daily login (each morning)

Upstox tokens expire every day at midnight. Each morning before 9:15 AM IST:

1. Open your Vercel frontend URL.
2. You'll see a yellow **"⚠️ Upstox token expired"** banner at the top.
3. Click **Login Now**.
4. Click **Start Login** — the backend requests an OTP from Upstox.
5. Enter the **6-digit SMS OTP** you receive on your Upstox-registered mobile.
6. Click **Submit OTP** — the backend auto-fills your PIN and TOTP.
7. The banner turns green: **"Upstox live data connected — NIFTY 50: ₹XXXXX"**

### 5.4 — Enable fully automatic daily login (no OTP needed)

To make the login fully hands-free using TOTP:

1. In Upstox: **Settings → My Profile → Two Factor Authentication → Enable**.
2. When the QR code appears, click **"Can't scan? Enter key manually"**.
3. Copy the **base32 key** — it looks like `JBSWY3DPEHPK3PXP`.
4. Add to Render environment:

| Key | Value |
|---|---|
| `UPSTOX_MOBILE` | Your 10-digit Upstox-registered mobile number |
| `UPSTOX_PIN` | Your 6-digit Upstox login PIN |
| `UPSTOX_TOTP_SECRET` | The base32 key from step 3 |

With these set, the backend auto-refreshes the token every morning at 8:30 AM IST without any manual input. No OTP banner will appear.

> ⚠️ **Security note:** These are sensitive credentials. Render stores them encrypted at rest. Never commit them to GitHub or share them.

---

## Step 6 — Enable push notifications (optional)

Get a phone alert every time a paper trade opens or closes:

1. Install the **ntfy** app on your phone — search "ntfy" on Play Store or App Store (free, no account needed).
2. In the app, tap the **+** button → enter a topic name. Use a long random string for privacy, e.g. `naveen-trading-k9x2m4p7q1`.
3. Add to Render environment:

| Key | Value |
|---|---|
| `NTFY_TOPIC` | `naveen-trading-k9x2m4p7q1` *(your chosen topic)* |

Notifications arrive the moment a position opens or closes.

---

## Step 7 — Keep the backend awake (important for free tier)

Render's free tier **spins down after 15 minutes of no traffic**. The next request takes 30–60 seconds to wake it up (cold start). During market hours this is disruptive.

### Fix: UptimeRobot (free, 5 minutes to set up)

1. Go to **uptimerobot.com** → Create Free Account.
2. Click **+ Add New Monitor**:
   - Monitor Type: **HTTP(s)**
   - Friendly Name: `Stock Trading API`
   - URL: `https://stock-trading-api.onrender.com/health`
   - Monitoring Interval: **5 minutes**
3. Click **Create Monitor**.

UptimeRobot pings your backend every 5 minutes — this keeps it alive all day. You also get email alerts if the backend goes down.

---

## Keeping the app updated

Every time you push code, both services automatically redeploy:

```bash
# Make changes to the code, then:
git add .
git commit -m "describe your change"
git push

# Render rebuilds backend:  ~2–3 minutes
# Vercel rebuilds frontend: ~1 minute
```

No manual steps needed — both services watch the `main` branch.

---

## Troubleshooting

### "Build failed" on Render

Open the Render **Logs** tab. Common causes:

| Error | Fix |
|---|---|
| `ModuleNotFoundError` | A package is missing from `requirements.txt` |
| `SyntaxError` | Python syntax error in code — fix and push again |
| `error: command 'pip' failed` | Check Python version — Render uses Python 3.11 by default |

### "Application failed to start" on Render

The build passed but startup failed. Check logs for:

| Error | Fix |
|---|---|
| `Address already in use` | Start command must use `$PORT` env var |
| `pydantic_settings` import error | Make sure `pydantic-settings==2.2.1` is in requirements.txt |
| `KeyError` on settings | An env var is referenced in code but missing from Render environment |

### CORS error in browser console

```
Access to fetch blocked by CORS policy
```

1. Go to Render → Environment.
2. Check `CORS_ORIGINS` exactly matches your Vercel URL.
3. No trailing slash. Must start with `https://`.
4. Save → wait for redeploy.

### Frontend shows "Failed to load" or blank data

1. Open browser DevTools → **Network** tab.
2. Look for the failing API request — check the URL it's calling.
3. If the URL shows `localhost:8000` → go to Vercel → Settings → Environment Variables → update `NEXT_PUBLIC_API_BASE_URL` → **Redeploy**.
4. If the URL is correct but request fails with 502/503 → Render may be in cold start. Wait 60 seconds and try again.

### Upstox "token expired" after every restart

This is expected on Render free tier — the filesystem is ephemeral, so `upstox_token.json` is wiped on restart.

**Permanent fix:** Configure TOTP auto-login (Step 5.4). The token is then refreshed from env vars on every startup, no file needed.

---

## Free tier limitations summary

| Limitation | Impact | Workaround |
|---|---|---|
| Render spins down after 15 min idle | 30–60s cold start on first request | UptimeRobot ping every 5 min (Step 7) |
| Render filesystem is ephemeral | Trading state, watchlist, token lost on restart | Accept for paper trading; TOTP for token |
| Render free: 750 hours/month | Enough for one always-on service | — |
| Vercel free: 100 GB bandwidth | More than enough for personal use | — |
| No background scheduler on Render free | Auto-tick runs but may miss ticks if sleeping | Use UptimeRobot to keep alive |

---

## Complete environment variable reference

### Backend (set on Render)

| Variable | Required | Default | Description |
|---|---|---|---|
| `ENVIRONMENT` | ✅ | `development` | Set to `production` |
| `DATA_PROVIDER` | ✅ | `mock` | `mock` or `upstox` |
| `PAPER_TRADING` | ✅ | `true` | Always `true` for safety |
| `CORS_ORIGINS` | Recommended | — | Your Vercel URL |
| `APP_FRONTEND_URL` | Recommended | `localhost:3000` | Your Vercel URL |
| `SUGGESTIONS_TTL_SECONDS` | No | `300` | Set `600` on free tier |
| `WATCHLIST_PATH` | No | `watchlist.json` | Path to watchlist JSON |
| `UPSTOX_API_KEY` | Live data | — | Upstox developer portal |
| `UPSTOX_API_SECRET` | Live data | — | Upstox developer portal |
| `UPSTOX_REDIRECT_URI` | Live data | — | Must match Upstox app |
| `UPSTOX_ACCESS_TOKEN` | Optional | — | Paste token to skip OAuth |
| `UPSTOX_MOBILE` | Auto-login | — | 10-digit mobile number |
| `UPSTOX_PIN` | Auto-login | — | 6-digit Upstox PIN |
| `UPSTOX_TOTP_SECRET` | Auto-login | — | Base32 2FA key |
| `NTFY_TOPIC` | Optional | — | Push notification topic |
| `NTFY_SERVER` | No | `https://ntfy.sh` | ntfy server URL |
| `ANALYZER_PROVIDER` | No | `stub` | `stub` or `anthropic` |
| `ANTHROPIC_API_KEY` | AI only | — | For Claude AI analysis |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-6` | Claude model |

### Frontend (set on Vercel)

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | ✅ | `http://localhost:8000` | Your Render backend URL |

---

## Deployment checklist

Copy and use this to track your progress:

```
STEP 1 — GITHUB
[ ] Code pushed to GitHub repo

STEP 2 — RENDER BACKEND
[ ] Web Service created, root directory = backend
[ ] Region = Singapore
[ ] Build command = pip install -r requirements.txt
[ ] Start command = uvicorn app.main:app --host 0.0.0.0 --port $PORT
[ ] All env vars set (ENVIRONMENT, DATA_PROVIDER, PAPER_TRADING, etc.)
[ ] Service status = Live (green)
[ ] Health check passes: /health → {"status":"ok"}
[ ] Suggestions load: /api/suggestions/intraday → 10 items

STEP 3 — VERCEL FRONTEND
[ ] Project imported, root directory = frontend
[ ] NEXT_PUBLIC_API_BASE_URL = https://your-api.onrender.com
[ ] Build succeeded
[ ] Frontend URL noted

STEP 4 — WIRE TOGETHER
[ ] CORS_ORIGINS on Render = your Vercel URL
[ ] APP_FRONTEND_URL on Render = your Vercel URL
[ ] Full dashboard loads without errors
[ ] Trading page works
[ ] No CORS errors in browser console

STEP 5 — LIVE DATA (optional)
[ ] Upstox developer app created
[ ] UPSTOX_API_KEY, SECRET, REDIRECT_URI added to Render
[ ] DATA_PROVIDER = upstox
[ ] Daily login completed from UI banner
[ ] Green "Upstox live data connected" bar visible

STEP 6 — NOTIFICATIONS (optional)
[ ] ntfy app installed on phone
[ ] NTFY_TOPIC set on Render
[ ] Test trade notification received

STEP 7 — KEEP ALIVE
[ ] UptimeRobot monitor created for /health every 5 minutes
```
