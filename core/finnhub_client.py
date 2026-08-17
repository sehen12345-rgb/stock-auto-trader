"""Finnhub 무료 API 클라이언트.

어닝 캘린더, 인사이더 매매, 뉴스 감성 분석을 제공한다.
API key: FINNHUB_API_KEY 환경변수 (없으면 graceful fallback)
무료 tier: 60 req/min
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from typing import Any

import requests
from loguru import logger

_BASE_URL = "https://finnhub.io/api/v1"
_REQUEST_TIMEOUT = 5

# ── 캐시 ────────────────────────────────────────────────────────────────────
_earnings_cache: dict[str, tuple[float, Any]] = {}   # {ticker: (ts, data)}
_insider_cache:  dict[str, tuple[float, Any]] = {}
_news_cache:     dict[str, tuple[float, Any]] = {}

_EARNINGS_TTL: float = 3600.0    # 1시간
_INSIDER_TTL:  float = 21600.0   # 6시간
_NEWS_TTL:     float = 1800.0    # 30분


def _api_key() -> str | None:
    return os.getenv("FINNHUB_API_KEY") or None


def _get(endpoint: str, params: dict[str, Any]) -> Any:
    """Finnhub API GET 요청 (공통)."""
    key = _api_key()
    if not key:
        raise ValueError("FINNHUB_API_KEY 없음")
    params["token"] = key
    resp = requests.get(
        f"{_BASE_URL}{endpoint}",
        params=params,
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ── 어닝 캘린더 ────────────────────────────────────────────────────────────

def get_earnings_calendar(ticker: str) -> dict[str, Any]:
    """다음 어닝 발표일 및 며칠 남았는지 반환.

    Returns:
        {
            "next_date": "2024-11-20",  # 없으면 None
            "days_until": 15,           # 없으면 None
        }
        실패 시: {"next_date": None, "days_until": None}
    """
    default: dict[str, Any] = {"next_date": None, "days_until": None}

    now = time.monotonic()
    cached = _earnings_cache.get(ticker)
    if cached and (now - cached[0]) < _EARNINGS_TTL:
        return cached[1]

    try:
        today = date.today()
        from_date = today.isoformat()
        to_date = (today + timedelta(days=90)).isoformat()

        data = _get("/calendar/earnings", {
            "symbol": ticker,
            "from": from_date,
            "to": to_date,
        })

        earnings_list = data.get("earningsCalendar", [])
        if not earnings_list:
            result = default
        else:
            # 오늘 이후 가장 빠른 날짜 선택
            future = [
                e for e in earnings_list
                if e.get("date") and e["date"] >= from_date
            ]
            if not future:
                result = default
            else:
                next_entry = min(future, key=lambda e: e["date"])
                next_date_str = next_entry["date"]
                next_date_obj = date.fromisoformat(next_date_str)
                days_until = (next_date_obj - today).days
                result = {"next_date": next_date_str, "days_until": days_until}

        _earnings_cache[ticker] = (now, result)
        logger.debug(f"[Finnhub] {ticker} 어닝: {result}")
        return result

    except ValueError:
        # API key 없음 — 조용히 fallback
        return default
    except Exception as e:
        logger.debug(f"[Finnhub] {ticker} 어닝 캘린더 조회 실패: {e}")
        return default


# ── 인사이더 매매 ──────────────────────────────────────────────────────────

def get_insider_trades(ticker: str) -> dict[str, Any]:
    """최근 30일 인사이더 매수/매도 비율 반환.

    Returns:
        {
            "net_buy_shares": int,   # 순매수 주식 수 (양수=매수, 음수=매도)
            "buy_count": int,
            "sell_count": int,
        }
        실패 시: {"net_buy_shares": 0, "buy_count": 0, "sell_count": 0}
    """
    default: dict[str, Any] = {"net_buy_shares": 0, "buy_count": 0, "sell_count": 0}

    now = time.monotonic()
    cached = _insider_cache.get(ticker)
    if cached and (now - cached[0]) < _INSIDER_TTL:
        return cached[1]

    try:
        data = _get("/stock/insider-transactions", {"symbol": ticker})
        transactions = data.get("data", []) or []

        cutoff = (date.today() - timedelta(days=30)).isoformat()
        recent = [t for t in transactions if t.get("transactionDate", "") >= cutoff]

        net_shares = 0
        buy_count = 0
        sell_count = 0

        for t in recent:
            change = t.get("change", 0) or 0
            if change > 0:
                buy_count += 1
                net_shares += change
            elif change < 0:
                sell_count += 1
                net_shares += change  # 음수

        result: dict[str, Any] = {
            "net_buy_shares": net_shares,
            "buy_count": buy_count,
            "sell_count": sell_count,
        }
        _insider_cache[ticker] = (now, result)
        logger.debug(f"[Finnhub] {ticker} 인사이더: 순매수={net_shares:+,} (매수{buy_count}건/매도{sell_count}건)")
        return result

    except ValueError:
        return default
    except Exception as e:
        logger.debug(f"[Finnhub] {ticker} 인사이더 매매 조회 실패: {e}")
        return default


# ── 뉴스 감성 ──────────────────────────────────────────────────────────────

def get_news_sentiment(ticker: str) -> float:
    """최근 뉴스 감성 점수 (-1 ~ +1) 반환.

    +1 = 극도 긍정, -1 = 극도 부정, 0 = 중립

    실패 시: 0.0
    """
    now = time.monotonic()
    cached = _news_cache.get(ticker)
    if cached and (now - cached[0]) < _NEWS_TTL:
        return float(cached[1])

    try:
        data = _get("/news-sentiment", {"symbol": ticker})
        # Finnhub 반환: {"buzz": {...}, "sentiment": {"bullishPercent": 0.6, "bearishPercent": 0.4}}
        sentiment = data.get("sentiment", {})
        bullish = float(sentiment.get("bullishPercent", 0.5))
        bearish = float(sentiment.get("bearishPercent", 0.5))

        # -1 ~ +1 로 정규화 (bullish 비율 기반)
        score = round(bullish - bearish, 4)

        _news_cache[ticker] = (now, score)
        logger.debug(f"[Finnhub] {ticker} 뉴스 감성={score:+.3f} (긍정{bullish:.0%}/부정{bearish:.0%})")
        return score

    except ValueError:
        return 0.0
    except Exception as e:
        logger.debug(f"[Finnhub] {ticker} 뉴스 감성 조회 실패: {e}")
        return 0.0


# ── 종목 뉴스 헤드라인 ────────────────────────────────────────────────────

_company_news_cache: dict[str, tuple[float, Any]] = {}
_COMPANY_NEWS_TTL: float = 1800.0  # 30분


def get_company_news(ticker: str, max_items: int = 5) -> list[str]:
    """최근 종목 뉴스 헤드라인 반환.

    Returns:
        ["headline1", "headline2", ...] (최대 max_items개)
        실패 시: []
    """
    now = time.monotonic()
    cached = _company_news_cache.get(ticker)
    if cached and (now - cached[0]) < _COMPANY_NEWS_TTL:
        return list(cached[1])

    try:
        today = date.today()
        from_date = (today - timedelta(days=7)).isoformat()
        to_date = today.isoformat()

        data = _get("/company-news", {
            "symbol": ticker,
            "from": from_date,
            "to": to_date,
        })

        if not isinstance(data, list):
            _company_news_cache[ticker] = (now, [])
            return []

        headlines = [
            item.get("headline", "").strip()
            for item in data[:max_items]
            if item.get("headline", "").strip()
        ]
        _company_news_cache[ticker] = (now, headlines)
        logger.debug(f"[Finnhub] {ticker} 뉴스 {len(headlines)}건")
        return headlines

    except ValueError:
        return []
    except Exception as e:
        logger.debug(f"[Finnhub] {ticker} 뉴스 헤드라인 조회 실패: {e}")
        return []


# ── 어닝 임박 여부 (편의 함수) ────────────────────────────────────────────

def is_earnings_imminent(ticker: str, days: int = 3) -> bool:
    """어닝 발표가 `days`일 이내인지 확인.

    Returns:
        True면 어닝 임박 (매수 위험)
    """
    cal = get_earnings_calendar(ticker)
    days_until = cal.get("days_until")
    if days_until is None:
        return False
    return 0 <= days_until <= days
