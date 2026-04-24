"""FastAPI app entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import analyze, auth, signals, stocks, suggestions, trading, watchlist
from app.services.scheduler import lifespan


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Backend for the stock suggestion dashboard. "
            "Returns top-10 intraday and long-term ideas based on a "
            "blended technical + fundamental score, refreshed every 10 minutes."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"^https://.*\.vercel\.app$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(suggestions.router)
    app.include_router(watchlist.router)
    app.include_router(stocks.router)
    app.include_router(analyze.router)
    app.include_router(signals.router)   # rule-based 9-strategy algo engine
    app.include_router(auth.router)
    app.include_router(trading.router)

    @app.get("/api/market/regime", tags=["market"])
    def market_regime() -> dict:
        """Return current market regime classification."""
        try:
            from app.services.market_regime import detect
            r = detect()
            return {
                "regime": r.regime,
                "nifty_ltp": r.nifty_ltp,
                "nifty_change_pct": r.nifty_change_pct,
                "adx": r.adx,
                "vix": r.vix,
                "sma20": r.sma20,
                "sma50": r.sma50,
                "recommended_min_confluence": r.recommended_min_confluence,
                "block_new_longs": r.block_new_longs,
                "disabled_strategies": list(r.disabled_strategies),
                "label": r.label,
                "summary": r.summary(),
            }
        except Exception as exc:
            return {"regime": "UNKNOWN", "error": str(exc)}

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "app": settings.app_name,
            "env": settings.environment,
            "provider": settings.data_provider,
            "paper_trading": settings.paper_trading,
            "docs": "/docs",
        }

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
