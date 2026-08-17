import asyncio
import os
import time as _time
from datetime import datetime, time as dtime
from typing import Any

from loguru import logger

from config.settings import KIS_MOCK
from core.llm_judge import LLMJudge
from core.risk_manager import calc_atr_stop, calc_position_size, kelly_position_size
from core.factor_score import score_ticker, rank_tickers, MIN_SCORE_TO_TRADE
from core.sector_filter import is_sector_favorable
from database.db import get_db
from database.models import PositionRepository, TradeRepository

DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() == "true"
SEED_AMOUNT: int = int(os.getenv("SEED_AMOUNT", "2011811"))
MAX_SLOTS: int = 2                              # 201만원 시드 → 2종목 집중투자
MAX_PER_SLOT: int = SEED_AMOUNT // MAX_SLOTS   # 종목당 ~100만원
STOP_LOSS_PCT: float = 2.0                     # 작은 시드 → 손실 빠르게 컷
TAKE_PROFIT_PCT: float = 5.0
MAX_DAILY_LOSS: int = int(SEED_AMOUNT * 0.03)  # 일 손실 한도 3% (~6만원)

# 매매 모드별 설정
TRADING_MODE_CONFIG: dict[str, dict[str, Any]] = {
    "scalping":    {"tick_interval": 10,  "stop_pct": 0.8, "take_profit_pct": 1.5},
    "day_trading": {"tick_interval": 30,  "stop_pct": 1.5, "take_profit_pct": 3.0},
    "swing":       {"tick_interval": 300, "stop_pct": 2.0, "take_profit_pct": 5.0},
    "long_term":   {"tick_interval": 300, "stop_pct": 2.5, "take_profit_pct": 8.0},
}

# 트레일링 스탑 하락 허용 % (최고가 대비)
TRAILING_STOP_PCT: float = 1.5

