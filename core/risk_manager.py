"""
프로 퀀트 리스크 관리 모듈.
ATR 기반 동적 손절 + 리스크 패리티 포지션 사이징.
"""
from __future__ import annotations
from typing import Any
from loguru import logger


# 포트폴리오 대비 종목당 리스크 한도
RISK_PER_TRADE_PCT: float = 1.5   # 참고용

# ── 공격 모드 (201만원 → 1000만원) ─────────────────────────────────────────
# 1슬롯 집중 80% 베팅: 201만원 × 80% = ~160만원 올인
# 손익비 1:2 (손절 1.5% : 익절 3%) — 승률 40%만 돼도 기댓값 양수
SLOT_ALLOCATION_PCT: float = 80.0  # 시드의 80% = ~160만원/슬롯 (공격 모드)
# 1000만원 달성 후 자동 전환되는 보존 모드 비율
SLOT_ALLOCATION_PCT_SAFE: float = 45.0  # 시드의 45% = 분산 보존 모드

# ATR 배수: 1.5배
ATR_STOP_MULTIPLIER: float = 1.5
# Kelly 상한
MAX_KELLY_FRACTION: float = 0.25  # 공격 모드 Kelly 상한 상향


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
    """슬롯 기반 포지션 사이징 (소액 시드 자본 효율 최대화).

    1차: 슬롯 배분 기준 (seed × SLOT_ALLOCATION_PCT%)
    2차: 가용 예수금 상한 적용
    3차: 최소 1주 보장 (예수금 충분 시)

    예: seed=201만원, 삼성 274,500원
      슬롯금액 = 201만 × 45% = 90만원
      qty = 900,000 // 274,500 = 3주 (82만원 투자)
    """
    # 슬롯 배분 금액 (원화 기준)
    slot_amount_krw = seed_amount * (SLOT_ALLOCATION_PCT / 100)

    if is_overseas:
        slot_amount_usd = slot_amount_krw / usd_krw
        qty_by_slot = int(slot_amount_usd // entry_price)
        qty_by_cash = int((available_cash / usd_krw) // entry_price)
    else:
        qty_by_slot = int(slot_amount_krw // entry_price)
        qty_by_cash = int(available_cash // entry_price)

    qty = min(qty_by_slot, qty_by_cash)

    # 최소 1주 (예수금이 1주 이상 살 수 있을 때만)
    can_afford = available_cash >= entry_price * (1 if not is_overseas else usd_krw / usd_krw)
    return max(qty, 1) if can_afford and qty_by_cash >= 1 else 0


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
