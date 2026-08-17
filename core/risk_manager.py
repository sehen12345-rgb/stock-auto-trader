"""
프로 퀀트 리스크 관리 모듈.
ATR 기반 동적 손절 + 리스크 패리티 포지션 사이징.
"""
from __future__ import annotations
from typing import Any
from loguru import logger


# 포트폴리오 대비 종목당 리스크 한도
# 201만원 소액 시드: 1회 손실 최대 1.5% (~3만원) → 복구 가능한 수준
RISK_PER_TRADE_PCT: float = 1.5
# ATR 배수: 1.5배 → 더 타이트한 손절 (스윙 트레이딩에 적합)
ATR_STOP_MULTIPLIER: float = 1.5
# Kelly 상한 (소액 시드: 과도한 집중 방지)
MAX_KELLY_FRACTION: float = 0.20


def calc_atr_stop(entry_price: float, atr: float | None, is_overseas: bool) -> float:
    """ATR 기반 동적 손절가 계산.

    손절 = 진입가 - (ATR × ATR_STOP_MULTIPLIER)
    ATR 없으면 해외 2%, 국내 1.5% 고정 폴백.
    """
    if atr and atr > 0:
        stop = entry_price - (atr * ATR_STOP_MULTIPLIER)
    else:
        # 폴백: 해외 1.5%, 국내 1.0% (스윙 기준)
        fallback_pct = 0.015 if is_overseas else 0.010
        stop = entry_price * (1 - fallback_pct)

    dec = 2 if is_overseas else 0
    return round(max(stop, 0), dec)


def calc_position_size(
    available_cash: float,
    entry_price: float,
    stop_price: float,
    seed_amount: float,
    is_overseas: bool,
    usd_krw: float = 1300.0,
) -> int:
    """리스크 패리티 기반 수량 계산.

    리스크 = seed × RISK_PER_TRADE_PCT%
    수량 = 리스크 / (진입가 - 손절가)
    예수금 초과 시 가용 예수금 기준으로 줄임.
    """
    risk_amount = seed_amount * (RISK_PER_TRADE_PCT / 100)  # 포트폴리오 1%

    price_risk = entry_price - stop_price  # 1주당 리스크
    if price_risk <= 0:
        # 손절가 계산 오류 → 가용 예수금 기준 폴백
        if is_overseas:
            return max(1, int((available_cash / usd_krw) // entry_price))
        return max(1, int(available_cash // entry_price))

    if is_overseas:
        # 달러 기준으로 계산
        risk_usd = risk_amount / usd_krw
        qty = int(risk_usd / price_risk)
        max_qty_by_cash = int((available_cash / usd_krw) // entry_price)
    else:
        qty = int(risk_amount / price_risk)
        max_qty_by_cash = int(available_cash // entry_price)

    qty = min(qty, max_qty_by_cash)
    return max(qty, 1) if available_cash >= entry_price * (usd_krw if is_overseas else 1) / (usd_krw if is_overseas else 1) else 0


def kelly_position_size(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    available_cash: float,
    entry_price: float,
    is_overseas: bool,
    usd_krw: float = 1300.0,
) -> int:
    """Kelly Criterion 기반 포지션 사이징.

    Kelly = W - (1-W)/R
    W: 승률, R: 손익비 (평균이익/평균손실)
    상한: MAX_KELLY_FRACTION
    """
    if avg_loss <= 0 or win_rate <= 0:
        return 0
    r = avg_win / avg_loss  # 손익비
    kelly_f = win_rate - (1 - win_rate) / r
    kelly_f = max(0.0, min(kelly_f, MAX_KELLY_FRACTION))

    bet_amount = available_cash * kelly_f
    if is_overseas:
        qty = int((bet_amount / usd_krw) // entry_price)
    else:
        qty = int(bet_amount // entry_price)

    logger.debug(
        f"[RiskMgr] Kelly: W={win_rate:.0%} R={r:.2f} → f={kelly_f:.1%} "
        f"→ {qty}주 (베팅 {bet_amount:,.0f}원)"
    )
    return max(qty, 0)
