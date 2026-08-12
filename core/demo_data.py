"""
데모 모드용 가짜 데이터 생성기.
DEMO_MODE=true 일 때 실제 API 없이 현실적인 데이터를 시뮬레이션한다.
"""
import random
from datetime import datetime, timedelta
from typing import Any

# ──────────────────────────────────────────────
# 종목 기준 데이터
# ──────────────────────────────────────────────
DEMO_STOCKS: dict[str, dict[str, Any]] = {
    # KOSPI
    "005930": {"name": "삼성전자", "market": "KR", "base_price": 75400, "week52_high": 88800},
    "000660": {"name": "SK하이닉스", "market": "KR", "base_price": 189500, "week52_high": 238000},
    "035420": {"name": "NAVER", "market": "KR", "base_price": 198500, "week52_high": 248000},
    "051910": {"name": "LG화학", "market": "KR", "base_price": 312000, "week52_high": 420000},
    "006400": {"name": "삼성SDI", "market": "KR", "base_price": 258000, "week52_high": 380000},
    # NASDAQ
    "AAPL":  {"name": "Apple", "market": "US", "base_price": 227.5, "week52_high": 237.2},
    "NVDA":  {"name": "NVIDIA", "market": "US", "base_price": 138.9, "week52_high": 153.1},
    "MSFT":  {"name": "Microsoft", "market": "US", "base_price": 441.2, "week52_high": 468.3},
    "TSLA":  {"name": "Tesla", "market": "US", "base_price": 248.7, "week52_high": 358.6},
    "AMZN":  {"name": "Amazon", "market": "US", "base_price": 218.3, "week52_high": 242.5},
}

# 인스턴스별 현재가 캐시 (요청마다 ±0.5% 랜덤)
_price_cache: dict[str, float] = {}


def _jitter(base: float, pct: float = 0.005) -> float:
    """base 가격에 ±pct 범위 랜덤 노이즈를 더해 반환."""
    return round(base * (1 + random.uniform(-pct, pct)), 2)


def get_demo_ticker(ticker: str) -> dict[str, Any]:
    """단일 종목 시세 데이터 반환 (실제 DataFetcher.fetch 형식과 동일)."""
    stock = DEMO_STOCKS.get(ticker)
    if stock is None:
        # 알 수 없는 종목: 더미
        return {
            "ticker": ticker,
            "current_price": 10000.0,
            "volume": 100000,
            "ma20": 9800.0,
            "avg_volume_20": 80000,
            "week52_high": 12000.0,
            "above_ma20": True,
            "volume_surge": True,
        }

    base = stock["base_price"]
    if ticker not in _price_cache:
        _price_cache[ticker] = base
    # 매 호출마다 소폭 변동
    _price_cache[ticker] = _jitter(_price_cache[ticker], 0.005)
    cur = _price_cache[ticker]

    ma20 = round(base * random.uniform(0.97, 0.99), 2)
    avg_vol = random.randint(500_000, 3_000_000)
    volume = int(avg_vol * random.uniform(1.0, 2.2))
    week52_high = stock["week52_high"]

    return {
        "ticker": ticker,
        "current_price": cur,
        "volume": volume,
        "ma20": ma20,
        "avg_volume_20": avg_vol,
        "week52_high": week52_high,
        "above_ma20": cur > ma20,
        "volume_surge": volume >= avg_vol * 1.5,
        "name": stock["name"],
        "market": stock["market"],
    }


def get_demo_portfolio() -> dict[str, Any]:
    """포트폴리오 요약 (총평가액, 현금, 수익률)."""
    seed = 10_000_000  # 1천만원 시드
    invested = seed * 0.65
    pnl_pct = round(random.uniform(-0.8, 3.2), 2)
    total_value = round(invested * (1 + pnl_pct / 100) + seed * 0.35, 0)
    cash = round(seed * 0.35, 0)
    return {
        "total_value": total_value,
        "cash": cash,
        "return_pct": pnl_pct,
        "seed": seed,
    }


