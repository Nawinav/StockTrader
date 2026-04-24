/**
 * Lightweight API client for the FastAPI backend.
 *
 * Configure the backend URL via NEXT_PUBLIC_API_BASE_URL.
 * Defaults to http://localhost:8000 for local dev.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "http://localhost:8000";

export type Horizon = "intraday" | "longterm";
export type Action = "BUY" | "SELL" | "HOLD";

export interface ScoreBreakdown {
  technical: number;
  fundamental: number;
  composite: number;
  signals: string[];
}

export interface TechnicalSnapshot {
  last_price: number;
  change_pct: number;
  rsi: number;
  macd: number;
  macd_signal: number;
  sma_20: number;
  sma_50: number;
  sma_200: number;
  volume_ratio: number;
  atr_pct: number;
}

export interface FundamentalSnapshot {
  market_cap_cr: number;
  pe: number;
  pb: number;
  roe: number;
  debt_to_equity: number;
  eps_growth_3y: number;
  revenue_growth_3y: number;
  dividend_yield: number;
  promoter_holding: number;
}

export interface Suggestion {
  symbol: string;
  name: string;
  sector: string;
  horizon: Horizon;
  action: Action;
  entry: number;
  stop_loss: number;
  target: number;
  expected_return_pct: number;
  score: ScoreBreakdown;
  technical: TechnicalSnapshot;
  fundamental: FundamentalSnapshot;
}

export interface SuggestionList {
  horizon: Horizon;
  generated_at: string;
  next_refresh_at: string;
  ttl_seconds: number;
  items: Suggestion[];
  /** "mock" = synthetic OHLCV, "upstox" = live NSE data. */
  data_provider?: string;
}

