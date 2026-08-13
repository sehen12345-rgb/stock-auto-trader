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
)


class DataFetcher:
    def __init__(self) -> None:
        self._broker = KISBroker()
        self._broker.connect()

    async def fetch(self, symbol: str) -> dict[str, Any]:
        try:
            return self._fetch_sync(symbol)
        except Exception as e:
            logger.warning(f"[Fetcher] {symbol} 조회 실패 (더미 반환): {e}")
            return self._dummy(symbol)

    def _fetch_sync(self, symbol: str) -> dict[str, Any]:
        is_overseas = self._broker._is_overseas(symbol)
        if is_overseas:
            current_price = self._broker.get_overseas_price(symbol)
            df = self._broker.get_overseas_ohlcv(symbol, period=252)
        else:
            current_price = self._broker.get_current_price(symbol)
            df = self._broker.get_ohlcv(symbol, period=252)

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
        try:
            if not df.empty:
                pullback_detected = is_pullback(df)
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
        try:
            balance = self._broker.get_balance()
            positions = self._broker.get_positions()
            seed = 10_000_000
            total_value = balance.total_equity if balance.total_equity > 0 else seed
            cash = balance.cash
            pnl_pct = round((total_value - seed) / seed * 100, 2) if seed > 0 else 0.0
            return {
                "total_value": total_value,
                "cash": cash,
                "return_pct": pnl_pct,
                "seed": seed,
            }
        except Exception as e:
            logger.warning(f"[Fetcher] 포트폴리오 조회 실패: {e}")
            return {"total_value": 0, "cash": 0, "return_pct": 0.0, "seed": 10_000_000}

    async def fetch_kis_positions(self) -> list[dict[str, Any]]:
        try:
            positions = self._broker.get_positions()
            result = []
            for p in positions:
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
            return result
        except Exception as e:
            logger.warning(f"[Fetcher] KIS 포지션 조회 실패: {e}")
            return []

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
