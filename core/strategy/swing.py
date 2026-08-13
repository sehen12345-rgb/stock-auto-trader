"""스윙 전략.

조건: 눌림목 감지(is_pullback) AND MA20 위 AND RSI 40~60 AND MACD > 0
손절: -3.5%, 익절: +8~15%
52주 고점 10% 이내면 추가 점수
"""
from typing import Any

from loguru import logger

from core.strategy.base import BaseStrategy, Signal, SignalType, StrategyConfig


class SwingStrategy(BaseStrategy):
    """스윙 전략."""

    DEFAULT_PARAMS: dict[str, Any] = {
        "rsi_low": 40.0,
        "rsi_high": 60.0,
        "stop_pct": 3.5,
        "take_profit_pct": 8.0,
        "week52_bonus_pct": 10.0,    # 52주 고점 N% 이내 보너스 기준
        "week52_bonus_score": 15.0,  # 보너스 점수
    }

    def __init__(self, config: StrategyConfig | None = None) -> None:
        if config is None:
            config = StrategyConfig(
                name="Swing",
                params=self.DEFAULT_PARAMS.copy(),
            )
        else:
            for k, v in self.DEFAULT_PARAMS.items():
                config.params.setdefault(k, v)
        super().__init__(config)

    def validate_data(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        return True

    def generate_signals(self, data: Any) -> list[Signal]:
        """data: {symbol: market_data_dict}.

        필요 키: pullback_detected, above_ma20, rsi, macd, current_price, pct_from_high
        """
        if not data:
            return []

        signals: list[Signal] = []
        rsi_low = float(self.get_param("rsi_low"))
        rsi_high = float(self.get_param("rsi_high"))
        stop_pct = float(self.get_param("stop_pct"))
        tp_pct = float(self.get_param("take_profit_pct"))
        w52_thresh = float(self.get_param("week52_bonus_pct"))
        w52_bonus = float(self.get_param("week52_bonus_score"))

        for symbol, d in data.items():
            try:
                pullback = d.get("pullback_detected", False)
                above_ma20 = d.get("above_ma20", False)
                rsi = d.get("rsi")
                macd = d.get("macd")
                current_price = d.get("current_price", 0.0)
                pct_from_high = d.get("pct_from_high", 100.0)

                if rsi is None or macd is None or not current_price:
                    continue

                # 스윙 조건: 눌림목 + MA20위 + RSI 범위 + MACD > 0
                cond_pullback = pullback
                cond_ma = above_ma20
                cond_rsi = rsi_low <= rsi <= rsi_high
                cond_macd = macd > 0

                if cond_pullback and cond_ma and cond_rsi and cond_macd:
                    score = (rsi - rsi_low) + (macd * 100)
                    reasons = [
                        "스윙 매수: 눌림목 감지",
                        f"MA20 위 유지",
                        f"RSI={rsi:.1f}({rsi_low}~{rsi_high})",
                        f"MACD={macd:.4f}(양수)",
                    ]

                    # 52주 고점 10% 이내 보너스
                    if pct_from_high is not None and pct_from_high <= w52_thresh:
                        score += w52_bonus
                        reasons.append(f"52주고점 {pct_from_high:.1f}% 이내 — 돌파 임박 보너스")

                    reason = ". ".join(reasons) + f". 손절-{stop_pct}%/익절+{tp_pct}~15%"
                    signals.append(
                        Signal(
                            symbol=symbol,
                            signal_type=SignalType.BUY,
                            strategy_name=self.name,
                            price=current_price,
                            score=score,
                            reason=reason,
                            metadata={
                                "rsi": rsi,
                                "macd": macd,
                                "pct_from_high": pct_from_high,
                                "pullback": pullback,
                                "stop_pct": stop_pct,
                                "take_profit_pct": tp_pct,
                            },
                        )
                    )
                    logger.info(f"[Swing] {symbol} 매수 신호 score={score:.2f} RSI={rsi:.1f}")

            except Exception as e:
                logger.warning(f"[Swing] {symbol} 신호 생성 오류: {e}")

        return signals
