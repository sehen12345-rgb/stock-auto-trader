"""시장 상황 판단 모듈.

공포탐욕지수, 코스피/나스닥 변동률로 시장 환경을 평가한다.
모든 외부 API 호출은 try/except로 감싸고 실패 시 기본값을 반환한다.
"""
from __future__ import annotations

import time
from typing import Any

import requests
from loguru import logger

# ── 캐시 ────────────────────────────────────────────────────────────────────
_fear_greed_cache: dict[str, Any] = {}
_fear_greed_ts: float = 0.0
_FEAR_GREED_TTL: float = 300.0  # 5분

_kospi_cache: float = 0.0
_kospi_ts: float = 0.0
_KOSPI_TTL: float = 60.0  # 1분

_nasdaq_cache: float = 0.0
_nasdaq_ts: float = 0.0
_NASDAQ_TTL: float = 60.0  # 1분

_REQUEST_TIMEOUT: int = 5


def get_fear_greed_index() -> dict[str, Any]:
    """CNN Fear & Greed 지수 조회 (무료 API).

    Returns:
        {"value": int, "rating": str}  # rating: Fear / Greed / Neutral 등
        실패 시: {"value": 50, "rating": "Neutral"}
    """
    global _fear_greed_cache, _fear_greed_ts

    now = time.monotonic()
    if _fear_greed_cache and (now - _fear_greed_ts) < _FEAR_GREED_TTL:
        return _fear_greed_cache

    default = {"value": 50, "rating": "Neutral"}
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.cnn.com/markets/fear-and-greed",
        }
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        value = int(round(float(fg.get("score", 50))))
        rating = str(fg.get("rating", "Neutral"))
        result = {"value": value, "rating": rating}
        _fear_greed_cache = result
        _fear_greed_ts = now
        logger.debug(f"[MarketFilter] Fear&Greed={value} ({rating})")
        return result
    except Exception as e:
        logger.debug(f"[MarketFilter] Fear&Greed 조회 실패: {e}")
        return default


def get_kospi_change() -> float:
    """코스피 지수 변동률(%) 조회.

    KIS API 대신 Yahoo Finance를 통해 ^KS11(코스피) 변동률을 가져온다.

    Returns:
        float: 변동률 (예: -1.2 = -1.2%). 실패 시 0.0
    """
    global _kospi_cache, _kospi_ts

    now = time.monotonic()
    if _kospi_ts and (now - _kospi_ts) < _KOSPI_TTL:
        return _kospi_cache

    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            "%5EKS11?interval=1d&range=2d"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        closes = (
            data.get("chart", {})
            .get("result", [{}])[0]
            .get("indicators", {})
            .get("quote", [{}])[0]
            .get("close", [])
        )
        # None 제거
        closes = [c for c in closes if c is not None]
        if len(closes) >= 2:
            change = (closes[-1] - closes[-2]) / closes[-2] * 100
            result = round(float(change), 2)
        else:
            result = 0.0
        _kospi_cache = result
        _kospi_ts = now
        logger.debug(f"[MarketFilter] 코스피 변동률={result:.2f}%")
        return result
    except Exception as e:
        logger.debug(f"[MarketFilter] 코스피 변동률 조회 실패: {e}")
        return 0.0


def get_nasdaq_change() -> float:
    """나스닥 지수 변동률(%) 조회.

    Yahoo Finance API로 ^IXIC(나스닥 종합) 변동률을 가져온다.

    Returns:
        float: 변동률 (예: 0.8 = +0.8%). 실패 시 0.0
    """
    global _nasdaq_cache, _nasdaq_ts

    now = time.monotonic()
    if _nasdaq_ts and (now - _nasdaq_ts) < _NASDAQ_TTL:
        return _nasdaq_cache

    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            "%5EIXIC?interval=1d&range=2d"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        closes = (
            data.get("chart", {})
            .get("result", [{}])[0]
            .get("indicators", {})
            .get("quote", [{}])[0]
            .get("close", [])
        )
        closes = [c for c in closes if c is not None]
        if len(closes) >= 2:
            change = (closes[-1] - closes[-2]) / closes[-2] * 100
            result = round(float(change), 2)
        else:
            result = 0.0
        _nasdaq_cache = result
        _nasdaq_ts = now
        logger.debug(f"[MarketFilter] 나스닥 변동률={result:.2f}%")
        return result
    except Exception as e:
        logger.debug(f"[MarketFilter] 나스닥 변동률 조회 실패: {e}")
        return 0.0


def is_market_bullish(kospi_change: float, fear_greed: int) -> bool:
    """매수 적합 시장 조건 판단.

    Args:
        kospi_change: 코스피 변동률 (%)
        fear_greed: Fear & Greed 지수 (0~100)

    Returns:
        bool: True면 매수 적합 (공포 극단이 아니고 시장 급락 아님)
    """
    # 코스피 -1.5% 이상 (너무 많이 빠지지 않음)
    cond_kospi = kospi_change >= -1.5
    # Fear & Greed 25 이상 (극단적 공포 아님)
    cond_fg = fear_greed >= 25
    return cond_kospi and cond_fg
