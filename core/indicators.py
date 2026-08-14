"""기술 지표 계산 모듈.

pandas DataFrame(OHLCV)을 받아 RSI, MACD, 볼린저밴드, ATR, EMA 등을 계산한다.
`ta` 라이브러리(https://technical-analysis-library-in-python.readthedocs.io) 사용.
"""
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

try:
    import ta
    _TA_AVAILABLE = True
except ImportError:
    _TA_AVAILABLE = False
    logger.warning("[indicators] `ta` 라이브러리 없음 — 수동 계산으로 폴백")


def compute_all(df: pd.DataFrame) -> dict[str, Any]:
    """OHLCV DataFrame → 기술 지표 dict.

    Args:
        df: 컬럼 open, high, low, close, volume (소문자) 필요.

    Returns:
        dict with keys:
            rsi, macd, macd_signal, macd_hist,
            bb_upper, bb_lower, bb_mid,
            atr, ema9, ema21, ema50,
            adx, stoch_k, stoch_d,
            vwap, pivot, r1, s1, momentum
    """
    result: dict[str, Any] = {
        "rsi": None,
        "macd": None,
        "macd_signal": None,
        "macd_hist": None,
        "bb_upper": None,
        "bb_lower": None,
        "bb_mid": None,
        "atr": None,
        "ema9": None,
        "ema21": None,
        "ema50": None,
        # 신규 지표
        "adx": None,
        "stoch_k": None,
        "stoch_d": None,
        "vwap": None,
        "pivot": None,
        "r1": None,
        "s1": None,
        "momentum": None,
    }

    if df is None or df.empty:
        return result

    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        logger.warning(f"[indicators] 필수 컬럼 없음: {missing}")
        return result

    if len(df) < 26:  # MACD 최소 필요
        logger.debug(f"[indicators] 데이터 부족: {len(df)}행")
        return result

    try:
        df = df.copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        if _TA_AVAILABLE:
            # RSI(14)
            rsi_ind = ta.momentum.RSIIndicator(close=close, window=14)
            result["rsi"] = _last(rsi_ind.rsi())

            # MACD(12, 26, 9)
            macd_ind = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
            result["macd"] = _last(macd_ind.macd())
            result["macd_signal"] = _last(macd_ind.macd_signal())
            result["macd_hist"] = _last(macd_ind.macd_diff())

            # Bollinger Bands(20, 2)
            bb_ind = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
            result["bb_upper"] = _last(bb_ind.bollinger_hband())
            result["bb_lower"] = _last(bb_ind.bollinger_lband())
            result["bb_mid"] = _last(bb_ind.bollinger_mavg())

            # ATR(14)
            atr_ind = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14)
            result["atr"] = _last(atr_ind.average_true_range())

            # EMA(9, 21, 50)
            result["ema9"] = _last(ta.trend.EMAIndicator(close=close, window=9).ema_indicator())
            result["ema21"] = _last(ta.trend.EMAIndicator(close=close, window=21).ema_indicator())
            result["ema50"] = _last(ta.trend.EMAIndicator(close=close, window=50).ema_indicator()) if len(df) >= 50 else None

            # ADX(14): 추세 강도
            try:
                adx_ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
                result["adx"] = _last(adx_ind.adx())
            except Exception as e:
                logger.debug(f"[indicators] ADX 계산 오류: {e}")

            # Stochastic(14, 3)
            try:
                stoch_ind = ta.momentum.StochasticOscillator(
                    high=high, low=low, close=close, window=14, smooth_window=3
                )
                result["stoch_k"] = _last(stoch_ind.stoch())
                result["stoch_d"] = _last(stoch_ind.stoch_signal())
            except Exception as e:
                logger.debug(f"[indicators] Stochastic 계산 오류: {e}")

        else:
            # 수동 계산 폴백
            result["rsi"] = _manual_rsi(close, 14)
            result["ema9"] = _manual_ema(close, 9)
            result["ema21"] = _manual_ema(close, 21)
            result["ema50"] = _manual_ema(close, 50) if len(df) >= 50 else None

        # VWAP: (고+저+종)/3 * 거래량 누적합 / 거래량 누적합 — 일봉 기준 근사값
        try:
            typical_price = (high + low + close) / 3
            vol_arr = volume.replace(0, float("nan"))
            cum_tp_vol = (typical_price * vol_arr).cumsum()
            cum_vol = vol_arr.cumsum()
            vwap_series = cum_tp_vol / cum_vol
            result["vwap"] = _last(vwap_series)
        except Exception as e:
            logger.debug(f"[indicators] VWAP 계산 오류: {e}")

        # Pivot Point: 전일 기준
        try:
            if len(df) >= 2:
                prev = df.iloc[-2]
                pp = (prev["high"] + prev["low"] + prev["close"]) / 3
                r1 = 2 * pp - prev["low"]
                s1 = 2 * pp - prev["high"]
                result["pivot"] = round(float(pp), 4)
                result["r1"] = round(float(r1), 4)
                result["s1"] = round(float(s1), 4)
        except Exception as e:
            logger.debug(f"[indicators] Pivot 계산 오류: {e}")

        # Momentum(10): 현재가 - 10봉 전 가격
        try:
            if len(df) >= 11:
                momentum = float(close.iloc[-1]) - float(close.iloc[-11])
                result["momentum"] = round(momentum, 4)
        except Exception as e:
            logger.debug(f"[indicators] Momentum 계산 오류: {e}")

    except Exception as e:
        logger.warning(f"[indicators] 지표 계산 오류: {e}")

    return result


