from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from core.engine import TradingEngine

router = APIRouter()
engine = TradingEngine()


class WatchlistAddRequest(BaseModel):
    ticker: str
    name: str = ""


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
    try:
        return await engine.get_portfolio()
    except Exception:
        return {"total_value": 0, "cash": 0, "return_pct": 0.0, "seed": 10_000_000}


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
