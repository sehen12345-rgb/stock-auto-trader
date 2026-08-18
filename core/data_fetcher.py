import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from loguru import logger

from config.settings import KIS_MOCK
from core.broker.kis import KISBroker
from core.indicators import (
    calc_volume_profile,
    compute_all,
    detect_candle_patterns,
    detect_double_bottom,
    detect_support_resistance,
    is_pullback,
    pullback_score,
)

_OHLCV_CACHE: dict[str, tuple[pd.DataFrame, float]] = {}
_OHLCV_TTL = 1800  # OHLCV 30분 캐시 (지표는 자주 바뀌지 않음)

_POSITIONS_CACHE: tuple[list, float] | None = None
_POSITIONS_TTL = 60  # KIS 포지션 1분 캐시 (레이트 리밋 방지)


class DataFetcher:
    def __init__(self) -> None:
        self._broker = KISBroker()
        self._broker.connect()

    async def fetch(self, symbol: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._fetch_sync, symbol)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} 조회 실패 (더미 반환): {e}")
            return self._dummy(symbol)

    def _get_ohlcv_cached(self, symbol: str, is_overseas: bool) -> pd.DataFrame:
        now = time.time()
        cached = _OHLCV_CACHE.get(symbol)
        if cached and (now - cached[1]) < _OHLCV_TTL:
            return cached[0]
        try:
            if is_overseas:
                df = self._broker.get_overseas_ohlcv(symbol, period=252)
            else:
                df = self._broker.get_ohlcv(symbol, period=252)
            _OHLCV_CACHE[symbol] = (df, now)
            return df
        except Exception as e:
            logger.debug(f"[Fetcher] {symbol} OHLCV 조회 실패, 캐시 사용: {e}")
            if cached:
                return cached[0]
            # KIS 실패 시 yfinance 백업
            if is_overseas:
                try:
                    import yfinance as yf
                    ticker_yf = symbol if not symbol.isdigit() else f"{symbol}.KS"
                    df_yf = yf.download(ticker_yf, period="1y", progress=False, auto_adjust=True)
                    if not df_yf.empty:
                        df_yf.columns = [c.lower() for c in df_yf.columns]
                        _OHLCV_CACHE[symbol] = (df_yf, now)
                        logger.debug(f"[Fetcher] {symbol} yfinance 백업 성공 ({len(df_yf)}봉)")
                        return df_yf
                except Exception as e2:
                    logger.debug(f"[Fetcher] {symbol} yfinance 백업 실패: {e2}")
            return pd.DataFrame()

    def _fetch_sync(self, symbol: str) -> dict[str, Any]:
        from core.kis_ws import get_live_price
        is_overseas = self._broker._is_overseas(symbol)
        if is_overseas:
            current_price = self._broker.get_overseas_price(symbol)
            time.sleep(0.3)
            df = self._get_ohlcv_cached(symbol, True)
        else:
            # WebSocket 캐시 우선 — 없으면 REST 폴링
            live = get_live_price(symbol)
            if live:
                current_price = live
                logger.debug(f"[Fetcher] {symbol} WS 캐시 사용: {live:,.0f}")
            else:
                current_price = self._broker.get_current_price(symbol)
                time.sleep(0.3)
            df = self._get_ohlcv_cached(symbol, False)

        closes = df["close"].tolist() if not df.empty else []
        volumes = df["volume"].tolist() if not df.empty else []
        highs = df["high"].tolist() if not df.empty else []

        # 오늘 실시간 거래량
        volume = int(volumes[-1]) if volumes else 0

        ma20_closes = closes[-20:] if len(closes) >= 20 else closes
        ma20 = round(sum(ma20_closes) / len(ma20_closes), 2) if ma20_closes else 0.0

        avg_vol_closes = volumes[-20:] if len(volumes) >= 20 else volumes
        avg_volume_20 = int(sum(avg_vol_closes) / len(avg_vol_closes)) if avg_vol_closes else 0

        week52_high = max(highs[-252:]) if highs else 0.0

        pct_from_high = 0.0
        if week52_high > 0 and current_price > 0:
            pct_from_high = round((week52_high - current_price) / week52_high * 100, 2)

        volume_ratio = round(volume / avg_volume_20, 2) if avg_volume_20 > 0 else 0.0

        # 기술 지표 계산 (try/except 로 봇 중단 방지)
        indicators: dict[str, Any] = {}
        try:
            if not df.empty:
                indicators = compute_all(df)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} 기술 지표 계산 실패: {e}")

        pullback_detected: bool = False
        pullback_info: dict = {}
        try:
            if not df.empty:
                pullback_info = pullback_score(df)
                pullback_detected = pullback_info.get("detected", False)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} pullback 감지 실패: {e}")

        # 캔들 패턴 감지
        candle_patterns: dict = {}
        try:
            if not df.empty:
                candle_patterns = detect_candle_patterns(df)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} 캔들 패턴 감지 실패: {e}")

        # 지지/저항 감지
        support_resistance: dict = {}
        try:
            if not df.empty:
                support_resistance = detect_support_resistance(df)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} 지지저항 감지 실패: {e}")

        # 쌍바닥 패턴
        double_bottom: bool = False
        try:
            if not df.empty:
                double_bottom = detect_double_bottom(df)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} 쌍바닥 감지 실패: {e}")

        # 매물대 계산
        volume_profile: dict = {}
        try:
            if not df.empty:
                volume_profile = calc_volume_profile(df)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} 매물대 계산 실패: {e}")

        result: dict = {
            "ticker": symbol,
            "current_price": current_price,
            "volume": volume,
            "ma20": ma20,
            "avg_volume_20": avg_volume_20,
            "week52_high": week52_high,
            "pct_from_high": pct_from_high,
            "volume_ratio": volume_ratio,
            "above_ma20": current_price > ma20 if ma20 > 0 else False,
            "volume_surge": volume_ratio >= 1.5,
            # 기술 지표
            "rsi": indicators.get("rsi"),
            "macd": indicators.get("macd"),
            "macd_signal": indicators.get("macd_signal"),
            "macd_hist": indicators.get("macd_hist"),
            "bb_upper": indicators.get("bb_upper"),
            "bb_lower": indicators.get("bb_lower"),
            "atr": indicators.get("atr"),
            "ema9": indicators.get("ema9"),
            "ema21": indicators.get("ema21"),
            "pullback_detected": pullback_detected,
            "pullback_score": pullback_info.get("score", 0),
            "pullback_depth_pct": pullback_info.get("depth_pct", 0.0),
            "pullback_reasons": pullback_info.get("reasons", []),
            # 신규 지표
            "adx": indicators.get("adx"),
            "stoch_k": indicators.get("stoch_k"),
            "stoch_d": indicators.get("stoch_d"),
            "vwap": indicators.get("vwap"),
            "pivot": indicators.get("pivot"),
            "r1": indicators.get("r1"),
            "s1": indicators.get("s1"),
            "momentum": indicators.get("momentum"),
            # 쌍바닥
            "double_bottom": double_bottom,
            # 외국인/기관 (기본값 — engine에서 kis_extra로 채움)
            "foreign_net": 0,
            "institution_net": 0,
            "individual_net": 0,
            "foreign_buying": False,
            "program_net": 0,
        }

        # 캔들 패턴 병합
        result.update(candle_patterns)
        # 지지/저항 병합
        result.update(support_resistance)
        # 매물대 병합
        result.update(volume_profile)

        return result

    async def fetch_ohlcv(self, symbol: str, period: int = 60) -> pd.DataFrame:
        try:
            return self._broker.get_ohlcv(symbol, period=period)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} OHLCV 조회 실패: {e}")
            return pd.DataFrame()

    async def fetch_portfolio(self) -> dict[str, Any]:
        import os
        # INITIAL_SEED: 최초 투자 원금 (수익률 기준) — SEED_AMOUNT와 분리
        initial_seed = int(os.getenv("INITIAL_SEED", os.getenv("SEED_AMOUNT", "2000000")))
        current_seed = int(os.getenv("SEED_AMOUNT", "2000000"))

        balance = self._broker.get_balance()
        total_equity = balance.total_equity
        cash = balance.cash

        if total_equity > 0:
            invested = max(0.0, total_equity - cash)
            pnl_amount = total_equity - initial_seed
            pnl_pct = round(pnl_amount / initial_seed * 100, 2) if initial_seed > 0 else 0.0
            return {
                "total_value": total_equity,
                "cash": cash,
                "invested": round(invested, 0),
                "pnl_amount": round(pnl_amount, 0),
                "return_pct": pnl_pct,
                "seed": initial_seed,
                "current_seed": current_seed,
                "api_error": False,
            }
        else:
            # 잔고 조회 실패 (장 외 시간 등) — 캐시된 포지션으로 추정
            positions = await self.fetch_kis_positions()
            invested = round(sum(p.get("value", 0) for p in positions), 0)
            return {
                "total_value": current_seed,
                "cash": current_seed,
                "invested": invested,
                "pnl_amount": 0,
                "return_pct": 0.0,
                "seed": initial_seed,
                "current_seed": current_seed,
                "api_error": True,
            }

    async def fetch_kis_positions(self) -> list[dict[str, Any]]:
        global _POSITIONS_CACHE
        now = time.time()
        if _POSITIONS_CACHE and (now - _POSITIONS_CACHE[1]) < _POSITIONS_TTL:
            return _POSITIONS_CACHE[0]

        result = []

        # ── KOSPI 국내주식 잔고 ───────────────────────────────────────────
        try:
            kospi_positions = self._broker.get_positions()
            for p in kospi_positions:
                pnl_pct = 0.0
                if p.avg_price > 0 and p.current_price > 0:
                    pnl_pct = round((p.current_price - p.avg_price) / p.avg_price * 100, 2)
                result.append({
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "current_price": p.current_price,
                    "value": round(p.current_price * p.quantity, 0),
                    "pnl_pct": pnl_pct,
                    "market": "KOSPI",
                    "stop_price": round(p.avg_price * 0.965, 0),
                    "target_price": round(p.avg_price * 1.06, 0),
                })
        except Exception as e:
            logger.debug(f"[Fetcher] KOSPI 포지션 조회 실패: {e}")

        # ── NASDAQ/NYSE 해외주식 잔고 ────────────────────────────────────
        try:
            overseas_positions = self._broker.get_overseas_positions()
            for p in overseas_positions:
                pnl_pct = 0.0
                if p.avg_price > 0 and p.current_price > 0:
                    pnl_pct = round((p.current_price - p.avg_price) / p.avg_price * 100, 2)
                result.append({
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "current_price": p.current_price,
                    "value": round(p.current_price * p.quantity, 0),
                    "pnl_pct": pnl_pct,
                    "market": "NASDAQ",
                    "stop_price": round(p.avg_price * 0.965, 2),
                    "target_price": round(p.avg_price * 1.06, 2),
                })
        except Exception as e:
            logger.debug(f"[Fetcher] 해외주식 포지션 조회 실패: {e}")

        if result or not _POSITIONS_CACHE:
            _POSITIONS_CACHE = (result, now)
        return _POSITIONS_CACHE[0] if _POSITIONS_CACHE else []

    @staticmethod
    def _dummy(symbol: str) -> dict[str, Any]:
        return {
            "ticker": symbol,
            "current_price": 0.0,
            "volume": 0,
            "ma20": 0.0,
            "avg_volume_20": 0,
            "week52_high": 0.0,
            "pct_from_high": 0.0,
            "volume_ratio": 0.0,
            "above_ma20": False,
            "volume_surge": False,
            # 기술 지표 (더미)
            "rsi": None,
            "macd": None,
            "macd_signal": None,
            "macd_hist": None,
            "bb_upper": None,
            "bb_lower": None,
            "atr": None,
            "ema9": None,
            "ema21": None,
            "pullback_detected": False,
            # 신규 지표 (더미)
            "adx": None,
            "stoch_k": None,
            "stoch_d": None,
            "vwap": None,
            "pivot": None,
            "r1": None,
            "s1": None,
            "momentum": None,
            # 캔들 패턴 (더미)
            "hammer": False,
            "doji": False,
            "bullish_engulfing": False,
            "bearish_engulfing": False,
            "shooting_star": False,
            "morning_star": False,
            # 지지/저항 (더미)
            "support": None,
            "resistance": None,
            "near_support": False,
            "near_resistance": False,
            # 쌍바닥 (더미)
            "double_bottom": False,
            # 매물대 (더미)
            "poc": None,
            "value_area_high": None,
            "value_area_low": None,
            "above_poc": False,
            "heavy_resistance": False,
            # 외국인/기관 (더미)
            "foreign_net": 0,
            "institution_net": 0,
            "individual_net": 0,
            "foreign_buying": False,
            "program_net": 0,
        }