def detect_candle_patterns(df: pd.DataFrame) -> dict[str, bool]:
    """최근 3봉으로 캔들 패턴 감지.

    Args:
        df: OHLCV DataFrame (open, high, low, close 필요)

    Returns:
        dict with keys:
            hammer, doji, bullish_engulfing, bearish_engulfing,
            shooting_star, morning_star
    """
    result: dict[str, bool] = {
        "hammer": False,
        "doji": False,
        "bullish_engulfing": False,
        "bearish_engulfing": False,
        "shooting_star": False,
        "morning_star": False,
    }

    if df is None or len(df) < 3:
        return result

    try:
        df = df.copy()
        required = {"open", "high", "low", "close"}
        if not required.issubset(set(df.columns)):
            return result

        c0 = df.iloc[-1]  # 현재 (최신)
        c1 = df.iloc[-2]  # 이전
        c2 = df.iloc[-3]  # 그 이전

        def body(c: pd.Series) -> float:
            return abs(float(c["close"]) - float(c["open"]))

        def upper_wick(c: pd.Series) -> float:
            return float(c["high"]) - max(float(c["close"]), float(c["open"]))

        def lower_wick(c: pd.Series) -> float:
            return min(float(c["close"]), float(c["open"])) - float(c["low"])

        def total_range(c: pd.Series) -> float:
            return float(c["high"]) - float(c["low"])

        def is_bearish(c: pd.Series) -> bool:
            return float(c["close"]) < float(c["open"])

        def is_bullish(c: pd.Series) -> bool:
            return float(c["close"]) > float(c["open"])

        # 망치형 (Hammer): 아래꼬리 >= 몸통 2배, 위꼬리 작음, 몸통 존재
        try:
            b0 = body(c0)
            lw0 = lower_wick(c0)
            uw0 = upper_wick(c0)
            tr0 = total_range(c0)
            if tr0 > 0 and b0 > 0 and lw0 >= b0 * 2 and uw0 <= b0 * 0.3:
                result["hammer"] = True
        except Exception:
            pass

        # 도지 (Doji): 몸통이 전체 범위의 10% 이하
        try:
            b0 = body(c0)
            tr0 = total_range(c0)
            if tr0 > 0 and b0 / tr0 <= 0.1:
                result["doji"] = True
        except Exception:
            pass

        # 불리시 장악형 (Bullish Engulfing): 전봉 음봉, 현봉 양봉으로 완전 감쌈
        try:
            if (is_bearish(c1) and is_bullish(c0)
                    and float(c0["open"]) < float(c1["close"])
                    and float(c0["close"]) > float(c1["open"])):
                result["bullish_engulfing"] = True
        except Exception:
            pass

        # 베어리시 장악형 (Bearish Engulfing): 전봉 양봉, 현봉 음봉으로 완전 감쌈
        try:
            if (is_bullish(c1) and is_bearish(c0)
                    and float(c0["open"]) > float(c1["close"])
                    and float(c0["close"]) < float(c1["open"])):
                result["bearish_engulfing"] = True
        except Exception:
            pass

        # 슈팅스타 (Shooting Star): 위꼬리 >= 몸통 2배, 아래꼬리 작음
        try:
            b0 = body(c0)
            uw0 = upper_wick(c0)
            lw0 = lower_wick(c0)
            if b0 > 0 and uw0 >= b0 * 2 and lw0 <= b0 * 0.3:
                result["shooting_star"] = True
        except Exception:
            pass

        # 모닝스타 (Morning Star): 음봉 - 도지/작은몸통 - 양봉 (3봉 패턴)
        try:
            b2 = body(c2)
            b1 = body(c1)
            tr1 = total_range(c1)
            b0 = body(c0)
            if (is_bearish(c2)
                    and (tr1 > 0 and b1 / tr1 <= 0.3)  # 중간봉: 도지 또는 작은 몸통
                    and is_bullish(c0)
                    and float(c0["close"]) > (float(c2["open"]) + float(c2["close"])) / 2):
                result["morning_star"] = True
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"[indicators] 캔들 패턴 감지 오류: {e}")

    return result


