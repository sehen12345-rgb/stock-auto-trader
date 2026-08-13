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
SEED_AMOUNT: int = 10_000_000  # 시드 1000만원
MAX_SLOTS: int = 4
MAX_PER_SLOT: int = 2_500_000  # 종목당 250만원
STOP_LOSS_PCT: float = 3.5
TAKE_PROFIT_PCT: float = 6.0
MAX_DAILY_LOSS: int = 300_000  # 일 손실 한도 30만원

# 매매 모드별 설정
TRADING_MODE_CONFIG: dict[str, dict[str, Any]] = {
    "scalping":    {"tick_interval": 10,  "stop_pct": 1.0, "take_profit_pct": 1.5},
    "day_trading": {"tick_interval": 30,  "stop_pct": 2.0, "take_profit_pct": 4.0},
    "swing":       {"tick_interval": 300, "stop_pct": 3.5, "take_profit_pct": 8.0},
    "long_term":   {"tick_interval": 300, "stop_pct": 3.5, "take_profit_pct": 6.0},
}

# 트레일링 스탑 하락 허용 % (최고가 대비)
TRAILING_STOP_PCT: float = 2.0


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
        self._market_open_notified = False
        self._market_close_notified = False
        self._daily_loss: float = 0.0
        self._daily_loss_date: str = ""

        self._decisions: list[dict[str, Any]] = []
        self._watchlist: dict[str, str] = {}
        self._task: asyncio.Task | None = None

        # 매매 모드
        self.trading_mode: str = "long_term"
        # 트레일링 스탑: {symbol: 최고가}
        self._trailing_stops: dict[str, float] = {}

        # 올랜도킴 기본 관심종목 (우량주 위주)
        _DEFAULT_WATCHLIST: dict[str, str] = {
            "005930": "삼성전자",
            "000660": "SK하이닉스",
            "NVDA": "NVIDIA",
            "AVGO": "Broadcom",
            "TSM": "TSMC",
            "MU": "Micron",
            "AMD": "AMD",
            "MRVL": "Marvell",
            "AMZN": "Amazon",
            "MSFT": "Microsoft",
            "GOOG": "Alphabet",
            "TSLA": "Tesla",
            "VRT": "Vertiv",
            "DELL": "Dell",
        }

        if DEMO_MODE:
            logger.info("[Engine] DEMO_MODE 활성화")
            from core.demo_data import get_demo_watchlist
            for item in get_demo_watchlist():
                self._watchlist[item["ticker"]] = item["name"]
        else:
            self._watchlist = dict(_DEFAULT_WATCHLIST)
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
                now = datetime.now()
                in_market = self._is_market_hours()

                if DEMO_MODE or in_market:
                    await self._tick()

                # 장 시작 알림 (09:00 직후 첫 틱)
                if not DEMO_MODE and in_market and not self._market_open_notified:
                    self._market_open_notified = True
                    self._market_close_notified = False
                    asyncio.create_task(_safe(self._notify_market_open()))

                # 장 마감 알림 (15:30 이후)
                if not DEMO_MODE and not in_market and self._market_open_notified and not self._market_close_notified:
                    if now.time() >= dtime(15, 30):
                        self._market_close_notified = True
                        self._market_open_notified = False
                        asyncio.create_task(_safe(self._notify_market_close()))

                # 모드별 tick interval
                interval = TRADING_MODE_CONFIG.get(self.trading_mode, {}).get("tick_interval", 30)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Engine] 루프 에러: {e}")
                await asyncio.sleep(10)

    def _is_market_hours(self) -> bool:
        now = datetime.now().time()
        return dtime(9, 0) <= now <= dtime(15, 30)

    def _reset_daily_loss_if_needed(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._daily_loss_date:
            self._daily_loss = 0.0
            self._daily_loss_date = today

    def _is_daily_loss_exceeded(self) -> bool:
        self._reset_daily_loss_if_needed()
        return self._daily_loss <= -MAX_DAILY_LOSS

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

        # 손절/익절 자동 체크 (장 중)
        if not DEMO_MODE and self._is_market_hours():
            await self._check_stop_conditions(positions, market_data)
            # 트레일링 스탑 체크
            await self._check_trailing_stops(positions, market_data)
            positions = await self.get_positions()

        # 전략 신호 생성 (기술 지표 기반)
        strategy_signal: dict[str, Any] | None = None
        try:
            strategy_signal = self._generate_strategy_signal(market_data, positions)
            if strategy_signal:
                logger.info(f"[Engine] 전략 신호: {strategy_signal.get('decision')} "
                            f"{strategy_signal.get('ticker')} score={strategy_signal.get('score', 0):.2f}")
        except Exception as e:
            logger.warning(f"[Engine] 전략 신호 생성 오류: {e}")

        try:
            decision = await self.judge.judge(
                market_data=market_data,
                positions=positions,
                watchlist=self._watchlist,
                trading_mode=self.trading_mode,
            )
            self.llm_call_count += 1

            # 전략 신호와 LLM 판단 통합 (전략 BUY + LLM BUY/HOLD → 우선 실행)
            final_decision = self._merge_signals(strategy_signal, decision)

            self._decisions.insert(0, {**final_decision, "timestamp": datetime.now().isoformat(timespec="seconds")})
            self._decisions = self._decisions[:50]

            from api.websocket import broadcast
            await broadcast({"type": "decision", "data": final_decision})

            if final_decision.get("decision") in ("BUY", "SELL"):
                await self._execute(final_decision, positions, market_data)
        except Exception as e:
            logger.error(f"[Engine] LLM 판단 에러: {e}")

    def set_trading_mode(self, mode: str) -> None:
        """매매 모드 변경.

        Args:
            mode: "scalping" | "day_trading" | "swing" | "long_term"
        """
        if mode not in TRADING_MODE_CONFIG:
            raise ValueError(f"지원하지 않는 모드: {mode}. 허용: {list(TRADING_MODE_CONFIG.keys())}")
        self.trading_mode = mode
        cfg = TRADING_MODE_CONFIG[mode]
        logger.info(f"[Engine] 매매 모드 변경: {mode} "
                    f"(tick={cfg['tick_interval']}s, "
                    f"stop={cfg['stop_pct']}%, tp={cfg['take_profit_pct']}%)")

    def _generate_strategy_signal(
        self,
        market_data: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """현재 매매 모드에 맞는 전략 신호 생성."""
        try:
            held = {p.get("symbol") for p in positions}
            mode = self.trading_mode

            if mode == "scalping":
                from core.strategy.scalping import ScalpingStrategy
                strategy = ScalpingStrategy()
            elif mode == "day_trading":
                from core.strategy.day_trading import DayTradingStrategy
                strategy = DayTradingStrategy()
            elif mode == "swing":
                from core.strategy.swing import SwingStrategy
                strategy = SwingStrategy()
            else:
                return None  # long_term은 LLM에 위임

            # 미보유 종목만 신호 대상
            filtered_data = {t: d for t, d in market_data.items() if t not in held}
            signals = strategy.generate_signals(filtered_data)

            if not signals:
                return None

            # 점수가 가장 높은 BUY 신호 선택
            buy_signals = [s for s in signals if s.signal_type.value == "BUY"]
            if not buy_signals:
                return None

            best = max(buy_signals, key=lambda s: s.score)
            cfg = TRADING_MODE_CONFIG.get(mode, {})
            price = best.price or 0
            qty = max(1, int(MAX_PER_SLOT // price)) if price > 0 else 1

            return {
                "decision": "BUY",
                "ticker": best.symbol,
                "quantity": qty,
                "confidence": min(99, int(best.score + 50)),
                "reason": f"[{mode.upper()}] {best.reason}",
                "score": best.score,
                "source": "strategy",
            }
        except Exception as e:
            logger.warning(f"[Engine] 전략 신호 생성 실패: {e}")
            return None

    @staticmethod
    def _merge_signals(
        strategy: dict[str, Any] | None,
        llm: dict[str, Any],
    ) -> dict[str, Any]:
        """전략 신호 + LLM 판단 통합.

        SELL은 LLM 우선.
        BUY: 전략 BUY + LLM BUY → 전략 신호 채택 (더 구체적인 지표 기반).
        BUY: 전략 BUY + LLM HOLD → 전략 신호 채택 (기술 지표 신뢰).
        그 외: LLM 판단 그대로.
        """
        if llm.get("decision") == "SELL":
            return llm

        if strategy and strategy.get("decision") == "BUY":
            if llm.get("decision") in ("BUY", "HOLD"):
                merged = dict(strategy)
                merged["reason"] = (
                    strategy.get("reason", "") + " | LLM: " + llm.get("reason", "")
                )
                return merged

        return llm

    async def _check_trailing_stops(
        self,
        positions: list[dict[str, Any]],
        market_data: dict[str, Any],
    ) -> None:
        """트레일링 스탑: 최고가 대비 TRAILING_STOP_PCT% 하락 시 매도."""
        for p in positions:
            sym = p.get("symbol", "")
            current = market_data.get(sym, {}).get("current_price", 0) or p.get("current_price", 0)
            qty = p.get("quantity", 0)

            if current <= 0 or qty <= 0:
                continue

            # 최고가 갱신
            peak = self._trailing_stops.get(sym, current)
            if current > peak:
                self._trailing_stops[sym] = current
                peak = current

            # 최고가 대비 하락폭 체크
            drawdown_pct = (peak - current) / peak * 100 if peak > 0 else 0
            if drawdown_pct >= TRAILING_STOP_PCT:
                reason = (
                    f"트레일링 스탑 발동: 최고가 {peak:,.0f} → 현재 {current:,.0f} "
                    f"(-{drawdown_pct:.1f}% >= {TRAILING_STOP_PCT}%)"
                )
                logger.info(f"[Engine] {sym} {reason}")
                await self._execute(
                    {"decision": "SELL", "ticker": sym, "quantity": qty,
                     "confidence": 90, "reason": reason},
                    positions,
                    market_data,
                )
                self._trailing_stops.pop(sym, None)

    async def _check_stop_conditions(
        self,
        positions: list[dict[str, Any]],
        market_data: dict[str, Any],
    ) -> None:
        for p in positions:
            sym = p.get("symbol", "")
            current = market_data.get(sym, {}).get("current_price", 0) or p.get("current_price", 0)
            stop = p.get("stop_price", 0)
            target = p.get("target_price", 0)
            qty = p.get("quantity", 0)

            if current <= 0 or qty <= 0:
                continue

            reason = ""
            if stop > 0 and current <= stop:
                reason = f"손절가 도달 ({current:,.0f} <= {stop:,.0f})"
            elif target > 0 and current >= target:
                reason = f"익절가 도달 ({current:,.0f} >= {target:,.0f})"

            if reason:
                logger.info(f"[Engine] {sym} {reason} → 자동 매도")
                await self._execute(
                    {"decision": "SELL", "ticker": sym, "quantity": qty,
                     "confidence": 95, "reason": reason},
                    positions,
                    market_data,
                )

    async def _execute(
        self,
        decision: dict[str, Any],
        positions: list[dict[str, Any]],
        market_data: dict[str, Any],
    ) -> None:
        ticker = decision.get("ticker", "")
        action = decision.get("decision", "")
        reason = decision.get("reason", "")

        if not ticker or not action:
            return

        if DEMO_MODE:
            logger.info(f"[Engine][DEMO] {action} {ticker}")
            from notifications.telegram_bot import notify_trade
            asyncio.create_task(_safe(notify_trade(action, ticker, decision.get("quantity", 0),
                                                   0, 0, 0, reason)))
            return

        if self._is_daily_loss_exceeded():
            logger.warning(f"[Engine] 일 손실 한도 초과, 주문 차단: {ticker}")
            return

        held_symbols = [p.get("symbol") for p in positions]
        current_price = market_data.get(ticker, {}).get("current_price", 0)

        if action == "BUY":
            if ticker in held_symbols:
                logger.info(f"[Engine] 이미 보유 중: {ticker}")
                return
            if len(held_symbols) >= MAX_SLOTS:
                logger.warning(f"[Engine] 슬롯 한도 초과 ({MAX_SLOTS}종목)")
                return
            if current_price <= 0:
                logger.warning(f"[Engine] {ticker} 현재가 없음, 매수 건너뜀")
                return

            qty = max(1, int(MAX_PER_SLOT // current_price))
            mode_cfg = TRADING_MODE_CONFIG.get(self.trading_mode, {})
            _stop_pct = mode_cfg.get("stop_pct", STOP_LOSS_PCT)
            _tp_pct = mode_cfg.get("take_profit_pct", TAKE_PROFIT_PCT)
            stop_price = round(current_price * (1 - _stop_pct / 100), 0)
            target_price = round(current_price * (1 + _tp_pct / 100), 0)

            try:
                from core.broker.kis import KISBroker
                broker = KISBroker()
                broker.connect()
                order = broker.buy_market(ticker, qty)
                logger.info(f"[Engine] 매수 주문: {ticker} {qty}주 @ {current_price:,.0f}원")

                from database.models import PositionRecord
                self.position_repo.upsert(PositionRecord(
                    symbol=ticker,
                    quantity=qty,
                    avg_price=current_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    market="KOSPI",
                    strategy=self.trading_mode,
                ))

                from database.models import Trade
                self.trade_repo.save(Trade(
                    symbol=ticker,
                    side="BUY",
                    order_type="MARKET",
                    quantity=qty,
                    price=current_price,
                    status="FILLED",
                    market="KOSPI",
                    strategy=self.trading_mode,
                ))

                from notifications.telegram_bot import notify_trade
                asyncio.create_task(_safe(notify_trade(
                    "BUY", ticker, qty, current_price, stop_price, target_price, reason
                )))
            except Exception as e:
                logger.error(f"[Engine] 매수 실패 {ticker}: {e}")

        elif action == "SELL":
            pos = next((p for p in positions if p.get("symbol") == ticker), None)
            if pos is None:
                logger.warning(f"[Engine] 미보유 종목 SELL 시도: {ticker}")
                return

            qty = pos.get("quantity", 0)
            avg_price = pos.get("avg_price", 0)

            try:
                from core.broker.kis import KISBroker
                broker = KISBroker()
                broker.connect()
                order = broker.sell_market(ticker, qty)
                logger.info(f"[Engine] 매도 주문: {ticker} {qty}주 @ {current_price:,.0f}원")

                pnl = (current_price - avg_price) * qty if current_price > 0 and avg_price > 0 else 0
                pnl_pct = round((current_price - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0
                self._daily_loss += pnl

                self.position_repo.delete(ticker)

                from database.models import Trade
                self.trade_repo.save(Trade(
                    symbol=ticker,
                    side="SELL",
                    order_type="MARKET",
                    quantity=qty,
                    price=current_price,
                    status="FILLED",
                    market="KOSPI",
                    strategy="orlando_kim",
                    pnl=pnl,
                ))

                from notifications.telegram_bot import notify_trade
                asyncio.create_task(_safe(notify_trade(
                    "SELL", ticker, qty, current_price, 0, 0, reason, pnl_pct=pnl_pct
                )))
            except Exception as e:
                logger.error(f"[Engine] 매도 실패 {ticker}: {e}")

    async def get_portfolio(self) -> dict[str, Any]:
        if DEMO_MODE:
            from core.demo_data import get_demo_portfolio
            return get_demo_portfolio()
        try:
            data = await self.fetcher.fetch_portfolio()
            return data
        except Exception as e:
            logger.error(f"[Engine] 포트폴리오 조회 실패: {e}")
            return {"total_value": 0, "cash": 0, "return_pct": 0.0, "seed": SEED_AMOUNT}

    async def get_positions(self) -> list[dict[str, Any]]:
        if DEMO_MODE:
            from core.demo_data import get_demo_positions
            return get_demo_positions()

        # KIS 잔고 우선, 500 오류 시 DB 폴백
        try:
            kis_positions = await self.fetcher.fetch_kis_positions()
            if kis_positions:
                return kis_positions
        except Exception as e:
            logger.warning(f"[Engine] KIS 포지션 조회 실패, DB 폴백: {e}")

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
                item["volume_ratio"] = data.get("volume_ratio", 0)
                item["above_ma20"] = data.get("above_ma20", False)
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
                item["volume_ratio"] = None
                item["above_ma20"] = None
            result.append(item)
        return result

    async def get_return_history(self) -> list[dict[str, Any]]:
        if DEMO_MODE:
            from core.demo_data import get_demo_return_history
            return get_demo_return_history(30)
        return []

    def add_to_watchlist(self, ticker: str, name: str = "") -> None:
        self._watchlist[ticker] = name

    def remove_from_watchlist(self, ticker: str) -> None:
        self._watchlist.pop(ticker, None)

    async def _notify_market_open(self) -> None:
        from notifications.telegram_bot import notify_market_open
        positions = await self.get_positions()
        await notify_market_open(positions)

    async def _notify_market_close(self) -> None:
        from notifications.telegram_bot import notify_market_close
        portfolio = await self.get_portfolio()
        positions = await self.get_positions()
        await notify_market_close(portfolio, positions, self._daily_loss)


async def _safe(coro: Any) -> None:
    try:
        await coro
    except Exception as e:
        logger.warning(f"[Engine] 알림 실패: {e}")
