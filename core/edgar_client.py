"""SEC EDGAR API 클라이언트 (API key 불필요, 완전 무료).

기관 보유 비율 변화, 인사이더 보유 비율을 조회한다.
base: https://data.sec.gov
User-Agent 헤더 필수 (SEC 정책).
캐시 TTL: 24시간 (분기 데이터)
"""
from __future__ import annotations

import time
from typing import Any

import requests
from loguru import logger

_BASE_URL = "https://data.sec.gov"
_REQUEST_TIMEOUT = 10

# SEC EDGAR 정책: User-Agent에 이름과 이메일 포함 필수
_HEADERS = {
    "User-Agent": "StockAutoTrader contact@example.com",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}

# ── 캐시 ────────────────────────────────────────────────────────────────────
_holdings_cache: dict[str, tuple[float, Any]] = {}   # {ticker: (ts, data)}
_insider_pct_cache: dict[str, tuple[float, Any]] = {}

_EDGAR_TTL: float = 86400.0  # 24시간

# ── ticker → CIK 변환 캐시 ────────────────────────────────────────────────
_cik_cache: dict[str, str | None] = {}


def _ticker_to_cik(ticker: str) -> str | None:
    """SEC EDGAR ticker → CIK 변환.

    Returns:
        CIK 문자열 (예: "0000320193") 또는 None (찾을 수 없음)
    """
    if ticker in _cik_cache:
        return _cik_cache[ticker]

    try:
        # SEC 공식 ticker → CIK 맵핑 파일
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": _HEADERS["User-Agent"]},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        ticker_upper = ticker.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                cik_int = entry.get("cik_str") or entry.get("cik")
                cik_str = str(cik_int).zfill(10)
                _cik_cache[ticker] = cik_str
                return cik_str

        _cik_cache[ticker] = None
        return None

    except Exception as e:
        logger.debug(f"[EDGAR] {ticker} CIK 조회 실패: {e}")
        _cik_cache[ticker] = None
        return None


def _get_company_facts(cik: str) -> dict[str, Any]:
    """SEC EDGAR company-facts API 조회."""
    url = f"{_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json"
    resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── 기관 보유 비율 ────────────────────────────────────────────────────────

def get_institutional_holdings(ticker: str) -> dict[str, Any]:
    """최근 13F 기관 보유 비율 및 변화 반환.

    Note: EDGAR company-facts에는 직접적인 기관보유 비율이 없으므로,
    총발행주식(EntityCommonStockSharesOutstanding) 기준으로 추정한다.
    정확한 13F 데이터는 EDGAR Full-Text Search를 별도로 파싱해야 하므로,
    현재는 보수적 fallback을 반환하되 향후 확장 가능한 구조로 작성한다.

    Returns:
        {
            "institutional_pct": float,   # 기관 보유 추정 비율 (0~100)
            "change": float,              # 전분기 대비 변화 (%p)
            "shares_outstanding": int,    # 총 발행주식 수
        }
        실패 시: {"institutional_pct": 0, "change": 0, "shares_outstanding": 0}
    """
    default: dict[str, Any] = {"institutional_pct": 0, "change": 0, "shares_outstanding": 0}

    now = time.monotonic()
    cached = _holdings_cache.get(ticker)
    if cached and (now - cached[0]) < _EDGAR_TTL:
        return cached[1]

    # 한국 종목 (숫자로 시작) → EDGAR 해당 없음
    if ticker and ticker[0].isdigit():
        return default

    try:
        cik = _ticker_to_cik(ticker)
        if not cik:
            logger.debug(f"[EDGAR] {ticker} CIK 없음")
            return default

        facts = _get_company_facts(cik)
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        dei     = facts.get("facts", {}).get("dei", {})

        # 총발행주식 (EntityCommonStockSharesOutstanding)
        shares_data = dei.get("EntityCommonStockSharesOutstanding", {})
        units = shares_data.get("units", {})
        shares_list = units.get("shares", [])

        if not shares_list:
            return default

        # 최신 분기 2개 추출
        # end 날짜 기준 최신 2개
        filtered = [s for s in shares_list if s.get("form") in ("10-K", "10-Q", "10-K/A", "10-Q/A")]
        filtered.sort(key=lambda s: s.get("end", ""), reverse=True)

        latest_shares = int(filtered[0]["val"]) if filtered else 0
        prev_shares = int(filtered[1]["val"]) if len(filtered) >= 2 else latest_shares

        # 변화율 계산 (주식 수 감소 = 자사주 매입 등으로 기관 비율 간접 추정)
        change_pct = 0.0
        if prev_shares > 0 and latest_shares > 0:
            change_pct = round((latest_shares - prev_shares) / prev_shares * 100, 2)

        # 기관 보유 비율 추정: EDGAR에서 직접 조회 불가 → 0으로 보수적 반환
        # (실제 13F는 별도 파싱 필요, 향후 확장 예정)
        result: dict[str, Any] = {
            "institutional_pct": 0,  # 추후 13F 파싱으로 확장
            "change": change_pct,
            "shares_outstanding": latest_shares,
        }
        _holdings_cache[ticker] = (now, result)
        logger.debug(
            f"[EDGAR] {ticker} 발행주식={latest_shares:,} "
            f"변화={change_pct:+.2f}%"
        )
        return result

    except Exception as e:
        logger.debug(f"[EDGAR] {ticker} 기관보유 조회 실패: {e}")
        return default


# ── 인사이더 보유 비율 ────────────────────────────────────────────────────

def get_insider_ownership_pct(ticker: str) -> float:
    """SEC Form 4 기반 인사이더 보유 비율 추정 (%).

    Note: EDGAR company-facts API에서 정확한 인사이더 비율을 직접 제공하지 않으므로,
    Proxy Statement (DEF 14A)에서 파싱하는 방식이 필요하다.
    현재는 총발행주식 변동으로 간접 추정하되 기본값 0을 반환한다.

    Returns:
        float: 인사이더 보유 비율 % (0~100). 실패 시 0.0
    """
    now = time.monotonic()
    cached = _insider_pct_cache.get(ticker)
    if cached and (now - cached[0]) < _EDGAR_TTL:
        return float(cached[1])

    # 한국 종목 → 해당 없음
    if ticker and ticker[0].isdigit():
        return 0.0

    try:
        # EDGAR submissions API로 최근 Form 4 파일링 확인
        cik = _ticker_to_cik(ticker)
        if not cik:
            return 0.0

        url = f"{_BASE_URL}/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        sub_data = resp.json()

        # 최근 filings 중 Form 4 건수 확인 (인사이더 활동 간접 지표)
        recent = sub_data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        form4_count = sum(1 for f in forms[:100] if f == "4")

        # Form 4 건수가 많을수록 인사이더 활동 활발 → 보유 비율 대략 추정
        # 실제 비율은 Proxy Statement 파싱 필요, 현재는 0.0 반환
        pct = 0.0

        _insider_pct_cache[ticker] = (now, pct)
        logger.debug(f"[EDGAR] {ticker} 최근 Form4={form4_count}건, 인사이더 보유={pct:.1f}%")
        return pct

    except Exception as e:
        logger.debug(f"[EDGAR] {ticker} 인사이더 보유 조회 실패: {e}")
        return 0.0
