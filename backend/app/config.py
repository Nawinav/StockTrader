"""Application configuration loaded from environment variables."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Stock Suggestion API"
    environment: str = "development"

    # Cache TTL for suggestions (seconds). 5 minutes by default.
    suggestions_ttl_seconds: int = 300

    # CORS: comma-separated list of allowed frontend origins.
    # In production set to your Vercel URL e.g. "https://your-app.vercel.app"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Data provider: "mock" | "upstox" (upstox is stubbed for now).
    data_provider: str = "mock"

    # Upstox credentials (only needed once you wire live data + trading).
    upstox_api_key: str | None = None
    upstox_api_secret: str | None = None
    upstox_redirect_uri: str | None = None
    upstox_access_token: str | None = None

    # --- Upstox headless auto-login (fill to enable daily auto-refresh) -
    # UPSTOX_TOTP_SECRET is the base32 key shown when you first set up 2FA
    # on Upstox: Settings → My Profile → Two Factor Authentication →
    # "Can't scan? Enter this key manually".  Keep .env chmod 600.
    upstox_mobile: str | None = None      # 10-digit mobile number
    upstox_pin: str | None = None         # 6-digit Upstox login PIN
    upstox_totp_secret: str | None = None # base32 TOTP secret key

    # --- Push notifications via ntfy.sh (free, no account needed) ----------
    # Install the "ntfy" app on your phone → subscribe to the same topic.
    # Use a long random string as the topic name for privacy.
    ntfy_topic:  str | None = None   # e.g. "naveen-trading-abc123"
    ntfy_server: str | None = None   # defaults to "https://ntfy.sh"

    # URL of the frontend app, sent as a deep-link in push notifications.
    app_frontend_url: str = "http://localhost:3000"

    # Paper-trading toggle (future). When False and a live key is set,
    # orders would be routed to real capital. Leave True until confident.
    paper_trading: bool = True

    # Watchlist persistence path (simple JSON store for MVP).
    watchlist_path: str = "watchlist.json"

    # ---- Intraday analyzer (Claude) -----------------------------------
    # Which Claude client backs the analyzer.
    #   "stub"      -> deterministic in-process response (no API cost, no network)
    #   "anthropic" -> real Anthropic API call (requires anthropic_api_key)
    analyzer_provider: str = "stub"

    # Anthropic credentials + model. Only used when analyzer_provider == "anthropic".
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    # Soft cache for analyzer responses per (symbol, minute-bucket).
    # LLM calls are expensive; re-analysing the same symbol within this window
    # returns the cached signal.
    analyzer_ttl_seconds: int = 60

    # Default capital / risk parameters used when the caller does not supply
    # per-request overrides. Keep tiny defaults so nothing dangerous happens.
    default_capital_inr: float = 100000.0
    default_risk_pct: float = 1.0
    default_max_daily_loss_pct: float = 3.0

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
