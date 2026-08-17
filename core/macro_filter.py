"""FRED API (연방준비은행) 거시경제 데이터 모듈.

연방기금금리, CPI 트렌드, 금리 방향을 분석해 매크로 리짐을 반환한다.
API key: FRED_API_KEY 환경변수 (없으면 graceful fallback)
완전 무료, base: https://api.stlouisfed.org/fred
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests
from loguru import logger

_BASE_URL = "https://api.stlouisfed.org/fred"
_REQUEST_TIMEOUT = 8

# ── 캐시 ────────────────────────────────────────────────────────────────────
_fed_rate_cache: dict[str, Any] = {}
_fed_rate_ts: float = 0.0

_rate_dir_cache: str = ""
_rate_dir_ts: float = 0.0

_cpi_cache: float = 0.0
_cpi_ts: float = 0.0

_macro_regime_cache: dict[str, Any] = {}
_macro_regime_ts: float = 0.0

_MACRO_TTL: float = 21600.0   # 6시간 (거시경제는 자주 안 바뀜)

# ── fallback ─────────────────────────────────────────────────────────────────
_FALLBACK_REGIME: dict[str, Any] = {
    "rate_dir": "stable",
    "cpi": 3.0,
    "bullish": True,
    "fed_rate": 5.25,
}


def _api_key() -> str | None:
    return os.getenv("FRED_API_KEY") or None


def _fred_get(series_id: str, limit: int = 12) -> list[dict[str, Any]]:
    """FRED 시계열 데이터 조회.

    Returns:
        [{"date": "2024-01-01", "value": "5.33"}, ...]  최신순 정렬
    Raises:
        ValueError: API key 없음
        Exception: 네트워크 / API 오류
    """
    key = _api_key()
    if not key:
        raise ValueError("FRED_API_KEY 없음")

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    resp = requests.get(
        f"{_BASE_URL}/series/observations",
        params=params,
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    observations = data.get("observations", [])
    # "." 값(결측) 제거
    return [o for o in observations if o.get("value") not in (".", "", None)]


# ── 연방기금금리 ───────────────────────────────────────────────────────────

def get_fed_rate() -> float:
    """현재 연방기금금리(FEDFUNDS 시리즈) 반환.

    Returns:
        float: 연방기금금리 (예: 5.33). 실패 시 5.25
    """
    global _fed_rate_cache, _fed_rate_ts

    now = time.monotonic()
    if _fed_rate_cache and (now - _fed_rate_ts) < _MACRO_TTL:
        return float(_fed_rate_cache.get("rate", 5.25))

    try:
        obs = _fred_get("FEDFUNDS", limit=3)
        if not obs:
            return 5.25
        rate = float(obs[0]["value"])
        _fed_rate_cache = {"rate": rate}
        _fed_rate_ts = now
        logger.debug(f"[MacroFilter] 연방기금금리={rate:.2f}%")
        return rate
    except ValueError:
        return 5.25
    except Exception as e:
        logger.debug(f"[MacroFilter] 연방기금금리 조회 실패: {e}")
        return 5.25


# ── 금리 방향 ──────────────────────────────────────────────────────────────

def get_rate_direction() -> str:
    """최근 3개월 연방기금금리 방향 판단.

    Returns:
        "cutting" | "hiking" | "stable"
    """
    global _rate_dir_cache, _rate_dir_ts

    now = time.monotonic()
    if _rate_dir_cache and (now - _rate_dir_ts) < _MACRO_TTL:
        return _rate_dir_cache

    try:
        obs = _fred_get("FEDFUNDS", limit=4)  # 최신 4개월 데이터
        if len(obs) < 2:
            return "stable"

        # 최신 값 (obs[0]) vs 3개월 전 (obs[3] 또는 가용 마지막)
        latest = float(obs[0]["value"])
        oldest = float(obs[-1]["value"])
        diff = latest - oldest

        if diff <= -0.125:
            direction = "cutting"
        elif diff >= 0.125:
            direction = "hiking"
        else:
            direction = "stable"

        _rate_dir_cache = direction
        _rate_dir_ts = now
        logger.debug(f"[MacroFilter] 금리 방향={direction} (최신{latest:.2f}% / 전{oldest:.2f}%)")
        return direction

    except ValueError:
        return "stable"
    except Exception as e:
        logger.debug(f"[MacroFilter] 금리 방향 조회 실패: {e}")
        return "stable"


# ── CPI 트렌드 ────────────────────────────────────────────────────────────

def get_cpi_trend() -> float:
    """CPI 전월비 변화율 반환 (CPIAUCSL 시리즈).

    Returns:
        float: 전월 대비 변화율 % (예: 0.3 = +0.3%). 실패 시 0.3
    """
    global _cpi_cache, _cpi_ts

    now = time.monotonic()
    if _cpi_ts and (now - _cpi_ts) < _MACRO_TTL:
        return _cpi_cache

    try:
        obs = _fred_get("CPIAUCSL", limit=3)
        if len(obs) < 2:
            return 0.3

        latest = float(obs[0]["value"])
        prev   = float(obs[1]["value"])
        mom_change = round((latest - prev) / prev * 100, 4) if prev > 0 else 0.3

        _cpi_cache = mom_change
        _cpi_ts = now
        logger.debug(f"[MacroFilter] CPI 전월비={mom_change:+.3f}%")
        return mom_change

    except ValueError:
        return 0.3
    except Exception as e:
        logger.debug(f"[MacroFilter] CPI 조회 실패: {e}")
        return 0.3


# ── 거시경제 리짐 (통합) ─────────────────────────────────────────────────

def get_macro_regime() -> dict[str, Any]:
    """거시경제 종합 리짐 반환 (6시간 캐시).

    Returns:
        {
            "rate_dir": "cutting" | "hiking" | "stable",
            "cpi": float,           # CPI 전월비 %
            "fed_rate": float,      # 연방기금금리 %
            "bullish": bool,        # True = 거시경제 호의적
        }
        실패 시: {"rate_dir": "stable", "cpi": 3.0, "bullish": True, "fed_rate": 5.25}
    """
    global _macro_regime_cache, _macro_regime_ts

    now = time.monotonic()
    if _macro_regime_cache and (now - _macro_regime_ts) < _MACRO_TTL:
        return _macro_regime_cache

    try:
        rate_dir = get_rate_direction()
        cpi      = get_cpi_trend()
        fed_rate = get_fed_rate()

        # 금리 인하 + CPI 안정(전월비 < 0.4%) = bullish
        # 금리 인상 또는 CPI 급등 = bearish
        if rate_dir == "cutting" and cpi < 0.4:
            bullish = True
        elif rate_dir == "hiking":
            bullish = False
        else:
            bullish = True  # stable 구간은 중립적 → 매수 허용

        result: dict[str, Any] = {
            "rate_dir": rate_dir,
            "cpi": round(cpi, 3),
            "fed_rate": fed_rate,
            "bullish": bullish,
        }
        _macro_regime_cache = result
        _macro_regime_ts = now
        logger.debug(
            f"[MacroFilter] 거시경제 리짐: 금리방향={rate_dir}, "
            f"CPI={cpi:+.3f}%, 연방기금={fed_rate:.2f}%, 강세={bullish}"
        )
        return result

    except Exception as e:
        logger.debug(f"[MacroFilter] 거시경제 리짐 조회 실패: {e}")
        return dict(_FALLBACK_REGIME)
