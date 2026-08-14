import asyncio
import os
import time as _time
from datetime import datetime, time as dtime
from typing import Any

from loguru import logger

from config.settings import KIS_MOCK
from core.llm_judge import LLMJudge
from database.db import get_db
from database.models import PositionRepository, TradeRepository

DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() == "true"
SEED_AMOUNT: int = int(os.getenv("SEED_AMOUNT", "2000000"))
MAX_SLOTS: int = 4                              # 최대 4종목 동시 보유
MAX_PER_SLOT: int = SEED_AMOUNT // MAX_SLOTS   # 종목당 50만원
STOP_LOSS_PCT: float = 3.5
TAKE_PROFIT_PCT: float = 6.0
MAX_DAILY_LOSS: int = SEED_AMOUNT // 20        # 일 손실 한도 ~10만원

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
        self._nasdaq_open_notified = False
        self._nasdaq_close_notified = False
        self._daily_loss: float = 0.0
        self._daily_loss_date: str = ""
        self._daily_liquidation_done: bool = False  # 14:00 전체 청산 플래그

        self._decisions: list[dict[str, Any]] = []
        self._watchlist: dict[str, str] = {}
        self._task: asyncio.Task | None = None

        # 매매 모드 (환경변수로 영속화)
        self.trading_mode: str = os.getenv("TRADING_MODE", "day_trading")
        # 트레일링 스탑: {symbol: 최고가}
        self._trailing_stops: dict[str, float] = {}
        # 분할매도 1차 완료: {symbol: 1차매도가}
        self._partial_sold: dict[str, float] = {}

        # 시장 필터 캐시
        self._fear_greed_cache: dict[str, Any] = {}
        self._fear_greed_ts: float = 0.0
        self._FEAR_GREED_TTL: float = 300.0  # 5분
        self._kospi_change: float = 0.0
        self._nasdaq_change: float = 0.0

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

                if DEMO_MODE or self._is_any_market_hours():
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

                # 15:20 안전망 — 익절/손절 못한 코스피 포지션 강제 청산
                if not DEMO_MODE and dtime(15, 20) <= now.time() <= dtime(15, 25):
                    await self._close_kospi_before_nasdaq()

                # 나스닥 장 시작 알림
                if not DEMO_MODE and self._is_nasdaq_hours() and not self._nasdaq_open_notified:
                    self._nasdaq_open_notified = True
                    self._nasdaq_close_notified = False
                    from notifications.telegram_bot import notify_nasdaq_open
                    asyncio.create_task(_safe(notify_nasdaq_open(await self.get_positions())))

                # 나스닥 장 종료 리셋
                if not DEMO_MODE and not self._is_nasdaq_hours() and self._nasdaq_open_notified:
                    self._nasdaq_open_notified = False

                # 모드별 tick interval
                interval = TRADING_MODE_CONFIG.get(self.trading_mode, {}).get("tick_interval", 30)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Engine] 루프 에러: {e}")
                await asyncio.sleep(10)

    async def _close_all_positions(self, reason: str = "전체 청산") -> None:
        """보유 중인 모든 포지션 전량 청산."""
        positions = await self.get_positions()
        if not positions:
            logger.info("[Engine] 청산할 포지션 없음")
            return
        logger.info(f"[Engine] 전체 청산 시작: {len(positions)}종목 — {reason}")
        for p in positions:
            sym = p.get("symbol", "")
            qty = p.get("quantity", 0)
            if qty <= 0:
                continue
            await self._execute(
                {"decision": "SELL", "ticker": sym, "quantity": qty,
                 "confidence": 99, "reason": reason},
                positions,
                {sym: {"current_price": p.get("current_price", 0)}},
            )
        from notifications.telegram_bot import _send
        asyncio.create_task(_safe(_send(
            f"🔔 <b>14:00 자동 전체 청산 완료</b>\n"
            f"{len(positions)}종목 매도 → 나스닥 자금 확보"
        )))

    async def _close_kospi_before_nasdaq(self) -> None:
        """15:20 코스피 포지션 전량 청산 — 나스닥 자금 확보."""
        positions = await self.get_positions()
        from core.broker.kis import KISBroker
        for p in positions:
            sym = p.get("symbol", "")
            if KISBroker._is_overseas(sym):
                continue
            if p.get("quantity", 0) <= 0:
                continue
            logger.info(f"[Engine] 장마감 전 코스피 청산: {sym}")
            await self._execute(
                {"decision": "SELL", "ticker": sym, "quantity": p["quantity"],
                 "confidence": 95, "reason": "장마감 전 코스피 청산 — 나스닥 자금 확보"},
                positions,
                {sym: {"current_price": p.get("current_price", 0)}},
            )

    def _is_market_hours(self) -> bool:
        now = datetime.now().time()
        return dtime(9, 0) <= now <= dtime(15, 30)

    def _is_nasdaq_hours(self) -> bool:
        """나스닥 정규장 (서머타임 자동 적용)."""
        from zoneinfo import ZoneInfo
        import datetime as _dt
        now_et = _dt.datetime.now(ZoneInfo("America/New_York"))
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now_et <= market_close

    def _is_any_market_hours(self) -> bool:
        return self._is_market_hours() or self._is_nasdaq_hours()

    def _reset_daily_loss_if_needed(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._daily_loss_date:
            self._daily_loss = 0.0
            self._daily_loss_date = today

    def _is_daily_loss_exceeded(self) -> bool:
        self._reset_daily_loss_if_needed()
        return self._daily_loss <= -MAX_DAILY_LOSS

    def _get_fear_greed_cached(self) -> dict[str, Any]:
        """Fear & Greed 지수 조회 (5분 캐시)."""
        now = _time.monotonic()
        if self._fear_greed_cache and (now - self._fear_greed_ts) < self._FEAR_GREED_TTL:
            return self._fear_greed_cache
        try:
            from core.market_filter import get_fear_greed_index
            result = get_fear_greed_index()
            self._fear_greed_cache = result
            self._fear_greed_ts = now
            return result
        except Exception as e:
            logger.debug(f"[Engine] Fear&Greed 캐시 갱신 실패: {e}")
            return self._fear_greed_cache or {"value": 50, "rating": "Neutral"}

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

        # 시장 필터 데이터 조회
        fear_greed: dict[str, Any] = {"value": 50, "rating": "Neutral"}
        kospi_change: float = 0.0
        nasdaq_change: float = 0.0
        news_context: dict[str, Any] = {}
        if not DEMO_MODE:
            try:
                from core.market_filter import get_fear_greed_index, get_kospi_change, get_nasdaq_change, is_market_bullish
                fear_greed = self._get_fear_greed_cached()
                kospi_change = get_kospi_change()
                nasdaq_change = get_nasdaq_change()
                self._kospi_change = kospi_change
                self._nasdaq_change = nasdaq_change
                bullish = is_market_bullish(kospi_change, fear_greed.get("value", 50))
                logger.debug(
                    f"[Engine] 시장필터: 코스피{kospi_change:+.2f}%, "
                    f"FG={fear_greed.get('value')}({fear_greed.get('rating')}), "
                    f"매수적합={bullish}"
                )
            except Exception as e:
                logger.debug(f"[Engine] 시장 필터 조회 실패: {e}")

            # 실시간 뉴스 수집 (5분 캐시)
            try:
                from core.news_fetcher import fetch_news_context
                news_context = await fetch_news_context()
                logger.debug(f"[Engine] 뉴스: {news_context.get('summary', '')[:80]}")
            except Exception as e:
                logger.debug(f"[Engine] 뉴스 수집 실패: {e}")

            # 외국인/기관 동향 병합 (국내주식만)
            try:
                from core.kis_extra import get_investor_trend
                from core.broker.kis import KISBroker
                kis_broker = KISBroker()
                kis_broker.connect()
                for ticker in tickers:
                    if not KISBroker._is_overseas(ticker):
                        investor = get_investor_trend(ticker, kis_broker)
                        if ticker in market_data:
                            market_data[ticker].update(investor)
            except Exception as e:
                logger.debug(f"[Engine] 외국인/기관 동향 조회 실패: {e}")

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
                fear_greed=fear_greed,
                kospi_change=kospi_change,
                nasdaq_change=nasdaq_change,
                news_context=news_context,
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
        # .env에 저장해서 재시작해도 유지
        _env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        try:
            with open(_env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.startswith("TRADING_MODE="):
                    lines[i] = f"TRADING_MODE={mode}\n"
                    found = True
            if not found:
                lines.append(f"TRADING_MODE={mode}\n")
            with open(_env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logger.warning(f"[Engine] TRADING_MODE .env 저장 실패: {e}")
        cfg = TRADING_MODE_CONFIG[mode]
        stop_pct = cfg["stop_pct"]
        tp_pct = cfg["take_profit_pct"]
        # 기존 포지션 목표가/손절가 재계산
        try:
            positions = self.position_repo.find_all()
            for p in positions:
                from core.broker.kis import KISBroker
                is_os = KISBroker._is_overseas(p.symbol)
                dec = 2 if is_os else 0
                new_stop = round(p.avg_price * (1 - stop_pct / 100), dec)
                new_tp = round(p.avg_price * (1 + tp_pct / 100), dec)
                self.position_repo.db.execute(
                    "UPDATE positions SET stop_price=?, target_price=? WHERE symbol=?",
                    (new_stop, new_tp, p.symbol)
                )
            logger.info(f"[Engine] 모드 변경 → 포지션 {len(positions)}개 목표가 재계산 완료")
        except Exception as e:
            logger.warning(f"[Engine] 포지션 목표가 재계산 실패: {e}")
        logger.info(f"[Engine] 매매 모드 변경: {mode} "
                    f"(tick={cfg['tick_interval']}s, "
                    f"stop={stop_pct}%, tp={tp_pct}%)")

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
        # LLM SELL은 무시 — _check_stop_conditions가 손절/익절을 전담
        if llm.get("decision") == "SELL":
            return {
                "decision": "HOLD", "ticker": llm.get("ticker", ""), "quantity": 0,
                "confidence": 0, "reason": f"[LLM SELL 무시 — 자동 손절/익절 위임] {llm.get('reason', '')}",
            }

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
        from core.broker.kis import KISBroker as _KIS
        for p in positions:
            sym = p.get("symbol", "")
            current = market_data.get(sym, {}).get("current_price", 0) or p.get("current_price", 0)
            stop = p.get("stop_price", 0)
            target = p.get("target_price", 0)
            avg = p.get("avg_price", 0)
            qty = p.get("quantity", 0)

            if current <= 0 or qty <= 0 or avg <= 0:
                continue

            pnl_pct = (current - avg) / avg * 100

            # ── 단타 분할매도 ──────────────────────────────
            # 1차 익절: +2%(KOSPI) 또는 +4%(해외) 도달 시 50% 매도
            # 이후 나머지는 트레일링 스탑 -1%로 관리
            if self.trading_mode == "day_trading" and sym not in self._partial_sold:
                is_os = _KIS._is_overseas(sym)
                first_tp = 4.0 if is_os else 2.0
                if pnl_pct >= first_tp and qty >= 2:
                    half = qty // 2
                    reason = (
                        f"분할매도 1차: +{pnl_pct:.1f}% 도달 → {half}주 익절, "
                        f"나머지 {qty - half}주 트레일링 스탑 관리"
                    )
                    logger.info(f"[Engine] {sym} {reason}")
                    self._partial_sold[sym] = current  # 1차 매도 완료 표시
                    # 트레일링 스탑을 현재가 기준으로 재설정
                    self._trailing_stops[sym] = current
                    await self._execute(
                        {"decision": "SELL", "ticker": sym, "quantity": half,
                         "confidence": 90, "reason": reason},
                        positions, market_data,
                    )
                    continue

            # ── 손절 / 전량 익절 ───────────────────────────
            reason = ""
            if stop > 0 and current <= stop:
                reason = f"손절가 도달 ({current:,.0f} <= {stop:,.0f})"
            elif target > 0 and current >= target:
                reason = f"익절가 도달 ({current:,.0f} >= {target:,.0f})"

            if reason:
                logger.info(f"[Engine] {sym} {reason} → 전량 매도")
                self._partial_sold.pop(sym, None)
                self._trailing_stops.pop(sym, None)
                await self._execute(
                    {"decision": "SELL", "ticker": sym, "quantity": qty,
                     "confidence": 95, "reason": reason},
                    positions, market_data,
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
            # 확신도 70% 미만이면 매수 차단 (매매 품질 향상)
            confidence = decision.get("confidence", 0)
            if confidence < 70:
                logger.info(f"[Engine] {ticker} 확신도 부족 ({confidence}% < 70%), 매수 건너뜀")
                return
            if ticker in held_symbols:
                logger.info(f"[Engine] 이미 보유 중: {ticker}")
                return
            if len(held_symbols) >= MAX_SLOTS:
                logger.warning(f"[Engine] 슬롯 한도 초과 ({MAX_SLOTS}종목)")
                return
            if current_price <= 0:
                logger.warning(f"[Engine] {ticker} 현재가 없음, 매수 건너뜀")
                return

            from core.broker.kis import KISBroker
            is_overseas = KISBroker._is_overseas(ticker)

            # 해외 주식: 나스닥 장 시간 아니면 매수 건너뜀
            if is_overseas and not self._is_nasdaq_hours():
                logger.info(f"[Engine] {ticker} 나스닥 장 시간 아님, 매수 건너뜀")
                return

            # 실제 예수금 조회
            available_cash = 0
            try:
                bal = self.fetcher._broker.get_balance()
                available_cash = bal.cash if bal.cash else 0
            except Exception as e:
                logger.warning(f"[Engine] 잔고 조회 실패 ({e}), 시드 기준 추정")
                # 폴백: 시드 - 현재 포지션 평가액 추정
                invested = sum(p.get("value", 0) for p in positions)
                available_cash = max(0, SEED_AMOUNT - invested)

            # 남은 슬롯 수로 예수금 동적 배분
            remaining_slots = MAX_SLOTS - len(held_symbols)
            budget_per_slot = available_cash / max(remaining_slots, 1)

            if is_overseas:
                usd_budget = budget_per_slot / 1380
                qty = int(usd_budget // current_price)
                # 슬롯 예산 부족해도 전체 예수금으로 1주 살 수 있으면 매수
                if qty == 0 and (available_cash / 1380) >= current_price:
                    qty = 1
            else:
                qty = int(budget_per_slot // current_price)
                # 슬롯 예산 부족해도 전체 예수금으로 1주 살 수 있으면 매수
                if qty == 0 and available_cash >= current_price:
                    qty = 1

            if qty <= 0:
                logger.warning(
                    f"[Engine] {ticker} 매수 불가 — 예수금 {available_cash:,.0f}원 < 현재가 {current_price:,.0f}원"
                )
                return

            # 실제 필요금액이 예수금 초과하면 수량 줄이기
            if available_cash > 0 and available_cash < current_price * qty:
                qty = int(available_cash // current_price)
                if qty <= 0:
                    logger.warning(
                        f"[Engine] {ticker} 잔고 부족 (가용: {available_cash:,.0f}원, 필요: {current_price:,.0f}원)"
                    )
                    return

            mode_cfg = TRADING_MODE_CONFIG.get(self.trading_mode, {})
            _stop_pct = mode_cfg.get("stop_pct", STOP_LOSS_PCT)
            _tp_pct = mode_cfg.get("take_profit_pct", TAKE_PROFIT_PCT)
            # 단타 모드: 코스피는 빠른 회전 (-1.5%/+2%), 나스닥은 변동성 여유 (-2%/+4%)
            if self.trading_mode == "day_trading":
                if is_overseas:
                    _stop_pct, _tp_pct = 2.0, 4.0
                else:
                    _stop_pct, _tp_pct = 1.5, 2.0
            stop_price = round(current_price * (1 - _stop_pct / 100), 2 if is_overseas else 0)
            target_price = round(current_price * (1 + _tp_pct / 100), 2 if is_overseas else 0)

            try:
                broker = KISBroker()
                broker.connect()
                if is_overseas:
                    order = broker.buy_overseas_market(ticker, qty)
                    logger.info(f"[Engine] 해외 매수: {ticker} {qty}주 @ ${current_price:.2f}")
                else:
                    order = broker.buy_market(ticker, qty)
                    logger.info(f"[Engine] 매수 주문: {ticker} {qty}주 @ {current_price:,.0f}원")

                from core.broker.kis import OrderStatus as KOrderStatus
                if order.status == KOrderStatus.REJECTED:
                    logger.warning(f"[Engine] 주문 거부됨: {ticker} — DB 저장 건너뜀")
                    return

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
                    order_id=order.order_id,
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
            from core.broker.kis import KISBroker
            pos = next((p for p in positions if p.get("symbol") == ticker), None)
            if pos is None:
                logger.warning(f"[Engine] 미보유 종목 SELL 시도: {ticker}")
                return

            full_qty = pos.get("quantity", 0)
            # decision에 수량 지정 시 분할매도, 없으면 전량
            sell_qty = decision.get("quantity") or full_qty
            sell_qty = min(sell_qty, full_qty)
            avg_price = pos.get("avg_price", 0)

            _is_overseas_sell = KISBroker._is_overseas(ticker)
            try:
                broker = KISBroker()
                broker.connect()
                if _is_overseas_sell:
                    sell_order = broker.sell_overseas_market(ticker, sell_qty)
                    logger.info(f"[Engine] 해외 매도: {ticker} {sell_qty}주 @ ${current_price:.2f}")
                else:
                    sell_order = broker.sell_market(ticker, sell_qty)
                    logger.info(f"[Engine] 매도 주문: {ticker} {sell_qty}주 @ {current_price:,.0f}원")

                from core.broker.kis import OrderStatus as KOrderStatus
                if sell_order.status == KOrderStatus.REJECTED:
                    logger.warning(f"[Engine] 매도 거부됨: {ticker} — DB 유지")
                    return

                gross_pnl = (current_price - avg_price) * sell_qty if current_price > 0 and avg_price > 0 else 0
                # 수수료 + 세금 차감 (한국투자증권 온라인 기준)
                # 수수료: 편도 0.015% (유관기관 포함 약 0.019%)
                # 증권거래세: 코스피 0.18% (매도 시만)
                _fee_rate = 0.00019  # 수수료 편도 (0.019%)
                _tax_rate = 0.0 if _is_overseas_sell else 0.0018
                buy_fee  = avg_price * sell_qty * _fee_rate
                sell_fee = current_price * sell_qty * (_fee_rate + _tax_rate)
                pnl = round(gross_pnl - buy_fee - sell_fee, 0)
                pnl_pct = round((current_price - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0
                self._daily_loss += pnl

                remaining = full_qty - sell_qty
                if remaining > 0:
                    # 분할매도 — 남은 수량으로 포지션 업데이트
                    from database.models import PositionRecord
                    self.position_repo.upsert(PositionRecord(
                        symbol=ticker, quantity=remaining, avg_price=avg_price,
                        stop_price=pos.get("stop_price", 0),
                        target_price=pos.get("target_price", 0),
                        market=pos.get("market", ""), strategy=self.trading_mode,
                    ))
                else:
                    self.position_repo.delete(ticker)
                    self._partial_sold.pop(ticker, None)

                from database.models import Trade
                self.trade_repo.save(Trade(
                    symbol=ticker,
                    side="SELL",
                    order_type="MARKET",
                    quantity=sell_qty,
                    price=current_price,
                    order_id=sell_order.order_id,
                    status="FILLED",
                    market="KOSPI",
                    strategy=self.trading_mode,
                    pnl=pnl,
                ))

                from notifications.telegram_bot import notify_trade
                asyncio.create_task(_safe(notify_trade(
                    "SELL", ticker, sell_qty, current_price, 0, 0, reason, pnl_pct=pnl_pct
                )))

                # 복리: 매도 후 시드 자동 갱신
                asyncio.create_task(_safe(self._update_seed_amount()))
            except Exception as e:
                logger.error(f"[Engine] 매도 실패 {ticker}: {e}")

    async def _update_seed_amount(self) -> None:
        """매도 후 실현 수익을 시드에 반영 (복리 운용)."""
        global SEED_AMOUNT, MAX_PER_SLOT
        try:
            bal = self.fetcher._broker.get_balance()
            new_seed = int(bal.total_value) if bal.total_value and bal.total_value > 0 else 0
            if new_seed <= 0:
                return
            # 최솟값 보호: 현재 시드보다 10% 이상 늘었을 때만 업데이트
            if new_seed > SEED_AMOUNT * 1.01:
                old = SEED_AMOUNT
                SEED_AMOUNT = new_seed
                MAX_PER_SLOT = SEED_AMOUNT // MAX_SLOTS
                # .env 저장
                _env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
                with open(_env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for i, line in enumerate(lines):
                    if line.startswith("SEED_AMOUNT="):
                        lines[i] = f"SEED_AMOUNT={SEED_AMOUNT}\n"
                        break
                with open(_env_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                logger.info(f"[Engine] 복리 시드 갱신: {old:,} → {SEED_AMOUNT:,}원")
        except Exception as e:
            logger.debug(f"[Engine] 시드 갱신 실패 (무시): {e}")

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

        # KIS 잔고 우선, DB의 stop/target으로 덮어쓰기
        try:
            from core.broker.kis import KISBroker as _KIS
            kis_positions = await self.fetcher.fetch_kis_positions()
            if kis_positions:
                cfg = TRADING_MODE_CONFIG.get(self.trading_mode, {})
                base_stop = cfg.get("stop_pct", STOP_LOSS_PCT)
                base_tp = cfg.get("take_profit_pct", TAKE_PROFIT_PCT)
                for p in kis_positions:
                    avg = p.get("avg_price", 0)
                    if avg <= 0:
                        continue
                    sym = p.get("symbol", "")
                    overseas = _KIS._is_overseas(sym)
                    if self.trading_mode == "day_trading":
                        stop_pct = 2.0 if overseas else 1.5
                        tp_pct   = 4.0 if overseas else 2.0
                    else:
                        stop_pct, tp_pct = base_stop, base_tp
                    dec = 2 if overseas else 0
                    p["stop_price"]   = round(avg * (1 - stop_pct / 100), dec)
                    p["target_price"] = round(avg * (1 + tp_pct  / 100), dec)
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