export interface WatchlistItem {
  symbol: string;
  note: string | null;
  added_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ---- Intraday analyzer (Claude) -------------------------------------

export type AnalyzerAction = "BUY" | "SELL" | "HOLD" | "EXIT" | "AVOID";
export type EntryType = "MARKET" | "LIMIT" | "STOP";
export type StopLossType = "STRUCTURAL" | "ATR" | "PERCENT";
export type TargetLevel = "T1" | "T2" | "T3";

export interface SignalEntry {
  type: EntryType;
  price: number | null;
  valid_until_ist: string;
}

export interface SignalStopLoss {
  price: number;
  type: StopLossType;
  rationale: string;
}

export interface SignalTarget {
  level: TargetLevel;
  price: number;
  rr: number;
  rationale: string;
}

export interface SignalPositionSize {
  quantity: number;
  rupee_risk: number;
  rupee_exposure: number;
  calc: string;
}

export interface SignalReasoning {
  market_context: string;
  trend_alignment: string;
  price_action: string;
  indicator_confluence: string;
  volume_confirmation: string;
  key_levels: string;
  time_of_day: string;
}

export interface AnalyzerSignal {
  symbol: string;
  timestamp_ist: string;
  action: AnalyzerAction;
  confidence: number;
  setup_name: string;
  timeframe_basis: string;
  // 9-strategy confluence fields (populated when Claude evaluates strategy alignment)
  strategies_triggered?: string[];
  strategy_confluence_count?: number;
  hold_period?: string | null;
  entry: SignalEntry;
  stop_loss: SignalStopLoss;
  targets: SignalTarget[];
  position_size: SignalPositionSize;
  trail_strategy: string;
  reasoning: SignalReasoning;
  conflicting_signals: string[];
  invalidation: string;
  what_to_watch: string[];
  risk_flags: string[];
  disclaimer_acknowledged: boolean;
  meta_provider?: string | null;
  meta_model?: string | null;
  meta_cached?: boolean | null;
  meta_latency_ms?: number | null;
}

export interface AnalyzePosition {
  has_position?: boolean;
  side?: "long" | "short" | "none";
  entry?: number;
  quantity?: number;
  unrealized_pnl?: number;
  stop_loss?: number;
  target?: number;
  age_minutes?: number;
}

export interface AnalyzeAccount {
  capital?: number;
  risk_pct?: number;
  max_daily_loss_pct?: number;
  day_pnl?: number;
  trades_today?: number;
  max_trades?: number;
}

export interface AnalyzeRequest {
  position?: AnalyzePosition;
  account?: AnalyzeAccount;
  bust_cache?: boolean;
}

export interface ChartCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartResponse {
  symbol: string;
  timeframe: string;
  candles: ChartCandle[];
}

export interface ExpertAnalysis {
  symbol: string;
  name: string;
  sector: string;
  last_price: number;
  change_pct_1d: number;
  change_pct_5d: number;
  change_pct_20d: number;
  trend: string;
  momentum: string;
  rsi: number;
  macd_hist: number;
  atr_pct: number;
  volatility_label: string;
  volume_vs_avg_20d: number;
  avg_volume_20d: number;
  supports: number[];
  resistances: number[];
  nearest_support: number;
  nearest_resistance: number;
  risk_reward_ratio: number;
  fib_levels: Record<string, number>;
  narrative: string[];
  intraday_score: ScoreBreakdown;
  longterm_score: ScoreBreakdown;
}

// ---- Rule-based Algo Signal (9-strategy confluence engine) ----------

export type AlgoAction = "BUY" | "SELL" | "HOLD" | "AVOID";
export type AlgoConfidence = "HIGH" | "MEDIUM" | "LOW";

export interface AlgoStrategyDetail {
  name: string;
  tag: string;
  direction: number;        // 1=bullish, -1=bearish, 0=neutral
  direction_label: string;  // "BULLISH" | "BEARISH" | "NEUTRAL"
  reason: string;
}

export interface AlgoIndependentVote {
  name: string;
  tag: string;
  direction: number;
  direction_label: string;
  reason: string;
  data_available: boolean;
}

export interface AlgoSignal {
  stock: string;
  date: string;
  time: string;
  action: AlgoAction;
  entry_price: number;
  stop_loss: number;
  target_1: number;
  target_2: number;
  hold_period: string;
  confidence: AlgoConfidence;
  risk_reward_ratio: string;
  strategies_triggered: string[];
  strategy_confluence_count: number;
  reason: string;
  book_profit_instruction: string;
  risk_per_trade_percent: number;
  suggested_position_size_units: number;
  pre_trade_filters_passed: boolean;
  filter_failures: string[];
  strategy_details: AlgoStrategyDetail[];
  indicators_snapshot: Record<string, number | string | null>;
  // Enhancement layers
  market_regime?: string;
  regime_min_confluence?: number;
  regime_disabled_strategies?: string[];
  independent_votes?: AlgoIndependentVote[];
  event_blocked?: boolean;
  event_reasons?: string[];
  meta_engine_version?: string;
  meta_cached?: boolean | null;
  meta_latency_ms?: number | null;
}

export interface MarketRegime {
  regime: string;
  nifty_ltp: number;
  nifty_change_pct: number;
  adx: number;
  vix: number;
  sma20: number;
  sma50: number;
  recommended_min_confluence: number;
  block_new_longs: boolean;
  disabled_strategies: string[];
  label: string;
  summary: string;
}

export interface AlgoSignalRequest {
  capital?: number;
  risk_pct?: number;
  bust_cache?: boolean;
}

// ---- Paper trading --------------------------------------------------

export type TradeSide = "LONG" | "SHORT";
export type ExitReason = "STOP" | "TARGET" | "EOD" | "MANUAL" | "SIGNAL_FLIP" | "P1" | "P2" | "TIME_STOP" | "TRAIL";

export type TradingProfile = "ACTIVE" | "BALANCED" | "HIGH_CONFIDENCE";

export interface TradingConfig {
  // Trading profile — sets filter aggressiveness
  trading_profile: TradingProfile;
  starting_capital_inr: number;
  risk_pct_per_trade: number;
  max_concurrent_positions: number;
  max_entries_per_day: number;
  min_composite_score: number;
  max_stop_distance_pct: number;
  eod_flatten: boolean;
  auto_trading_enabled: boolean;
  // 9-strategy algo engine gate
  use_algo_engine: boolean;
  min_confluence_count: number;
  // Trailing stop
  trail_trigger_pct: number;
  trail_step_pct: number;
}

export interface Position {
  symbol: string;
  name: string;
  sector: string;
  side: TradeSide;
  qty: number;
  entry_price: number;
  stop_loss: number;
  target: number;
  last_price: number;
  entered_at: string;
  score_at_entry: number;
  unrealized_pnl: number;
  unrealized_pct: number;
  risk_inr: number;
  strategies_at_entry: string[];
  confluence_at_entry: number;
  // High-confidence grade
  hc_grade?: string;
  hc_score?: number;
  // Partial profit state
  pp_p1_done?: boolean;
  pp_p2_done?: boolean;
  pp_p1_price?: number;
  pp_p2_price?: number;
}

export interface Trade {
  id: string;
  symbol: string;
  name: string;
  sector: string;
  side: TradeSide;
  qty: number;
  entry_price: number;
  exit_price: number;
  entered_at: string;
  exited_at: string;
  realized_pnl: number;
  realized_pct: number;
  reason: ExitReason;
  score_at_entry: number;
  stop_loss: number;
  target: number;
  strategies_at_entry: string[];
  confluence_at_entry: number;
  // Execution cost simulation
  gross_pnl?: number;
  execution_cost?: number;
  // Market regime at entry
  market_regime?: string;
  // High-confidence grade
  hc_grade?: string;
  hc_score?: number;
}

export interface PortfolioSnapshot {
  starting_capital: number;
  cash: number;
  invested: number;
  equity: number;
  realized_pnl_total: number;
  realized_pnl_today: number;
  unrealized_pnl: number;
  entries_today: number;
  wins_today: number;
  losses_today: number;
  positions: Position[];
  as_of: string;
  market_open: boolean;
  paper_trading: boolean;
  auto_trading_enabled: boolean;
  data_provider: string;
  last_tick_at?: string | null;
  last_tick_reason?: string | null;
}

export interface TickResponse {
  opened: number;
  closed: number;
  reasons: string[];
}

export const api = {
  getSuggestions: (horizon: Horizon, refresh = false) =>
    request<SuggestionList>(
      `/api/suggestions/${horizon}${refresh ? "?refresh=true" : ""}`,
    ),
  getChart: (symbol: string, timeframe = "3M") =>
    request<ChartResponse>(
      `/api/stocks/${encodeURIComponent(symbol)}/chart?timeframe=${timeframe}`,
    ),
  getAnalysis: (symbol: string) =>
    request<ExpertAnalysis>(
      `/api/stocks/${encodeURIComponent(symbol)}/analysis`,
    ),
  getStock: (symbol: string) =>
    request(`/api/stocks/${encodeURIComponent(symbol)}`),
  listWatchlist: () =>
    request<{ items: WatchlistItem[] }>(`/api/watchlist`),
  addWatchlist: (symbol: string, note?: string) =>
    request<WatchlistItem>(`/api/watchlist`, {
      method: "POST",
      body: JSON.stringify({ symbol, note }),
    }),
  removeWatchlist: (symbol: string) =>
    request<void>(`/api/watchlist/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),
  analyze: (symbol: string, body?: AnalyzeRequest) =>
    request<AnalyzerSignal>(`/api/analyze/${encodeURIComponent(symbol)}`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  algoSignal: (symbol: string, body?: AlgoSignalRequest) =>
    request<AlgoSignal>(`/api/signals/${encodeURIComponent(symbol)}`, {
      method: body ? "POST" : "GET",
      ...(body ? { body: JSON.stringify(body) } : {}),
    }),

  // ---- Paper-trading engine -----------------------------------------
  tradingState: () => request<PortfolioSnapshot>(`/api/trading/state`),
  tradingPositions: () =>
    request<{ items: Position[]; as_of: string }>(`/api/trading/positions`),
  tradingTrades: (limit = 50) =>
    request<{ items: Trade[] }>(`/api/trading/trades?limit=${limit}`),
  tradingConfig: () => request<TradingConfig>(`/api/trading/config`),
  tradingUpdateConfig: (cfg: TradingConfig) =>
    request<TradingConfig>(`/api/trading/config`, {
      method: "POST",
      body: JSON.stringify(cfg),
    }),
  tradingToggleAuto: (enabled: boolean) =>
    request<TradingConfig>(`/api/trading/auto`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  tradingTick: () =>
    request<TickResponse>(`/api/trading/tick`, { method: "POST" }),
  tradingFlatten: () =>
    request<TickResponse>(`/api/trading/flatten`, { method: "POST" }),
  tradingClose: (symbol: string) =>
    request<{ trade: Trade }>(
      `/api/trading/positions/${encodeURIComponent(symbol)}/close`,
      { method: "POST" },
    ),
  tradingReset: () =>
    request<{ ok: boolean; state: PortfolioSnapshot }>(`/api/trading/reset`, {
      method: "POST",
    }),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  tradingWhy: () => request<Record<string, any>>(`/api/trading/why`),
  marketRegime: () => request<MarketRegime>(`/api/market/regime`),

  // ---- Upstox auth / token management ---------------------------------

  upstoxStatus: () =>
    request<{
      has_env_token: boolean;
      has_file_token: boolean;
      token_expired: boolean;
      token_expires_at: string | null;
      auto_refresh_configured: boolean;
      ready: boolean;
    }>(`/auth/upstox/status`),

  /** Make a live Nifty 50 LTP call to confirm Upstox API is reachable. */
  upstoxTest: () =>
    request<{
      ok: boolean;
      nifty_ltp: number | null;
      error: string | null;
    }>(`/auth/upstox/test`),

  /**
   * Start a headless login session in the background.
   * Returns immediately with { status: "starting", job_id }.
   * Poll upstoxLoginJobStatus() until status changes.
   */
  upstoxStartLogin: () =>
    request<{ status: string; job_id?: string }>(
      `/auth/upstox/start-login`,
      { method: "POST" },
    ),

  /**
   * Poll the background login job status.
   * Possible statuses: "starting" | "otp_required" | "success" | "error"
   */
  upstoxLoginJobStatus: (jobId: string) =>
    request<{
      status: string;
      session_id?: string;
      token_expires_at?: string;
      error?: string;
    }>(`/auth/upstox/login-job/${jobId}`),

  /** Submit the SMS OTP to the waiting login session. */
  upstoxSubmitOtp: (session_id: string, otp: string) =>
    request<{ status: string; token_expires_at?: string }>(
      `/auth/upstox/submit-otp`,
      {
        method: "POST",
        body: JSON.stringify({ session_id, otp }),
      },
    ),
};
