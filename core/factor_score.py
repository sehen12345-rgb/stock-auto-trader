"""
멀티팩터 퀀트 스코어링.
기술적 지표, 모멘텀, 거래량, 패턴을 종합해 0~100점 산출.
점수가 높을수록 매수 신호 강함.
"""
from __future__ import annotations
from typing import Any
from loguru import logger


def _get_finnhub_bonus(ticker: str) -> float:
    """Finnhub 시그널 보너스/패널티 계산.

    - 어닝 3일 이내: -20점
    - 인사이더 순매수 양수: +10점
    - 뉴스 센티멘트 > 0.3: +10점, < -0.3: -15점
    """
    bonus = 0.0
    try:
        from core.finnhub_client import get_earnings_calendar, get_insider_trades, get_news_sentiment

        # 어닝 임박 패널티
        cal = get_earnings_calendar(ticker)
        days_until = cal.get("days_until")
        if days_until is not None and 0 <= days_until <= 3:
            bonus -= 20
            logger.debug(f"[FactorScore] {ticker} 어닝 {days_until}일 전 — -20점")

        # 인사이더 순매수 보너스
        insider = get_insider_trades(ticker)
        if insider.get("net_buy_shares", 0) > 0:
            bonus += 10
            logger.debug(f"[FactorScore] {ticker} 인사이더 순매수 — +10점")

        # 뉴스 감성 보너스/패널티
        sentiment = get_news_sentiment(ticker)
        if sentiment > 0.3:
            bonus += 10
            logger.debug(f"[FactorScore] {ticker} 뉴스 긍정({sentiment:+.3f}) — +10점")
        elif sentiment < -0.3:
            bonus -= 15
            logger.debug(f"[FactorScore] {ticker} 뉴스 부정({sentiment:+.3f}) — -15점")

    except Exception as e:
        logger.debug(f"[FactorScore] {ticker} Finnhub 보너스 계산 실패: {e}")

    return bonus


def _get_macro_bonus() -> float:
    """FRED 거시경제 금리 방향 보너스.

    금리 인하 사이클이면 +5점 보너스.
    """
    try:
        from core.macro_filter import get_macro_regime
        regime = get_macro_regime()
        if regime.get("rate_dir") == "cutting":
            logger.debug("[FactorScore] 금리 인하 사이클 — +5점 보너스")
            return 5.0
    except Exception as e:
        logger.debug(f"[FactorScore] 거시경제 보너스 계산 실패: {e}")
    return 0.0


# 팩터별 가중치 (합계 = 100)
WEIGHTS = {
    "trend":     30,  # 추세 (MA 배열)
    "momentum":  25,  # 모멘텀 (RSI, MACD)
    "volume":    20,  # 거래량
    "pattern":   15,  # 캔들 패턴 + 지지저항
    "regime":    10,  # 시장 국면 보너스
}

# 이 점수 미만이면 LLM에 넘기지 않고 HOLD
# 52점: 너무 빡빡하지 않으면서 애매한 셋업 걸러냄
MIN_SCORE_TO_TRADE: float = 52.0


