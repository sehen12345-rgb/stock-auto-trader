"""기술 지표 계산 모듈.

pandas DataFrame(OHLCV)을 받아 RSI, MACD, 볼린저밴드, ATR, EMA 등을 계산한다.
`ta` 라이브러리(https://technical-analysis-library-in-python.readthedocs.io) 사용.
"""
from typing import Any

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
            atr, ema9, ema21, ema50
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

        else:
            # 수동 계산 폴백
            result["rsi"] = _manual_rsi(close, 14)
            result["ema9"] = _manual_ema(close, 9)
            result["ema21"] = _manual_ema(close, 21)
            result["ema50"] = _manual_ema(close, 50) if len(df) >= 50 else None

    except Exception as e:
        logger.warning(f"[indicators] 지표 계산 오류: {e}")

    return result


def is_pullback(df: pd.DataFrame, lookback: int = 5) -> bool:
    """눌림목(pullback) 감지.

    최근 lookback 봉 중 고점 대비 3~10% 되돌린 후 반등이 시작됐으면 True.

    Args:
        df: OHLCV DataFrame
        lookback: 확인할 최근 봉 수

    Returns:
        bool
    """
    try:
        if df is None or len(df) < lookback + 2:
            return False

        df = df.copy()
        recent = df.iloc[-(lookback + 2):]
        closes = recent["close"].tolist()

        # 구간 고점
        peak = max(closes[:-1])
        current = closes[-1]
        prev = closes[-2]

        if peak <= 0:
            return False

        drawdown_pct = (peak - min(closes[:-1])) / peak * 100
        rebound = current > prev  # 직전 봉 대비 반등

        return 3.0 <= drawdown_pct <= 10.0 and rebound
    except Exception as e:
        logger.debug(f"[indicators] is_pullback 오류: {e}")
        return False


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
