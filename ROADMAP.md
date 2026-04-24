# Roadmap — from MVP to live Upstox trading

This app is shipped as a read-only suggestion board. The next three milestones graduate it into a paper-trading bot and, only when the strategy has been validated, a live trading bot on real capital.

**Guiding principles**
- No shortcut from mock data to live orders. You must cross every milestone in order.
- Paper-trading results are recorded and compared to the suggestion scores for at least N weeks before real capital is allowed.
- Two independent flags must be flipped to enable real orders. A single env var is not enough.

---

## Milestone 1 — Live Upstox market data (read-only)

**Goal:** replace `MockProvider` with `UpstoxProvider` so scores reflect real NSE prices. No orders yet.

1. Register a developer app on the Upstox portal and capture:
   - `UPSTOX_API_KEY`
   - `UPSTOX_API_SECRET`
   - `UPSTOX_REDIRECT_URI`
2. Build the OAuth round-trip (authorize → code → access_token). Access tokens expire daily; add a refresh helper.
3. Map each entry in `backend/app/data/universe.py` to its Upstox `instrument_key` (download the instruments CSV).
4. Implement `UpstoxClient.get_historical_candles` and `.get_ltp` in `backend/app/integrations/upstox.py`.
5. Implement `UpstoxProvider.get_history` / `.get_quote` in `backend/app/services/data_provider.py` by translating Upstox responses into `OHLCV` objects.
6. Flip `DATA_PROVIDER=upstox` in Render env.
7. Smoke-test `/api/suggestions/intraday` returns live quotes.

**Exit criteria:** suggestion prices match NSE within a few seconds; no rate-limit or auth errors for a full trading day.

---

## Milestone 2 — Paper trading with mock capital

**Goal:** execute suggestions against a simulated broker and track P&L end-to-end.

1. Add a `PaperBroker` class (`backend/app/integrations/paper_broker.py`) that:
   - Accepts the same `OrderRequest` as `UpstoxClient.place_order`.
   - Fills orders at the current LTP ± a small configurable slippage %.
   - Writes fills to a DB table `paper_fills`.
2. Add tables: `paper_accounts`, `paper_positions`, `paper_fills`, `suggestion_audit`. Use SQLite locally, Postgres on Render.
3. Add `/api/paper/*` endpoints: account balance, open positions, fills, P&L curve.
4. Build a scheduler (APScheduler or a Render cron worker) that:
   - Every 10 min pulls new suggestions.
   - Opens paper positions sized to a configurable % of capital per idea.
   - Honours stop-loss / target on every scheduler tick.
5. Add a frontend `/paper` page showing positions and a P&L chart (Recharts).
6. Seed the paper account with e.g. ₹10,00,000 mock capital.

**Exit criteria:** at least 4 full trading weeks of paper fills, with the aggregated paper P&L beating a passive Nifty benchmark by a margin you are comfortable with. Also: zero incidents where the paper engine produced nonsensical fills.

---

## Milestone 3 — Live trading, tiny capital

**Goal:** allow real orders with strict guardrails. Default must be OFF.

1. Add env flags:
   - `PAPER_TRADING=false`
   - `ENABLE_LIVE_TRADING=true`
   - Both must be set. Startup asserts this explicitly and logs a loud banner.
2. Implement `UpstoxBroker.place_order` that calls `POST /v2/order/place`.
3. Wrap every order path in a **daily risk budget**:
   - Max loss / day (₹ and % of capital).
   - Max position size per trade.
   - Max open positions simultaneously.
   - Block new entries after daily stop is hit.
4. Two-channel confirmation:
   - Write an order intent row to Postgres.
   - Push a Telegram/Slack notification with an `approve/reject` link before the order is sent.
5. Start with ₹5,000–₹10,000 of real capital. Do not scale until 30+ live trading days.
6. Compare realised P&L against paper P&L weekly. If they diverge materially, cut size or pause.

**Exit criteria:** well-documented risk rules, tested kill switch, and at least one live-trading month with results within tolerance of paper results.

---

## Ongoing work

- Replace the watchlist JSON store with Postgres + per-user auth.
- Add a backtesting harness for the scoring engine (daily bars, walk-forward).
- Let users customise the scoring weights and save their own strategies.
- Sector rotation / correlation filters to diversify the top 10.
- Event-based refresh (earnings day, results day) in addition to the 10-minute cadence.