def score_ticker(data: dict[str, Any], regime: str = "neutral") -> float:
    """종목 멀티팩터 점수 계산 (0~100).

    Args:
        data: fetcher가 반환한 종목 데이터 딕셔너리
        regime: "bull" | "neutral" | "bear"
    Returns:
        float: 0~100 점수 (Finnhub/FRED 보너스 포함 시 범위 초과 가능, 상한 100 클램프)
    """
    scores: dict[str, float] = {}

    # ── 1. 추세 팩터 (30점) ────────────────────────────────────────
    trend = 0.0
    current = data.get("current_price", 0) or 0
    ma20   = data.get("ma20", 0) or 0
    ema9   = data.get("ema9") or 0
    ema21  = data.get("ema21") or 0
    week52_high = data.get("week52_high", 0) or 0
    pct_from_high = data.get("pct_from_high", 100) or 100

    if current > 0 and ma20 > 0:
        if current > ma20:
            trend += 40  # MA20 위
        if ema9 > 0 and ema21 > 0 and ema9 > ema21:
            trend += 30  # 단기EMA > 장기EMA (골든크로스 배열)
        if pct_from_high < 15:
            trend += 20  # 52주 고점 15% 이내 (강세)
        if pct_from_high < 5:
            trend += 10  # 52주 신고가 근처

    scores["trend"] = min(trend, 100)

    # ── 2. 모멘텀 팩터 (25점) ────────────────────────────────────
    momentum = 0.0
    rsi = data.get("rsi")
    macd_hist = data.get("macd_hist")
    stoch_k = data.get("stoch_k")
    adx = data.get("adx")

    if rsi is not None:
        # 45~60 구간이 스윙 매수 최적 (추세 유지 + 과매수 아님)
        if 45 <= rsi <= 60:
            momentum += 40  # 황금 구간
        elif 40 <= rsi < 45 or 60 < rsi <= 65:
            momentum += 25
        elif 30 <= rsi < 40:
            momentum += 15  # 바닥권 반등 — 추세 미확인
        elif rsi > 70:
            momentum -= 10  # 과매수 패널티

    if macd_hist is not None:
        if macd_hist > 0:
            momentum += 30  # MACD 히스토그램 양전환
        elif macd_hist > -0.5:
            momentum += 10  # 음수지만 수렴 중

    if adx is not None and adx > 25:
        momentum += 20  # 추세 강도 충분
    elif adx is not None and adx > 20:
        momentum += 10

    if stoch_k is not None and 20 <= stoch_k <= 80:
        momentum += 15  # 스토캐스틱 중립 구간

    scores["momentum"] = min(momentum, 100)

    # ── 3. 거래량 팩터 (20점) ────────────────────────────────────
    volume = 0.0
    vol_ratio = data.get("volume_ratio", 0) or 0
    above_poc = data.get("above_poc", False)
    heavy_resistance = data.get("heavy_resistance", False)

    if vol_ratio >= 3.0:
        volume += 60  # 거래량 3배 이상 → 기관/세력 개입 신호
    elif vol_ratio >= 2.0:
        volume += 45  # 2배 이상 → 강한 관심
    elif vol_ratio >= 1.5:
        volume += 30
    elif vol_ratio >= 1.2:
        volume += 20
    elif vol_ratio >= 0.8:
        volume += 10  # 평균 근처 → 소폭 가산
    elif vol_ratio >= 0.5:
        volume += 0   # 낮지만 패널티 없음
    elif vol_ratio < 0.5:
        volume -= 10  # 거래량 절반 미만일 때만 패널티

    if above_poc:
        volume += 25  # 매물대(POC) 위에서 거래 → 돌파
    if not heavy_resistance:
        volume += 15  # 강한 매물 저항 없음

    scores["volume"] = min(volume, 100)

    # ── 4. 패턴 팩터 (15점) ────────────────────────────────────
    pattern = 0.0
    bullish_patterns = [
        data.get("hammer", False),
        data.get("bullish_engulfing", False),
        data.get("morning_star", False),
        data.get("double_bottom", False),
    ]
    bearish_patterns = [
        data.get("shooting_star", False),
        data.get("bearish_engulfing", False),
    ]
    near_support = data.get("near_support", False)
    near_resistance = data.get("near_resistance", False)
    pullback = data.get("pullback_detected", False)

    bull_count = sum(1 for p in bullish_patterns if p)
    bear_count = sum(1 for p in bearish_patterns if p)

    pattern += bull_count * 25
    pattern -= bear_count * 30

    if near_support:
        pattern += 25  # 지지선 근처 매수
    if near_resistance:
        pattern -= 20  # 저항선 근처 → 불리

    if pullback:
        pullback_score = data.get("pullback_score", 0) or 0
        pattern += min(pullback_score * 5, 30)  # 풀백 점수 반영

    scores["pattern"] = max(0, min(pattern, 100))

    # ── 5. 시장 국면 보너스 (10점) ──────────────────────────────
    regime_score = {"bull": 100, "neutral": 50, "bear": 0}.get(regime, 50)
    scores["regime"] = regime_score

    # ── 종합 점수 ────────────────────────────────────────────────
    total = sum(
        scores[k] * WEIGHTS[k] / 100
        for k in WEIGHTS
    )

    # ── 외부 API 보너스 (Finnhub + FRED) ─────────────────────────
    ticker = data.get("ticker", "")
    if ticker:
        total += _get_finnhub_bonus(ticker)
        total += _get_macro_bonus()

    total = max(0.0, min(total, 100.0))  # 0~100 클램프

    logger.debug(
        f"[FactorScore] {ticker or '?'} "
        f"총점={total:.1f} "
        f"(추세={scores['trend']:.0f} 모멘텀={scores['momentum']:.0f} "
        f"거래량={scores['volume']:.0f} 패턴={scores['pattern']:.0f} "
        f"리짐={scores['regime']:.0f})"
    )
    return round(total, 1)


def rank_tickers(
    market_data: dict[str, dict[str, Any]],
    held_symbols: set[str],
    regime: str = "neutral",
) -> list[tuple[str, float]]:
    """watchlist 전체 종목을 팩터 점수로 랭킹.

    Returns:
        [(ticker, score), ...] 내림차순 정렬
    """
    ranked = []
    for ticker, data in market_data.items():
        if not data or data.get("current_price", 0) <= 0:
            continue
        score = score_ticker(data, regime=regime)
        ranked.append((ticker, score))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked
