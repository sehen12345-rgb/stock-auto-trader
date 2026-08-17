"""
섹터 ETF 모멘텀 필터.
종목별로 해당 섹터 ETF 추이를 체크해 역풍 섹터 진입 차단.
"""
from __future__ import annotations
import time
from typing import Any
from loguru import logger

# 섹터 ETF 매핑
SECTOR_MAP: dict[str, str] = {
    # 반도체
    "NVDA": "SOXX", "AMD": "SOXX", "MU": "SOXX",
    "AVGO": "SOXX", "MRVL": "SOXX", "TSM": "SOXX",
    # 빅테크
    "MSFT": "QQQ", "AMZN": "QQQ", "GOOG": "QQQ",
    "TSLA": "QQQ", "META": "QQQ",
    # 데이터센터/인프라
    "VRT": "XLK", "DELL": "XLK", "DDOG": "XLK",
    # 방산/에너지
    "GE": "XLI", "BE": "XLU",
    # 기본값
    "_default_overseas": "QQQ",
    "_default_domestic": None,
}

_etf_cache: dict[str, tuple[float, float]] = {}  # {etf: (change_pct, ts)}
_ETF_TTL: float = 300.0  # 5분


def get_etf_change(etf: str) -> float:
    """ETF 당일 변동률 조회 (yfinance, 5분 캐시)."""
    now = time.monotonic()
    cached = _etf_cache.get(etf)
    if cached and (now - cached[1]) < _ETF_TTL:
        return cached[0]

    try:
        import yfinance as yf
        hist = yf.Ticker(etf).history(period="2d")
        if hist is None or len(hist) < 2:
            return 0.0
        closes = hist["Close"].dropna().tolist()
        if len(closes) < 2:
            return 0.0
        change = (closes[-1] - closes[-2]) / closes[-2] * 100
        change = round(float(change), 2)
        _etf_cache[etf] = (change, now)
        logger.debug(f"[SectorFilter] {etf} 변동률={change:+.2f}%")
        return change
    except Exception as e:
        logger.debug(f"[SectorFilter] {etf} 조회 실패: {e}")
        return 0.0


def is_sector_favorable(ticker: str, threshold: float = -1.5) -> tuple[bool, str]:
    """해당 종목의 섹터 ETF가 매수 적합한지 판단.

    Args:
        ticker: 종목 코드
        threshold: 섹터 변동률 하한 (기본 -1.5%)
    Returns:
        (적합여부, 섹터ETF명)
    """
    # 국내주식은 섹터 필터 미적용
    if ticker.isdigit():
        return True, "N/A"

    etf = SECTOR_MAP.get(ticker, SECTOR_MAP["_default_overseas"])
    if not etf:
        return True, "N/A"

    change = get_etf_change(etf)
    favorable = change >= threshold
    return favorable, f"{etf}({change:+.2f}%)"
