from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.engine import TradingEngine
from database.research_repo import get_research_repo

router = APIRouter()
engine = TradingEngine()


class WatchlistAddRequest(BaseModel):
    ticker: str
    name: str = ""


class TradingModeRequest(BaseModel):
    mode: str  # "scalping" | "day_trading" | "swing" | "long_term"


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str = "long_term"  # "scalping" | "day_trading" | "swing" | "long_term"
    period_days: int = 90


class ResearchNoteRequest(BaseModel):
    ticker: str
    source: str = ""
    rating: str = ""
    target_price: float = 0.0
    current_price: float = 0.0
    summary: str = ""
    content: str = ""
    catalyst: str = ""


@router.get("/status")
async def get_status() -> dict[str, Any]:
    try:
        return {
            "running": engine.running,
            "mode": "paper" if engine.is_paper else "live",
            "demo_mode": engine.demo_mode,
            "uptime_seconds": engine.uptime_seconds(),
            "last_tick": engine.last_tick.isoformat() if engine.last_tick else None,
            "llm_call_count": engine.llm_call_count,
            "market_open": engine._is_market_hours(),
        }
    except Exception as e:
        return {"running": False, "mode": "unknown", "demo_mode": False,
                "uptime_seconds": 0, "last_tick": None, "llm_call_count": 0,
                "market_open": False, "error": str(e)}


@router.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    import os
    seed = int(os.getenv("SEED_AMOUNT", "2000000"))
    try:
        return await engine.get_portfolio()
    except Exception:
        return {"total_value": seed, "cash": seed, "invested": 0,
                "pnl_amount": 0, "return_pct": 0.0, "seed": seed, "api_error": True}


@router.get("/positions")
async def get_positions() -> list[dict[str, Any]]:
    try:
        return await engine.get_positions()
    except Exception:
        return []


@router.get("/decisions")
async def get_decisions() -> list[dict[str, Any]]:
    try:
        return engine.get_recent_decisions(limit=20)
    except Exception:
        return []


@router.get("/watchlist")
async def get_watchlist() -> list[dict[str, Any]]:
    try:
        return await engine.get_watchlist()
    except Exception:
        return []


@router.post("/start")
async def start_bot() -> dict[str, str]:
    if engine.running:
        return {"status": "already_running"}
    await engine.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_bot() -> dict[str, str]:
    if not engine.running:
        return {"status": "already_stopped"}
    await engine.stop()
    return {"status": "stopped"}


@router.post("/watchlist")
async def add_watchlist(req: WatchlistAddRequest) -> dict[str, str]:
    engine.add_to_watchlist(req.ticker, req.name)
    return {"status": "added", "ticker": req.ticker}


@router.delete("/watchlist/{ticker}")
async def remove_watchlist(ticker: str) -> dict[str, str]:
    engine.remove_from_watchlist(ticker)
    return {"status": "removed", "ticker": ticker}


@router.get("/return-history")
async def get_return_history() -> list[dict[str, Any]]:
    try:
        return await engine.get_return_history()
    except Exception:
        return []


# ── 매매 모드 ──────────────────────────────────────────────────────────────

@router.get("/trading-mode")
async def get_trading_mode() -> dict[str, Any]:
    """현재 매매 모드 반환."""
    from core.engine import TRADING_MODE_CONFIG
    mode = engine.trading_mode
    cfg = TRADING_MODE_CONFIG.get(mode, {})
    return {
        "mode": mode,
        "tick_interval": cfg.get("tick_interval", 30),
        "stop_pct": cfg.get("stop_pct", 3.5),
        "take_profit_pct": cfg.get("take_profit_pct", 6.0),
        "trailing_stop_pct": 2.0,
    }


@router.post("/trading-mode")
async def set_trading_mode(req: TradingModeRequest) -> dict[str, Any]:
    """매매 모드 변경."""
    from core.engine import TRADING_MODE_CONFIG
    if req.mode not in TRADING_MODE_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 모드: {req.mode}. 허용: {list(TRADING_MODE_CONFIG.keys())}",
        )
    engine.set_trading_mode(req.mode)
    return {"status": "ok", "mode": req.mode}


# ── 백테스트 ───────────────────────────────────────────────────────────────

@router.post("/backtest")
async def run_backtest(req: BacktestRequest) -> dict[str, Any]:
    """백테스트 실행.

    ticker의 과거 OHLCV 데이터를 받아 strategy 기반 백테스트 결과를 반환한다.
    DEMO_MODE 또는 DataFetcher를 통해 OHLCV를 받는다.
    """
    import os
    from loguru import logger

    DEMO_MODE_FLAG: bool = os.getenv("DEMO_MODE", "false").lower() == "true"

    try:
        from core.backtest import Backtest
        from core.engine import TRADING_MODE_CONFIG

        mode_cfg = TRADING_MODE_CONFIG.get(req.strategy, {})
        stop_pct = mode_cfg.get("stop_pct", 3.5)
        tp_pct = mode_cfg.get("take_profit_pct", 6.0)

        import pandas as pd

        if DEMO_MODE_FLAG:
            # 데모 모드: 랜덤 OHLCV 생성
            import numpy as np
            import random
            n = min(req.period_days, 252)
            base = 50000.0
            closes = [base]
            for _ in range(n - 1):
                closes.append(closes[-1] * (1 + random.gauss(0.001, 0.02)))
            highs = [c * random.uniform(1.0, 1.03) for c in closes]
            lows = [c * random.uniform(0.97, 1.0) for c in closes]
            opens = [c * random.uniform(0.98, 1.02) for c in closes]
            vols = [int(random.uniform(500000, 2000000)) for _ in closes]
            df = pd.DataFrame({
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": vols,
            })
        else:
            try:
                from core.data_fetcher import DataFetcher
                fetcher = DataFetcher()
                df = await fetcher.fetch_ohlcv(req.ticker, period=req.period_days)
            except Exception as e:
                logger.warning(f"[Backtest API] OHLCV 조회 실패, 더미 사용: {e}")
                df = pd.DataFrame()

        if df is None or df.empty:
            return {
                "error": "OHLCV 데이터 없음",
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "total_return": 0.0,
                "sharpe_ratio": 0.0,
                "trades": [],
            }

        bt = Backtest()
        result = bt.run(df, strategy_name=req.strategy, stop_pct=stop_pct, take_profit_pct=tp_pct)
        result["ticker"] = req.ticker
        result["strategy"] = req.strategy
        result["period_days"] = req.period_days
        result["stop_pct"] = stop_pct
        result["take_profit_pct"] = tp_pct
        # trades 리스트 최대 100개
        result["trades"] = result.get("trades", [])[:100]
        return result

    except Exception as e:
        logger.error(f"[Backtest API] 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 리서치 노트 ────────────────────────────────────────────────────────────

@router.post("/research")
async def save_research(req: ResearchNoteRequest) -> dict[str, Any]:
    """리서치 노트 저장."""
    repo = get_research_repo()
    note_id = repo.save(req.model_dump())
    return {"status": "saved", "id": note_id}


@router.get("/research")
async def list_research(ticker: str = "") -> list[dict[str, Any]]:
    """리서치 노트 목록. ticker 쿼리 파라미터로 필터링 가능."""
    repo = get_research_repo()
    if ticker:
        return repo.find_by_ticker(ticker.upper(), limit=50)
    return repo.find_all(limit=50)


@router.delete("/research/{note_id}")
async def delete_research(note_id: int) -> dict[str, Any]:
    """리서치 노트 삭제."""
    repo = get_research_repo()
    repo.delete(note_id)
    return {"status": "deleted", "id": note_id}