# 최대 보유 기간 (일) — 이 초과 시 수익/손실 무관 청산 (기회비용 관리)
MAX_HOLD_DAYS: int = 10


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
        self.alert_monitor: "AlertMonitor | None" = None

        # 손절 후 재진입 차단: {symbol: monotonic_timestamp}
        self._sell_cooldown: dict[str, float] = {}
        self._SELL_COOLDOWN_SECS: float = 86400.0  # 24시간

        # 매매 모드 (환경변수로 영속화)
        self.trading_mode: str = os.getenv("TRADING_MODE", "swing")
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

        # 마켓 리짐 캐시
        self._market_regime: dict[str, Any] = {"regime": "neutral"}
        self._regime_ts: float = 0.0
        self._REGIME_TTL: float = 1800.0  # 30분

        # 팩터 스코어 캐시 (tick마다 갱신)
        self._factor_scores: dict[str, float] = {}

        # 분할매수 접근 알림 중복 방지: {ticker_티어_approaching: bool}
        self._approaching_alerts: dict[str, bool] = {}

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
            "GE": "GE Aerospace",    # 방산·항공엔진 방어주, 적정가 $363
            "BE": "Bloom Energy",     # AI 전력 인프라, 적정가 $230
            "DDOG": "Datadog",        # 소프트웨어 저평가 회복주
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
        if self.alert_monitor is None:
            from core.alert_monitor import AlertMonitor
            self.alert_monitor = AlertMonitor(self.fetcher)
        await self.alert_monitor.start()
        # APScheduler 스케줄러 시작
        try:
            from core.scheduler import setup_scheduler
            setup_scheduler(self)
        except Exception as _sched_err:
            logger.warning(f"[Engine] 스케줄러 시작 실패 (무시): {_sched_err}")
        # 시작시 실제 KIS 잔고 동기화 (SEED + DB 포지션)
        asyncio.create_task(_safe(self._sync_positions_on_start()))
        # KIS 체결 이력 → 로컬 DB 동기화 (기기 간 매매일지 일치)
        asyncio.create_task(_safe(self._sync_trade_history_from_kis()))
        from notifications.telegram_bot import notify_start
        asyncio.create_task(_safe(notify_start()))

    async def stop(self) -> None:
        self.running = False
        try:
            from core.scheduler import shutdown_scheduler
            shutdown_scheduler()
        except Exception:
            pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # 아직 실행 중인 비동기 작업들 취소 (주문 중복 방지)
        tasks = [t for t in asyncio.all_tasks()
                 if t is not asyncio.current_task() and not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("[Engine] 봇 중지")
        from notifications.telegram_bot import notify_stop
        await _safe(notify_stop())

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

                # 나스닥 정규장 시작 알림 (22:30 KST) + 올랜도킴 야간 리포트
                if not DEMO_MODE and self._is_nasdaq_hours() and not self._nasdaq_open_notified:
                    self._nasdaq_open_notified = True
                    self._nasdaq_close_notified = False
                    from notifications.telegram_bot import notify_nasdaq_open, notify_daily_orlando
                    asyncio.create_task(_safe(notify_nasdaq_open(await self.get_positions())))
                    market_data_snap = getattr(self, "_last_market_data", {})
                    asyncio.create_task(_safe(notify_daily_orlando(market_data_snap)))

                # 나스닥 장 종료 리셋 (다음 날 재알림 위해)
                if not DEMO_MODE and not self._is_nasdaq_hours() and not self._is_premarket_hours() and self._nasdaq_open_notified:
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

    def _is_premarket_hours(self) -> bool:
        """나스닥 프리마켓 04:00~09:30 ET (KST 17:00~22:30)."""
        from zoneinfo import ZoneInfo
        import datetime as _dt
        now_et = _dt.datetime.now(ZoneInfo("America/New_York"))
        premarket_open  = now_et.replace(hour=4,  minute=0, second=0, microsecond=0)
        premarket_close = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        return premarket_open <= now_et < premarket_close

    def _is_afterhours(self) -> bool:
        """애프터마켓 16:00~20:00 ET."""
        from zoneinfo import ZoneInfo
        import datetime as _dt
        now_et = _dt.datetime.now(ZoneInfo("America/New_York"))
        ah_open  = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        ah_close = now_et.replace(hour=20, minute=0, second=0, microsecond=0)
        return ah_open <= now_et <= ah_close

    def _is_any_market_hours(self) -> bool:
        return self._is_market_hours() or self._is_nasdaq_hours() \
               or self._is_premarket_hours() or self._is_afterhours()

    def _reset_daily_loss_if_needed(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._daily_loss_date:
            # 날짜 바뀌면 메모리 초기화, DB는 날짜별로 유지
            self._daily_loss = 0.0
            self._daily_loss_date = today
        else:
            # 재시작 시 오늘 손실 DB에서 복원
            if self._daily_loss == 0.0:
                try:
                    row = self.position_repo.db.execute_one(
                        "SELECT loss FROM daily_loss WHERE date=?", (today,)
                    )
                    if row:
                        self._daily_loss = float(row["loss"])
                except Exception:
                    pass

    def _persist_daily_loss(self) -> None:
        """오늘 손실을 DB에 저장 — 재시작 후에도 유지."""
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            self.position_repo.db.execute(
                "INSERT INTO daily_loss(date, loss) VALUES(?,?) "
                "ON CONFLICT(date) DO UPDATE SET loss=excluded.loss",
                (today, self._daily_loss),
            )
        except Exception as e:
            logger.debug(f"[Engine] 일손실 저장 실패: {e}")

    def _is_daily_loss_exceeded(self) -> bool:
        self._reset_daily_loss_if_needed()
        return self._daily_loss < -MAX_DAILY_LOSS

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
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        # 10틱(약 5분)마다 실제 잔고로 SEED_AMOUNT 자동 갱신
        if not DEMO_MODE and self._tick_count % 10 == 0:
            asyncio.create_task(_safe(self._update_seed_amount()))

        from core.broker.kis import KISBroker as _KISBroker

        all_tickers = list(self._watchlist.keys())
        if not all_tickers:
            return

        # ── 장 시간에 따라 분석 대상 종목 필터링 ─────────────────────────────
        kospi_open   = self._is_market_hours()
        # KIS Open API는 프리마켓/애프터마켓 주문 미지원 → 정규장만 허용
        nasdaq_open  = self._is_nasdaq_hours()
        if not DEMO_MODE:
            tickers = []
            for t in all_tickers:
                if _KISBroker._is_overseas(t):
                    if nasdaq_open:
                        tickers.append(t)
                    else:
                        logger.debug(f"[Engine] 나스닥 마감 — {t} 패스")
                else:
                    if kospi_open:
                        tickers.append(t)
                    else:
                        logger.debug(f"[Engine] 코스피 마감 — {t} 패스")
            if not tickers:
                logger.info("[Engine] 분석 대상 종목 없음 (모든 시장 마감)")
                return
        else:
            tickers = all_tickers

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

        # 올랜도킴 리포트용 최신 시세 저장
        self._last_market_data = market_data

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

            # 마켓 리짐 조회 (30분 캐시)
            try:
                from core.market_filter import get_market_regime
                now_mono = _time.monotonic()
                if not self._market_regime.get("regime") or (now_mono - self._regime_ts) > self._REGIME_TTL:
                    self._market_regime = get_market_regime()
                    self._regime_ts = now_mono
                regime = self._market_regime.get("regime", "neutral")
                logger.debug(f"[Engine] 마켓 리짐: {regime} (QQQ {self._market_regime.get('pct_from_ma200', 0):+.1f}% vs MA200)")
            except Exception as e:
                logger.debug(f"[Engine] 마켓 리짐 조회 실패: {e}")
                regime = "neutral"

            # 실시간 뉴스 수집 (5분 캐시)
            try:
                from core.news_fetcher import fetch_news_context
                news_context = await fetch_news_context()
                logger.debug(f"[Engine] 뉴스: {news_context.get('summary', '')[:80]}")
            except Exception as e:
                logger.debug(f"[Engine] 뉴스 수집 실패: {e}")

        # 팩터 스코어 계산 (미보유 종목만 랭킹)
        factor_scores: dict[str, float] = {}
        try:
            held_syms = {p.get("symbol") for p in await self.get_positions()}
            ranked = rank_tickers(market_data, held_syms, regime=self._market_regime.get("regime", "neutral"))
            factor_scores = dict(ranked)
            self._factor_scores = factor_scores
            top3 = [(t, s) for t, s in ranked if t not in held_syms][:3]
            if top3:
                logger.info(
                    f"[Engine] 팩터 TOP3: "
                    + " | ".join(f"{t} {s:.0f}점" for t, s in top3)
                )
        except Exception as e:
            logger.debug(f"[Engine] 팩터 스코어 계산 실패: {e}")

        # 외국인/기관 동향 병합 (국내주식만) — 팩터 계산 성공/실패 무관하게 항상 실행
        if not DEMO_MODE:
            try:
                from core.kis_extra import get_investor_trend
                from core.broker.kis import KISBroker
                kis_broker = self.fetcher._broker
                for ticker in tickers:
                    if not KISBroker._is_overseas(ticker):
                        investor = get_investor_trend(ticker, kis_broker)
                        if ticker in market_data:
                            market_data[ticker].update(investor)
            except Exception as e:
                logger.debug(f"[Engine] 외국인/기관 동향 조회 실패: {e}")

        # Finnhub 감성·인사이더 데이터 market_data에 병합 (해외주식, 30분 캐시)
        if not DEMO_MODE and self._is_nasdaq_hours():
            try:
                from core.finnhub_client import get_news_sentiment, get_insider_trades, get_company_news
                from core.broker.kis import KISBroker as _KFinn
                for ticker, data in market_data.items():
                    if _KFinn._is_overseas(ticker):
                        data["finnhub_sentiment"] = get_news_sentiment(ticker)
                        insider = get_insider_trades(ticker)
                        data["insider_net_shares"] = insider.get("net_buy_shares", 0)
                        data["insider_buy_count"]  = insider.get("buy_count", 0)
                        data["insider_sell_count"] = insider.get("sell_count", 0)
                        data["finnhub_news"]       = get_company_news(ticker, max_items=3)
            except Exception as e:
                logger.debug(f"[Engine] Finnhub 데이터 병합 실패: {e}")

        positions = await self.get_positions()

        # 손절/익절 자동 체크 (코스피 또는 나스닥 장 중)
        if not DEMO_MODE and (self._is_market_hours() or self._is_nasdaq_hours()):
            await self._check_stop_conditions(positions, market_data)
            # 트레일링 스탑 체크
            await self._check_trailing_stops(positions, market_data)
            positions = await self.get_positions()

        # 분할매수 체크 (나스닥/코스피 장 중)
        if not DEMO_MODE and (self._is_market_hours() or self._is_nasdaq_hours()):
            await self._check_tier_buys(positions, market_data)

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
                factor_scores=factor_scores,
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

            # ── 분할매도 ──────────────────────────────────────
            # ※ 리서치 노트 분할매수(tier_) 포지션은 목표가까지 보유 — 분할매도 제외
            strategy_tag_p = p.get("strategy", "")
            is_tier_position = strategy_tag_p.startswith("tier_")
            is_os = _KIS._is_overseas(sym)

            # 모드별 1차 익절 기준
            # day_trading : 해외 +3%, 국내 +1.5%
            # swing       : 해외 +3%, 국내 +2.5%  ← 201만원 스윙 핵심
            if self.trading_mode == "day_trading":
                first_tp = 3.0 if is_os else 1.5
            elif self.trading_mode == "swing":
                first_tp = 3.0 if is_os else 2.5
            else:
                first_tp = None  # scalping / long_term 은 분할매도 없음

            if (
                first_tp is not None
                and sym not in self._partial_sold
                and not is_tier_position
                and pnl_pct >= first_tp
                and qty >= 2
            ):
                half = qty // 2
                reason = (
                    f"분할매도 1차: +{pnl_pct:.1f}% 도달 → {half}주 익절 "
                    f"(나머지 {qty - half}주 트레일링 스탑 {TRAILING_STOP_PCT}% 관리)"
                )
                logger.info(f"[Engine] {sym} {reason}")
                self._partial_sold[sym] = current
                self._trailing_stops[sym] = current  # 현재가 기준 트레일링 스탑 재설정
                await self._execute(
                    {"decision": "SELL", "ticker": sym, "quantity": half,
                     "confidence": 90, "reason": reason},
                    positions, market_data,
                )
                continue

            # ── 최대 보유 기간 초과 강제 청산 ─────────────────────
            # 201만원 소액 시드: 기회비용 관리, 애매한 종목은 슬롯 점유 방지
            opened_at_str = p.get("opened_at", "")
            if opened_at_str and not is_tier_position:
                try:
                    from datetime import date
                    opened_date = datetime.fromisoformat(str(opened_at_str)).date()
                    hold_days = (date.today() - opened_date).days
                    if hold_days >= MAX_HOLD_DAYS:
                        hold_reason = (
                            f"최대 보유 기간 초과 ({hold_days}일 >= {MAX_HOLD_DAYS}일) "
                            f"현재 손익: {pnl_pct:+.1f}%"
                        )
                        logger.info(f"[Engine] {sym} {hold_reason} → 강제 청산")
                        self._partial_sold.pop(sym, None)
                        self._trailing_stops.pop(sym, None)
                        await self._execute(
                            {"decision": "SELL", "ticker": sym, "quantity": qty,
                             "confidence": 80, "reason": hold_reason},
                            positions, market_data,
                        )
                        continue
                except Exception:
                    pass

            # ── 손절 / 전량 익절 ───────────────────────────
            reason = ""
            if stop > 0 and current <= stop:
                reason = f"손절가 도달 ({current:,.2f} <= {stop:,.2f})"
            elif target > 0 and current >= target:
                reason = f"익절가 도달 ({current:,.2f} >= {target:,.2f})"

            if reason:
                logger.info(f"[Engine] {sym} {reason} → 전량 매도")
                self._partial_sold.pop(sym, None)
                self._trailing_stops.pop(sym, None)
                await self._execute(
                    {"decision": "SELL", "ticker": sym, "quantity": qty,
                     "confidence": 95, "reason": reason},
                    positions, market_data,
                )

    async def _check_tier_buys(
        self,
        positions: list[dict[str, Any]],
        market_data: dict[str, Any],
    ) -> None:
        """리서치 노트 분할매수 가격 도달 시 자동 매수 집행."""
        if DEMO_MODE:
            return
        # 약세장이면 분할매수도 차단
        if self._market_regime.get("regime") == "bear":
            return

        try:
            from database.db import get_db
            rows = get_db().execute(
                "SELECT ticker, buy_tier_1, buy_tier_2, buy_tier_3, stop_price, target_price, toss_alert_only "
                "FROM research_notes WHERE buy_tier_1 > 0 OR buy_tier_2 > 0 OR buy_tier_3 > 0",
                ()
            )
        except Exception as e:
            logger.debug(f"[Engine] 분할매수 리서치 조회 실패: {e}")
            return

        held = {p.get("symbol") for p in positions}

        for row in rows:
            ticker = row["ticker"]
            current = market_data.get(ticker, {}).get("current_price", 0)
            if current <= 0:
                continue

            # 각 티어별 체크 (이미 보유 중인 경우 추가매수 허용)
            tiers = [
                (row["buy_tier_1"], "1차"),
                (row["buy_tier_2"], "2차"),
                (row["buy_tier_3"], "3차"),
            ]
            for tier_price, tier_label in tiers:
                if not tier_price or tier_price <= 0:
                    continue

                toss_only = bool(row["toss_alert_only"] if row["toss_alert_only"] is not None else 0)
                pct_away = (current - tier_price) / tier_price * 100
                alert_key = f"{ticker}_{tier_label}_approaching"

                # ── 접근 알림: 매수가 5% 이내 도달 시 텔레그램 선알림 ──────
                if 0 < pct_away <= 5.0:
                    if not self._approaching_alerts.get(alert_key):
                        self._approaching_alerts[alert_key] = True
                        from notifications.telegram_bot import _send
                        account_tag = "📲 토스에서 직접 매수하세요!" if toss_only else "🤖 KIS 자동매수 예정"
                        is_os = ticker.isalpha() and not ticker.startswith("0")
                        price_str = f"${current:,.2f}" if is_os else f"{current:,.0f}원"
                        tier_str  = f"${tier_price:,.2f}" if is_os else f"{tier_price:,.0f}원"
                        asyncio.create_task(_safe(_send(
                            f"⚠️ <b>매수가 접근!</b>\n"
                            f"종목: <code>{ticker}</code>\n"
                            f"현재가: <b>{price_str}</b>\n"
                            f"🎯 {tier_label} 매수가: <b>{tier_str}</b> ({pct_away:.1f}% 남음)\n"
                            f"{account_tag}"
                        )))
                elif pct_away > 5.0:
                    self._approaching_alerts.pop(alert_key, None)

                # 현재가가 티어 가격 이하로 내려온 경우
                if current > tier_price:
                    continue

                # ── 토스 알림 전용 종목: 자동매수 없이 알림만 ──────────────
                if toss_only:
                    alert_hit_key = f"{ticker}_{tier_label}_hit"
                    if not self._approaching_alerts.get(alert_hit_key):
                        self._approaching_alerts[alert_hit_key] = True
                        from notifications.telegram_bot import _send
                        is_os = ticker.isalpha() and not ticker.startswith("0")
                        price_str = f"${current:,.2f}" if is_os else f"{current:,.0f}원"
                        tier_str  = f"${tier_price:,.2f}" if is_os else f"{tier_price:,.0f}원"
                        asyncio.create_task(_safe(_send(
                            f"🔔 <b>매수가 도달!</b>\n"
                            f"종목: <code>{ticker}</code>\n"
                            f"현재가: <b>{price_str}</b>\n"
                            f"✅ {tier_label} 매수가 <b>{tier_str}</b> 도달\n"
                            f"📲 <b>토스증권에서 지금 바로 매수하세요!</b>"
                        )))
                    continue  # KIS 자동매수 건너뜀

                # ── KIS 자동매수 ─────────────────────────────────────────────
                already_bought = any(
                    p.get("symbol") == ticker and p.get("strategy", "").startswith(f"tier_{tier_label}")
                    for p in positions
                )
                if already_bought:
                    continue

                if len(held) >= MAX_SLOTS and ticker not in held:
                    logger.info(f"[Engine] {ticker} {tier_label} 분할매수 대기 — 슬롯 한도")
                    break

                reason = (
                    f"리서치 노트 {tier_label} 분할매수 — "
                    f"목표가 ${row['target_price']:,.0f} / 손절 ${row['stop_price']:,.0f}"
                )
                logger.info(f"[Engine] {ticker} {tier_label} 분할매수 진입 ({current:,.2f} <= {tier_price:,.2f})")

                await self._execute(
                    {
                        "decision": "BUY",
                        "ticker": ticker,
                        "confidence": 80,
                        "reason": reason,
                        "strategy_override": f"tier_{tier_label}",
                    },
                    positions,
                    market_data,
                )
                held.add(ticker)
                break

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
            # 손절 후 24h 재진입 차단
            cooldown_ts = self._sell_cooldown.get(ticker, 0.0)
            if cooldown_ts > 0:
                elapsed = _time.monotonic() - cooldown_ts
                if elapsed < self._SELL_COOLDOWN_SECS:
                    remaining_h = (self._SELL_COOLDOWN_SECS - elapsed) / 3600
                    logger.info(f"[Engine] {ticker} 재진입 차단 — 손절 후 {remaining_h:.1f}h 대기")
                    return
                else:
                    self._sell_cooldown.pop(ticker, None)

            # 경제 이벤트 고위험 기간 매수 차단 (FOMC/CPI/PCE 당일·전일)
            try:
                from core.econ_calendar import is_high_risk_period, get_high_impact_today
                if is_high_risk_period():
                    events = get_high_impact_today()
                    event_names = ", ".join(e["event"] for e in events[:2]) if events else "고영향 이벤트 임박"
                    logger.info(f"[Engine] {ticker} 매수 차단 — 경제 이벤트 고위험 기간 ({event_names})")
                    return
            except Exception as _econ_err:
                logger.debug(f"[Engine] 경제 캘린더 체크 실패 (무시): {_econ_err}")

            # 약세장에서 신규 매수 차단
            regime = self._market_regime.get("regime", "neutral")
            if regime == "bear":
                logger.info(f"[Engine] {ticker} 매수 차단 — 약세장 (QQQ MA200 하단)")
                return

            # 확신도 70% 미만이면 매수 차단 (매매 품질 향상)
            confidence = decision.get("confidence", 0)
            if confidence < 70:
                logger.info(f"[Engine] {ticker} 확신도 부족 ({confidence}% < 70%), 매수 건너뜀")
                return

            # 팩터 스코어 필터 (리서치 노트 분할매수는 면제)
            if not decision.get("strategy_override"):
                factor_score = self._factor_scores.get(ticker, 0)
                if factor_score < MIN_SCORE_TO_TRADE and not DEMO_MODE:
                    logger.info(f"[Engine] {ticker} 팩터 점수 미달 ({factor_score:.0f}/{MIN_SCORE_TO_TRADE}), 매수 건너뜀")
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

            # 해외 주식: 나스닥 정규장 시간에만 매수 (KIS Open API는 프리/애프터마켓 미지원)
            if is_overseas and not self._is_nasdaq_hours():
                logger.info(f"[Engine] {ticker} 나스닥 장 시간 아님, 매수 건너뜀")
                return

            # 진입 타임 필터 (나스닥 개장/마감 직후 30분 고변동성 구간 제외)
            if is_overseas:
                from datetime import datetime as _dt
                now_time = _dt.now().time()
                from datetime import time as _t
                # KST 기준: 22:30~23:00 (개장 직후), 04:30~05:00 (마감 직전)
                in_volatile = (
                    (_t(22, 30) <= now_time <= _t(23, 0)) or
                    (_t(4, 30) <= now_time <= _t(5, 0))
                )
                if in_volatile:
                    logger.info(f"[Engine] {ticker} 나스닥 고변동 시간대 매수 차단")
                    return

            # 어닝 발표 3일 이내 매수 차단 (Finnhub)
            if is_overseas:
                try:
                    from core.finnhub_client import get_earnings_calendar
                    cal = get_earnings_calendar(ticker)
                    days_until = cal.get("days_until")
                    if days_until is not None and 0 <= days_until <= 3:
                        msg = f"{ticker} 어닝 {days_until}일 전 — 매수 차단"
                        logger.info(f"[Engine] {msg}")
                        from notifications.telegram_bot import _send
                        import asyncio as _asyncio
                        _asyncio.create_task(_safe(_send(f"⚠️ {msg}")))
                        return
                except Exception as _earn_err:
                    logger.debug(f"[Engine] 어닝 캘린더 체크 실패 (무시): {_earn_err}")

            # 섹터 모멘텀 필터 (해외주식)
            if is_overseas:
                favorable, sector_info = is_sector_favorable(ticker)
                if not favorable:
                    logger.info(f"[Engine] {ticker} 섹터 역풍 ({sector_info}), 매수 차단")
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

            strategy_tag = decision.get("strategy_override", self.trading_mode)

            # ATR 기반 동적 손절
            atr = market_data.get(ticker, {}).get("atr")
            stop_price = calc_atr_stop(current_price, atr, is_overseas)

            # 목표가: 리서치 노트 목표가 우선, 없으면 손익비 2:1 폴백
            # 올랜도킴 전략 = 리서치 노트 target_price까지 장기 보유가 원칙
            research_target: float = 0.0
            research_stop: float = 0.0
            try:
                from database.db import get_db
                rn = get_db().execute(
                    "SELECT target_price, stop_price FROM research_notes WHERE ticker=?",
                    (ticker,)
                )
                row_rn = rn.fetchone() if rn else None
                if row_rn:
                    research_target = float(row_rn["target_price"] or 0)
                    research_stop   = float(row_rn["stop_price"]   or 0)
            except Exception:
                pass

            risk_per_share = current_price - stop_price
            if research_target > current_price:
                # 리서치 노트 목표가 사용 (올랜도킴 장기 보유 원칙)
                target_price = round(research_target, 2 if is_overseas else 0)
                # 리서치 노트 손절가도 있으면 적용 (더 넓은 ATR 손절이면 ATR 유지)
                if research_stop > 0 and research_stop < stop_price:
                    stop_price = round(research_stop, 2 if is_overseas else 0)
                logger.debug(
                    f"[Engine] {ticker} 리서치 노트 목표가 적용: "
                    f"손절={stop_price} / 목표={target_price} (올랜도킴 장기 보유)"
                )
            else:
                # 리서치 노트 없음 → 손익비 2:1 폴백 (단기 스윙)
                target_price = round(current_price + risk_per_share * 2, 2 if is_overseas else 0)
                logger.debug(
                    f"[Engine] {ticker} ATR 손절: {stop_price} / 목표가: {target_price} (위험/보상=1:2)"
                )

            # 리스크 패리티 포지션 사이징
            usd_krw_rate = self.fetcher._broker.get_usd_krw_rate() if is_overseas else 1300.0
            qty = calc_position_size(
                available_cash=available_cash,
                entry_price=current_price,
                stop_price=stop_price,
                seed_amount=SEED_AMOUNT,
                is_overseas=is_overseas,
                usd_krw=usd_krw_rate,
            )
            if qty <= 0:
                logger.warning(f"[Engine] {ticker} 리스크 사이징 결과 0주 — 매수 건너뜀")
                return

            try:
                broker = self.fetcher._broker
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
                    market="NASDAQ" if is_overseas else "KOSPI",
                    strategy=strategy_tag,
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
                    market="NASDAQ" if is_overseas else "KOSPI",
                    strategy=strategy_tag,
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
                broker = self.fetcher._broker
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
                self._persist_daily_loss()  # 재시작 후에도 한도 유지

                # 손절(마이너스 청산) 시 24h 재진입 차단 등록
                if pnl < 0 and remaining == 0:
                    self._sell_cooldown[ticker] = _time.monotonic()
                    logger.info(f"[Engine] {ticker} 손절 완료 → 24h 재진입 차단 등록")

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
                    market="NASDAQ" if _is_overseas_sell else "KOSPI",
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

    async def _update_seed_amount(self, force: bool = False) -> None:
        """실제 KIS 잔고로 SEED_AMOUNT 갱신 (복리 운용).
        force=True: 시작시 강제 갱신 (1% 제한 없음).
        """
        global SEED_AMOUNT, MAX_PER_SLOT
        try:
            bal = self.fetcher._broker.get_balance()
            new_seed = int(bal.total_equity) if bal.total_equity and bal.total_equity > 0 else 0
            if new_seed <= 0:
                return
            if force or new_seed != SEED_AMOUNT:
                old = SEED_AMOUNT
                SEED_AMOUNT = new_seed
                MAX_PER_SLOT = SEED_AMOUNT // MAX_SLOTS
                # .env 저장
                _env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
                with open(_env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                found = False
                for i, line in enumerate(lines):
                    if line.startswith("SEED_AMOUNT="):
                        lines[i] = f"SEED_AMOUNT={SEED_AMOUNT}\n"
                        found = True
                        break
                if not found:
                    lines.append(f"SEED_AMOUNT={SEED_AMOUNT}\n")
                with open(_env_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                logger.info(f"[Engine] 잔고 갱신: {old:,} → {SEED_AMOUNT:,}원 (종목당 {MAX_PER_SLOT:,}원)")
        except Exception as e:
            logger.debug(f"[Engine] 잔고 갱신 실패 (무시): {e}")

    async def _sync_positions_on_start(self) -> None:
        """서버 시작 시 KIS 실제 잔고와 DB 포지션 동기화."""
        # 1) 잔고 갱신
        await self._update_seed_amount(force=True)
        if DEMO_MODE:
            return
        try:
            # 2) KIS 실제 보유 종목 조회
            kis_positions = await self.fetcher.fetch_kis_positions()
            kis_symbols = {p["symbol"] for p in kis_positions}

            # 3) DB에만 있고 KIS에 없는 포지션 → 청산된 것으로 간주 삭제
            db_positions = self.position_repo.find_all()
            for db_pos in db_positions:
                if db_pos.symbol not in kis_symbols:
                    logger.info(f"[Engine] 포지션 동기화: {db_pos.symbol} DB에만 존재 → 삭제")
                    self.position_repo.delete(db_pos.symbol)

            # 4) KIS에 있고 DB에 없는 포지션 → DB에 추가
            db_syms = {p.symbol for p in self.position_repo.find_all()}
            for kp in kis_positions:
                sym = kp["symbol"]
                if sym not in db_syms and kp.get("quantity", 0) > 0:
                    from core.broker.kis import KISBroker as _K
                    is_os = _K._is_overseas(sym)
                    avg = kp.get("avg_price", 0)
                    cfg = TRADING_MODE_CONFIG.get(self.trading_mode, {})
                    sp = cfg.get("stop_pct", STOP_LOSS_PCT)
                    tp = cfg.get("take_profit_pct", TAKE_PROFIT_PCT)
                    dec = 2 if is_os else 0
                    from database.models import PositionRecord
                    self.position_repo.upsert(PositionRecord(
                        symbol=sym,
                        quantity=kp["quantity"],
                        avg_price=avg,
                        stop_price=round(avg * (1 - sp / 100), dec),
                        target_price=round(avg * (1 + tp / 100), dec),
                        market="NASDAQ" if is_os else "KOSPI",
                        strategy=self.trading_mode,
                    ))
                    logger.info(f"[Engine] 포지션 동기화: {sym} KIS에만 존재 → DB 추가")

            if kis_positions:
                logger.info(f"[Engine] 포지션 동기화 완료 — KIS {len(kis_positions)}개")
        except Exception as e:
            logger.warning(f"[Engine] 포지션 동기화 실패 (무시): {e}")

    async def _sync_trade_history_from_kis(self) -> None:
        """서버 시작 시 KIS 체결 이력을 로컬 DB와 동기화 (기기 간 매매일지 일치)."""
        if DEMO_MODE:
            return
        try:
            # 기존 fetcher의 broker 재사용 (이미 connect + 토큰 발급 완료)
            from core.broker.kis import KISBroker as _K
            broker: _K = self.fetcher._broker  # type: ignore[assignment]
            logger.info("[Engine] KIS 체결 이력 동기화 시작 (당일)")
            # 국내 + 해외 체결 이력 통합
            domestic_orders = broker.get_order_history(days=30)
            overseas_orders = broker.get_overseas_order_history()
            orders = domestic_orders + overseas_orders

            # 기존 DB에 있는 order_id 집합
            existing = {
                row["order_id"]
                for row in self.trade_repo.db.execute(
                    "SELECT order_id FROM trades WHERE order_id != ''", ()
                )
            }

            imported = 0
            for o in orders:
                if not o.order_id or o.order_id in existing:
                    continue
                created_at = o.raw.get("_created_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
                market = o.raw.get("_market", "KOSPI")

                self.trade_repo.db.insert(
                    """INSERT INTO trades
                       (symbol, side, order_type, quantity, price,
                        filled_qty, filled_price, order_id, status,
                        market, strategy, pnl, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        o.symbol,
                        o.side.value,
                        o.order_type.value,
                        o.quantity,
                        o.price,
                        o.filled_qty,
                        o.filled_price,
                        o.order_id,
                        "FILLED",
                        market,
                        "KIS_IMPORT",
                        0.0,  # PnL: 평단가 없어서 0으로 저장 (나중에 포지션 기록과 매칭 가능)
                        created_at,
                        created_at,
                    ),
                )
                existing.add(o.order_id)
                imported += 1

            if imported > 0:
                logger.info(f"[Engine] KIS 체결 이력 {imported}건 DB 동기화 완료 "
                            f"(국내 {len(domestic_orders)}건 + 해외 {len(overseas_orders)}건)")
            else:
                logger.info("[Engine] KIS 체결 이력 동기화: 신규 건 없음")
        except Exception as e:
            logger.warning(f"[Engine] KIS 체결 이력 동기화 실패 (무시): {e}")

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
        import datetime as _dt
        result = []
        today = _dt.date.today()
        cumulative_pnl = 0.0
        for i in range(29, -1, -1):  # 30일 전부터 오늘까지
            d = today - _dt.timedelta(days=i)
            date_str = d.strftime("%Y-%m-%d")
            daily_pnl = self.trade_repo.daily_pnl(date_str)
            cumulative_pnl += daily_pnl
            result.append({
                "date": date_str,
                "pnl": round(daily_pnl, 0),
                "cumulative_pnl": round(cumulative_pnl, 0),
            })
        return result

    def add_to_watchlist(self, ticker: str, name: str = "") -> None:
        self._watchlist[ticker] = name

    def remove_from_watchlist(self, ticker: str) -> None:
        self._watchlist.pop(ticker, None)

    async def _notify_market_open(self) -> None:
        from notifications.telegram_bot import notify_market_open, notify_daily_orlando
        positions = await self.get_positions()
        await notify_market_open(positions)
        # 올랜도킴 매수 모니터링 리포트 (장 시작 시)
        market_data = getattr(self, "_last_market_data", {})
        await notify_daily_orlando(market_data)

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
