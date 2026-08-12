import asyncio
import os
from datetime import datetime, time as dtime
from typing import Any

from loguru import logger

from config.settings import KIS_MOCK
from core.llm_judge import LLMJudge
from database.db import get_db
from database.models import PositionRepository, TradeRepository

DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() == "true"


class TradingEngine:
    _instance: "TradingEngine | None" = None

    def __new__(cls) -> "TradingEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        self.running = False
        self.is_paper = KIS_MOCK
        self.demo_mode = DEMO_MODE
        self._started_at: datetime | None = None
        self.last_tick: datetime | None = None
        self.llm_call_count = 0

        self._decisions: list[dict[str, Any]] = []
        self._watchlist: dict[str, str] = {}
        self._task: asyncio.Task | None = None

        if DEMO_MODE:
            logger.info("[Engine] DEMO_MODE 활성화 — 실제 API 없이 동작합니다")
            from core.demo_data import get_demo_watchlist
            for item in get_demo_watchlist():
                self._watchlist[item["ticker"]] = item["name"]
        else:
            from core.data_fetcher import DataFetcher
            self.fetcher = DataFetcher()

        self.judge = LLMJudge()
        self.position_repo = PositionRepository(get_db())
        self.trade_repo = TradeRepository(get_db())

    def uptime_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return (datetime.now() - self._started_at).total_seconds()

    async def start(self) -> None:
        self.running = True
        self._started_at = datetime.now()
        self._task = asyncio.create_task(self._loop())
        logger.info("[Engine] 봇 시작")

        from notifications.telegram_bot import notify_start
        asyncio.create_task(_safe(notify_start()))

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[Engine] 봇 중지")

        from notifications.telegram_bot import notify_stop
        asyncio.create_task(_safe(notify_stop()))

    async def _loop(self) -> None:
        while self.running:
            try:
                if DEMO_MODE or self._is_market_hours():
                    await self._tick()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Engine] 루프 에러: {e}")
                await asyncio.sleep(10)

    def _is_market_hours(self) -> bool:
        now = datetime.now().time()
        return dtime(9, 0) <= now <= dtime(15, 30)

    async def _tick(self) -> None:
        self.last_tick = datetime.now()
        tickers = list(self._watchlist.keys())
        if not tickers:
            return

        market_data: dict[str, Any] = {}
        if DEMO_MODE:
            from core.demo_data import get_demo_ticker
            for ticker in tickers:
                market_data[ticker] = get_demo_ticker(ticker)
        else:
            for ticker in tickers:
                try:
                    data = await self.fetcher.fetch(ticker)
                    market_data[ticker] = data
                except Exception as e:
                    logger.warning(f"[Engine] {ticker} 시세 조회 실패: {e}")

        positions = await self.get_positions()

        try:
            decision = await self.judge.judge(
                market_data=market_data,
                positions=positions,
                watchlist=self._watchlist,
            )
            self.llm_call_count += 1
            self._decisions.insert(0, {**decision, "timestamp": datetime.now().isoformat(timespec="seconds")})
            self._decisions = self._decisions[:50]

            from api.websocket import broadcast
            await broadcast({"type": "decision", "data": decision})

            if decision.get("decision") in ("BUY", "SELL"):
                await self._execute(decision)
        except Exception as e:
            logger.error(f"[Engine] LLM 판단 에러: {e}")

    async def _execute(self, decision: dict[str, Any]) -> None:
        ticker = decision.get("ticker", "")
        action = decision.get("decision", "")
        qty = int(decision.get("quantity", 1))
        logger.info(f"[Engine] {action} {ticker} x{qty}")

        from notifications.telegram_bot import notify_trade
        asyncio.create_task(_safe(notify_trade(action, ticker, qty, decision.get("reason", ""))))

    async def get_portfolio(self) -> dict[str, Any]:
        if DEMO_MODE:
            from core.demo_data import get_demo_portfolio
            return get_demo_portfolio()
        try:
            data = await self.fetcher.fetch_portfolio()
            return data
        except Exception as e:
            logger.error(f"[Engine] 포트폴리오 조회 실패: {e}")
            return {"total_value": 0, "cash": 0, "return_pct": 0.0}

    async def get_positions(self) -> list[dict[str, Any]]:
        if DEMO_MODE:
            from core.demo_data import get_demo_positions
            return get_demo_positions()
        try:
            records = self.position_repo.find_all()
            result = []
            for r in records:
                current_price = 0.0
                try:
                    data = await self.fetcher.fetch(r.symbol)
                    current_price = data.get("current_price", 0.0)
                except Exception:
                    pass
                pnl_pct = 0.0
                if r.avg_price > 0 and current_price > 0:
                    pnl_pct = round((current_price - r.avg_price) / r.avg_price * 100, 2)
                result.append({
                    "symbol": r.symbol,
                    "quantity": r.quantity,
                    "avg_price": r.avg_price,
                    "current_price": current_price,
                    "value": round(current_price * r.quantity, 0),
                    "pnl_pct": pnl_pct,
                    "market": r.market,
                    "opened_at": r.opened_at,
                    "stop_price": r.stop_price,
                    "target_price": r.target_price,
                })
            return result
        except Exception as e:
            logger.error(f"[Engine] 포지션 조회 실패: {e}")
            return []

    def get_recent_decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._decisions[:limit]

    async def get_watchlist(self) -> list[dict[str, Any]]:
        result = []
        for ticker, name in self._watchlist.items():
            item: dict[str, Any] = {"ticker": ticker, "name": name or ticker}
            try:
                if DEMO_MODE:
                    from core.demo_data import get_demo_ticker
                    data = get_demo_ticker(ticker)
                else:
                    data = await self.fetcher.fetch(ticker)
                item["current_price"] = data.get("current_price", 0)
                item["week52_high"] = data.get("week52_high", 0)
                high = data.get("week52_high", 0)
                cur = data.get("current_price", 0)
                if high > 0 and cur > 0:
                    item["pct_from_high"] = round((high - cur) / high * 100, 2)
                else:
                    item["pct_from_high"] = None
            except Exception:
                item["current_price"] = None
                item["week52_high"] = None
                item["pct_from_high"] = None
            result.append(item)
        return result

    async def get_return_history(self) -> list[dict[str, Any]]:
        """30일 수익률 추이. 데모 모드에서는 샘플 데이터 반환."""
        if DEMO_MODE:
            from core.demo_data import get_demo_return_history
            return get_demo_return_history(30)
        # 실전: DB에서 집계 (현재는 빈 배열)
        return []

    def add_to_watchlist(self, ticker: str, name: str = "") -> None:
        self._watchlist[ticker] = name

    def remove_from_watchlist(self, ticker: str) -> None:
        self._watchlist.pop(ticker, None)


async def _safe(coro: Any) -> None:
    try:
        await coro
    except Exception as e:
        logger.warning(f"[Engine] 알림 실패: {e}")
