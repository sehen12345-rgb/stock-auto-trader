from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.engine import TradingEngine

router = APIRouter()
engine = TradingEngine()


class WatchlistAddRequest(BaseModel):
    ticker: str
    name: str = ""


@router.get("/status")
async def get_status() -> dict[str, Any]:
    return {
        "running": engine.running,
        "mode": "paper" if engine.is_paper else "live",
        "uptime_seconds": engine.uptime_seconds(),
        "last_tick": engine.last_tick.isoformat() if engine.last_tick else None,
        "llm_call_count": engine.llm_call_count,
    }


@router.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    return await engine.get_portfolio()


@router.get("/positions")
async def get_positions() -> list[dict[str, Any]]:
    return await engine.get_positions()


@router.get("/decisions")
async def get_decisions() -> list[dict[str, Any]]:
    return engine.get_recent_decisions(limit=20)


@router.get("/watchlist")
async def get_watchlist() -> list[dict[str, Any]]:
    return await engine.get_watchlist()


@router.post("/start")
async def start_bot() -> dict[str, str]:
    if engine.running:
        raise HTTPException(status_code=400, detail="Bot is already running")
    await engine.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_bot() -> dict[str, str]:
    if not engine.running:
        raise HTTPException(status_code=400, detail="Bot is not running")
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