def get_demo_positions() -> list[dict[str, Any]]:
    """현재 보유 포지션 샘플 (2~3종목)."""
    tickers = [("005930", "삼성전자"), ("000660", "SK하이닉스"), ("NVDA", "NVIDIA")]
    results = []
    base_date = datetime.now() - timedelta(days=random.randint(3, 15))
    for ticker, name in tickers:
        stock = DEMO_STOCKS[ticker]
        avg = round(stock["base_price"] * random.uniform(0.95, 1.02), 2)
        cur = _price_cache.get(ticker, _jitter(stock["base_price"]))
        qty = random.randint(3, 20)
        pnl_pct = round((cur - avg) / avg * 100, 2)
        stop_price = round(avg * 0.965, 2)
        target_price = round(avg * 1.06, 2)
        results.append({
            "symbol": ticker,
            "name": name,
            "quantity": qty,
            "avg_price": avg,
            "current_price": cur,
            "value": round(cur * qty, 0),
            "pnl_pct": pnl_pct,
            "market": stock["market"],
            "opened_at": (base_date + timedelta(days=random.randint(0, 5))).strftime("%Y-%m-%d"),
            "stop_price": stop_price,
            "target_price": target_price,
            "oco_active": True,
        })
    return results


# 데모 LLM 판단 풀
_DEMO_REASONS = [
    "삼성전자가 20일 이동평균선 위에서 거래량 급증 중. 52주 고점 돌파 임박으로 강력 매수 신호.",
    "SK하이닉스 HBM 수요 증가로 외국인 순매수 지속. 목표가 +6% 단계적 익절 예정.",
    "NVDA 실적 발표 앞두고 옵션 시장 강세. 현재가 MA20 상위 유지 중.",
    "코스피 전체 -0.8% 하락으로 신규 매수 보류. 현재 포지션 유지 (HOLD).",
    "AAPL 52주 고점 -2.3% 수준. 거래량 평균 대비 1.7배, 돌파 시 추가 매수 검토.",
    "LG화학 목표가 도달(-3.5% 손절선 접근). 리스크 관리 차원에서 매도 신호 발생.",
    "시장 전체 상승세이나 MSFT 거래량 부족 (평균 대비 0.9배). 신뢰도 낮아 HOLD.",
    "TSLA 변동성 확대 구간. 올랜도킴 전략상 4종목 보유 한도 초과로 신규 진입 불가.",
    "NAVER 20일 이평선 하향 이탈. 매수 조건 미충족으로 관망 유지.",
    "삼성SDI 52주 고점 대비 -18% 수준. 반등 가능성 있으나 이평선 조건 미충족.",
]

_DEMO_DECISIONS = [
    {"decision": "BUY",  "ticker": "005930", "quantity": 10, "confidence": 78},
    {"decision": "BUY",  "ticker": "NVDA",   "quantity": 5,  "confidence": 82},
    {"decision": "HOLD", "ticker": "",        "quantity": 0,  "confidence": 55},
    {"decision": "SELL", "ticker": "000660",  "quantity": 8,  "confidence": 71},
    {"decision": "HOLD", "ticker": "",        "quantity": 0,  "confidence": 62},
    {"decision": "BUY",  "ticker": "AAPL",   "quantity": 3,  "confidence": 69},
]


def get_demo_decision() -> dict[str, Any]:
    """LLM 판단 샘플 1건 반환."""
    base = random.choice(_DEMO_DECISIONS).copy()
    base["reason"] = random.choice(_DEMO_REASONS)
    base["timestamp"] = datetime.now().isoformat(timespec="seconds")
    return base


def get_demo_return_history(days: int = 30) -> list[dict[str, Any]]:
    """30일치 EOD 수익률 추이 샘플 데이터."""
    result = []
    pct = 0.0
    base = datetime.now() - timedelta(days=days)
    for i in range(days):
        pct = round(pct + random.uniform(-0.5, 0.8), 2)
        result.append({
            "date": (base + timedelta(days=i)).strftime("%m/%d"),
            "return_pct": pct,
        })
    return result


def get_demo_watchlist() -> list[dict[str, Any]]:
    """기본 관심종목 데이터."""
    items = []
    for ticker in ["005930", "000660", "AAPL", "NVDA", "MSFT"]:
        data = get_demo_ticker(ticker)
        stock = DEMO_STOCKS[ticker]
        high = stock["week52_high"]
        cur = data["current_price"]
        pct_from_high = round((high - cur) / high * 100, 2) if high > 0 else None
        items.append({
            "ticker": ticker,
            "name": stock["name"],
            "current_price": cur,
            "week52_high": high,
            "pct_from_high": pct_from_high,
        })
    return items
