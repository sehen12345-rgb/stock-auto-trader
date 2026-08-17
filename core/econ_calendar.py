"""경제 이벤트 캘린더 모듈.

Finnhub `/calendar/economic` API를 사용해 FOMC, CPI, PCE, 실업률 등
고영향 경제 이벤트를 수집·캐시한다. API 키가 없으면 빈 리스트를 반환한다.
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Any

import httpx
from loguru import logger

# ── 상수 ──────────────────────────────────────────────────────────────────────
_BASE_URL = "https://finnhub.io/api/v1"
_REQUEST_TIMEOUT = 8
_EVENTS_TTL: float = 3600.0   # 1시간 캐시

# ── 캐시 ──────────────────────────────────────────────────────────────────────
_events_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
# key: "YYYY-MM-DD_YYYY-MM-DD" → (timestamp, events)

# Finnhub impact 매핑 (API 반환값 → 표준화)
_IMPACT_MAP: dict[str, str] = {
    "high": "high",
    "medium": "medium",
    "med": "medium",
    "low": "low",
    "1": "high",
    "2": "medium",
    "3": "low",
}


def _api_key() -> str | None:
    """FINNHUB_API_KEY 환경변수 반환. 없으면 None."""
    return os.getenv("FINNHUB_API_KEY") or None


def _normalize_impact(raw: Any) -> str:
    """Finnhub impact 값을 'high'/'medium'/'low' 로 정규화한다."""
    return _IMPACT_MAP.get(str(raw).lower(), "low")


def _fetch_events_from_api(from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Finnhub 경제 캘린더 API 호출 (동기 내부 함수).

    Returns:
        raw event 딕셔너리 리스트. 실패 시 빈 리스트.
    """
    key = _api_key()
    if not key:
        logger.debug("[EconCalendar] FINNHUB_API_KEY 없음 — 스킵")
        return []

    try:
        resp = httpx.get(
            f"{_BASE_URL}/calendar/economic",
            params={"from": from_date, "to": to_date, "token": key},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("economicCalendar", []) or []
    except httpx.HTTPStatusError as e:
        logger.debug(f"[EconCalendar] HTTP 오류: {e.response.status_code}")
        return []
    except Exception as e:
        logger.debug(f"[EconCalendar] API 호출 실패: {e}")
        return []


def _get_events(from_date: str, to_date: str) -> list[dict[str, Any]]:
    """캐시를 확인하고 없으면 API를 호출해 이벤트 목록을 반환한다.

    모든 impact 레벨 포함 (필터링은 호출자가 담당).
    """
    cache_key = f"{from_date}_{to_date}"
    now = time.monotonic()
    cached = _events_cache.get(cache_key)
    if cached and (now - cached[0]) < _EVENTS_TTL:
        logger.debug(f"[EconCalendar] 캐시 히트: {cache_key}")
        return cached[1]

    raw = _fetch_events_from_api(from_date, to_date)

    events: list[dict[str, Any]] = []
    for item in raw:
        try:
            impact = _normalize_impact(item.get("impact", "low"))
            events.append({
                "event":    str(item.get("event", "")),
                "date":     str(item.get("time", item.get("date", ""))[:10]),
                "impact":   impact,
                "country":  str(item.get("country", "")),
                "actual":   item.get("actual"),
                "estimate": item.get("estimate"),
                "previous": item.get("prev"),
            })
        except Exception as e:
            logger.debug(f"[EconCalendar] 이벤트 파싱 오류: {e}")

    _events_cache[cache_key] = (now, events)
    logger.debug(f"[EconCalendar] {len(events)}건 수집 ({from_date} ~ {to_date})")
    return events


# ── 공개 함수 ─────────────────────────────────────────────────────────────────

def get_upcoming_events(days_ahead: int = 14) -> list[dict[str, Any]]:
    """향후 `days_ahead`일 이내의 고영향(high) 경제 이벤트 목록을 반환한다.

    Args:
        days_ahead: 조회할 미래 일수 (기본 14일).

    Returns:
        [
            {
                "event":    str,    # 이벤트명 (예: "FOMC Rate Decision")
                "date":     str,    # 날짜 "YYYY-MM-DD"
                "impact":   str,    # "high" | "medium" | "low"
                "country":  str,    # 국가 코드 (예: "US")
                "actual":   float | None,
                "estimate": float | None,
                "previous": float | None,
            },
            ...
        ]
        API 키 없음 또는 실패 시 빈 리스트.
    """
    try:
        today = date.today()
        from_date = today.isoformat()
        to_date = (today + timedelta(days=days_ahead)).isoformat()

        all_events = _get_events(from_date, to_date)
        high_only = [e for e in all_events if e["impact"] == "high"]
        high_only.sort(key=lambda e: e["date"])

        logger.debug(f"[EconCalendar] 향후 {days_ahead}일 고영향 이벤트 {len(high_only)}건")
        return high_only
    except Exception as e:
        logger.warning(f"[EconCalendar] get_upcoming_events 실패: {e}")
        return []


def get_high_impact_today() -> list[dict[str, Any]]:
    """오늘 고영향 경제 이벤트 목록을 반환한다.

    Returns:
        오늘 날짜의 high impact 이벤트 리스트. 없으면 빈 리스트.
    """
    try:
        today = date.today().isoformat()
        events = get_upcoming_events(days_ahead=0)
        # days_ahead=0 이면 오늘만, 하지만 API 특성상 1일 범위로 재조회
        all_today = [e for e in get_upcoming_events(days_ahead=1) if e["date"] == today]
        logger.debug(f"[EconCalendar] 오늘({today}) 고영향 이벤트 {len(all_today)}건")
        return all_today
    except Exception as e:
        logger.warning(f"[EconCalendar] get_high_impact_today 실패: {e}")
        return []


def is_high_risk_period() -> bool:
    """오늘 또는 내일 고영향 경제 이벤트가 있으면 True를 반환한다.

    리스크 관리 로직에서 매매 억제 여부 판단에 사용한다.

    Returns:
        True = 고위험 기간 (고영향 이벤트 임박)
        False = 이벤트 없음 또는 조회 실패
    """
    try:
        today = date.today()
        tomorrow = (today + timedelta(days=1)).isoformat()
        today_str = today.isoformat()

        events = get_upcoming_events(days_ahead=1)
        for e in events:
            if e["date"] in (today_str, tomorrow):
                logger.info(
                    f"[EconCalendar] 고위험 기간 감지: {e['event']} ({e['date']})"
                )
                return True
        return False
    except Exception as e:
        logger.warning(f"[EconCalendar] is_high_risk_period 실패: {e}")
        return False