def detect_support_resistance(df: pd.DataFrame, window: int = 20) -> dict[str, Any]:
    """지지/저항 레벨 자동 감지.

    Args:
        df: OHLCV DataFrame
        window: 확인할 최근 봉 수

    Returns:
        dict with keys:
            support (float), resistance (float),
            near_support (bool), near_resistance (bool)
    """
    result: dict[str, Any] = {
        "support": None,
        "resistance": None,
        "near_support": False,
        "near_resistance": False,
    }

    if df is None or len(df) < window:
        return result

    try:
        df = df.copy()
        recent = df.iloc[-window:]
        highs = recent["high"].values
        lows = recent["low"].values
        closes = recent["close"].values
        current_price = float(closes[-1])

        # 저항선: 국소 고점들의 평균 (전후 봉보다 높은 점)
        resistance_points = []
        support_points = []
        for i in range(1, len(highs) - 1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                resistance_points.append(highs[i])
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                support_points.append(lows[i])

        if resistance_points:
            resistance = float(np.mean(resistance_points))
            result["resistance"] = round(resistance, 4)
            if current_price > 0:
                result["near_resistance"] = abs(resistance - current_price) / current_price <= 0.02

        if support_points:
            support = float(np.mean(support_points))
            result["support"] = round(support, 4)
            if current_price > 0:
                result["near_support"] = abs(support - current_price) / current_price <= 0.02

    except Exception as e:
        logger.debug(f"[indicators] 지지/저항 감지 오류: {e}")

    return result


def detect_double_bottom(df: pd.DataFrame) -> bool:
    """쌍바닥 패턴 감지.

    최근 60봉에서 비슷한 저점 2개(5% 이내 차이)를 찾고,
    두 저점 사이의 고점이 두 저점보다 높은지 확인.

    Args:
        df: OHLCV DataFrame

    Returns:
        bool: 쌍바닥 패턴 존재 여부
    """
    try:
        if df is None or len(df) < 20:
            return False

        n = min(60, len(df))
        recent = df.iloc[-n:].copy()
        lows = recent["low"].values
        highs = recent["high"].values

        # 국소 저점 인덱스 탐색
        local_min_idx = []
        for i in range(1, len(lows) - 1):
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                local_min_idx.append(i)

        if len(local_min_idx) < 2:
            return False

        # 가장 최근 두 저점 비교
        for i in range(len(local_min_idx) - 1):
            idx1 = local_min_idx[i]
            idx2 = local_min_idx[i + 1]
            v1 = lows[idx1]
            v2 = lows[idx2]

            # 두 저점 5% 이내 차이
            if v1 > 0 and abs(v1 - v2) / v1 <= 0.05:
                # 두 저점 사이 고점이 두 저점보다 높아야 함
                between_high = float(np.max(highs[idx1:idx2 + 1]))
                min_of_bottoms = min(v1, v2)
                if between_high > min_of_bottoms * 1.01:
                    return True

        return False

    except Exception as e:
        logger.debug(f"[indicators] 쌍바닥 감지 오류: {e}")
        return False


def calc_volume_profile(df: pd.DataFrame, bins: int = 20) -> dict[str, Any]:
    """매물대 계산: 가격 구간별 거래량 집계.

    Args:
        df: OHLCV DataFrame
        bins: 가격 구간 수

    Returns:
        dict with keys:
            poc (float): Point of Control — 거래량 최다 가격
            value_area_high (float): 거래량 70% 포함 상단
            value_area_low (float): 거래량 70% 포함 하단
            above_poc (bool): 현재가가 POC 위
            heavy_resistance (bool): 현재가 위 5% 이내에 두꺼운 매물대
    """
    result: dict[str, Any] = {
        "poc": None,
        "value_area_high": None,
        "value_area_low": None,
        "above_poc": False,
        "heavy_resistance": False,
    }

    try:
        if df is None or len(df) < 5:
            return result

        df = df.copy()
        close = df["close"].values
        volume = df["volume"].values
        high = df["high"].values
        low = df["low"].values

        price_min = float(np.min(low))
        price_max = float(np.max(high))
        if price_max <= price_min:
            return result

        bin_edges = np.linspace(price_min, price_max, bins + 1)
        bin_volumes = np.zeros(bins)

        for i in range(len(close)):
            # 각 봉의 거래량을 고-저 범위의 해당 빈에 분배
            bar_low = float(low[i])
            bar_high = float(high[i])
            bar_vol = float(volume[i])
            if bar_high <= bar_low:
                continue
            for b in range(bins):
                bin_lo = bin_edges[b]
                bin_hi = bin_edges[b + 1]
                overlap = max(0.0, min(bar_high, bin_hi) - max(bar_low, bin_lo))
                ratio = overlap / (bar_high - bar_low)
                bin_volumes[b] += bar_vol * ratio

        # POC: 거래량 최다 구간의 중간 가격
        poc_bin = int(np.argmax(bin_volumes))
        poc = float((bin_edges[poc_bin] + bin_edges[poc_bin + 1]) / 2)
        result["poc"] = round(poc, 4)

        # Value Area: 거래량 70% 포함 구간 (POC에서 양쪽 확장)
        total_vol = float(np.sum(bin_volumes))
        target_vol = total_vol * 0.70
        va_bins = [poc_bin]
        accumulated = bin_volumes[poc_bin]
        lo_ptr, hi_ptr = poc_bin - 1, poc_bin + 1

        while accumulated < target_vol:
            lo_vol = bin_volumes[lo_ptr] if lo_ptr >= 0 else 0.0
            hi_vol = bin_volumes[hi_ptr] if hi_ptr < bins else 0.0
            if lo_vol == 0 and hi_vol == 0:
                break
            if lo_vol >= hi_vol and lo_ptr >= 0:
                va_bins.append(lo_ptr)
                accumulated += lo_vol
                lo_ptr -= 1
            else:
                va_bins.append(hi_ptr)
                accumulated += hi_vol
                hi_ptr += 1

        va_min_bin = min(va_bins)
        va_max_bin = max(va_bins)
        result["value_area_low"] = round(float(bin_edges[va_min_bin]), 4)
        result["value_area_high"] = round(float(bin_edges[va_max_bin + 1]), 4)

        current_price = float(close[-1])
        if current_price > 0:
            result["above_poc"] = current_price > poc

            # 현재가 위 5% 이내에 두꺼운 매물대가 있는지 확인
            upper_limit = current_price * 1.05
            resistance_vol = 0.0
            for b in range(bins):
                mid = float((bin_edges[b] + bin_edges[b + 1]) / 2)
                if current_price < mid <= upper_limit:
                    resistance_vol += bin_volumes[b]

            # 전체 거래량의 15% 이상이면 두꺼운 매물대
            if total_vol > 0 and resistance_vol / total_vol >= 0.15:
                result["heavy_resistance"] = True

    except Exception as e:
        logger.debug(f"[indicators] 매물대 계산 오류: {e}")

    return result


def is_pullback(df: pd.DataFrame, lookback: int = 5) -> bool:
    """눌림목(pullback) 감지 — bool 래퍼."""
    result = pullback_score(df, lookback)
    return result["detected"]


def pullback_score(df: pd.DataFrame, lookback: int = 10) -> dict:
    """올랜도킴 눌림목 품질 점수 (0~100) + 상세 분석.

    조건별 가중치:
    - 되돌림 깊이 3~8%: +30 (올랜도킴 핵심)
    - MA20 위 (상승 추세): +20
    - RSI 40~65 (과열/침체 아님): +20
    - MACD > 0 (모멘텀 양): +15
    - 반등일 거래량 급증: +15

    Returns:
        {detected, score, depth_pct, reasons}
    """
    result = {"detected": False, "score": 0, "depth_pct": 0.0, "reasons": []}
    try:
        if df is None or len(df) < lookback + 5:
            return result

        closes = df["close"].tolist()
        volumes = df["volume"].tolist()

        recent_closes = closes[-(lookback + 2):]
        peak = max(recent_closes[:-1])
        trough = min(recent_closes[:-1])
        current = recent_closes[-1]
        prev = recent_closes[-2]

        if peak <= 0:
            return result

        depth_pct = (peak - trough) / peak * 100
        rebound = current > prev
        result["depth_pct"] = round(depth_pct, 2)

        if not (3.0 <= depth_pct <= 10.0 and rebound):
            return result

        score = 0
        reasons = []

        # 되돌림 깊이 점수 (3~8% 최적)
        if 3.0 <= depth_pct <= 8.0:
            score += 30
            reasons.append(f"눌림목 {depth_pct:.1f}% (최적)")
        else:
            score += 15
            reasons.append(f"눌림목 {depth_pct:.1f}% (양호)")

        # MA20 위
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20
            if current > ma20:
                score += 20
                reasons.append("MA20 위")

        # RSI 40~65
        try:
            close_s = pd.Series(closes)
            delta = close_s.diff()
            gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
            loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
            rsi = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
            rsi_val = float(rsi.iloc[-1])
            if 40 <= rsi_val <= 65:
                score += 20
                reasons.append(f"RSI {rsi_val:.0f}")
        except Exception:
            pass

        # MACD > 0
        try:
            close_s = pd.Series(closes)
            ema12 = close_s.ewm(span=12, adjust=False).mean()
            ema26 = close_s.ewm(span=26, adjust=False).mean()
            macd = float((ema12 - ema26).iloc[-1])
            if macd > 0:
                score += 15
                reasons.append("MACD 양전환")
        except Exception:
            pass

        # 반등일 거래량 급증
        if len(volumes) >= 20:
            avg_vol = sum(volumes[-20:-1]) / 19
            if avg_vol > 0 and volumes[-1] >= avg_vol * 1.3:
                score += 15
                reasons.append(f"반등 거래량 {volumes[-1]/avg_vol:.1f}배")

        result["detected"] = True
        result["score"] = min(score, 100)
        result["reasons"] = reasons
        return result
    except Exception as e:
        logger.debug(f"[indicators] pullback_score 오류: {e}")
        return result


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _last(series: pd.Series) -> float | None:
    """Series 마지막 유효값."""
    try:
        val = series.dropna().iloc[-1]
        return round(float(val), 4)
    except (IndexError, ValueError, TypeError):
        return None


def _manual_rsi(close: pd.Series, period: int = 14) -> float | None:
    """ta 없을 때 수동 RSI."""
    try:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return _last(rsi)
    except Exception:
        return None


def _manual_ema(close: pd.Series, period: int) -> float | None:
    """ta 없을 때 수동 EMA."""
    try:
        ema = close.ewm(span=period, adjust=False).mean()
        return _last(ema)
    except Exception:
        return None
