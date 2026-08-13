"""단타(Day Trading) 전략.

조건: MACD > MACD_signal (골든크로스) AND RSI 40~65 AND 현재가 > MA20
볼린저 하단 터치 후 반등 시 추가 점수
손절: -2%, 익절: +4%
"""
from typing import Any

from loguru import logger

from core.strategy.base import BaseStrategy, Signal, SignalType, StrategyConfig


class DayTradingStrategy(BaseStrategy):
    """단타 전략."""

    DEFAULT_PARAMS: dict[str, Any] = {
        "rsi_low": 40.0,
        "rsi_high": 65.0,
        "stop_pct": 2.0,
        "take_profit_pct": 4.0,
        "bb_bonus": 10.0,           # 볼린저 하단 근처 보너스 점수
    }

    def __init__(self, config: StrategyConfig | None = None) -> None:
        if config is None:
            config = StrategyConfig(
                name="DayTrading",
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

        필요 키: macd, macd_signal, rsi, current_price, ma20, bb_lower
        """
        if not data:
            return []

        signals: list[Signal] = []
        rsi_low = float(self.get_param("rsi_low"))
        rsi_high = float(self.get_param("rsi_high"))
        stop_pct = float(self.get_param("stop_pct"))
        tp_pct = float(self.get_param("take_profit_pct"))
        bb_bonus = float(self.get_param("bb_bonus"))

        for symbol, d in data.items():
            try:
                macd = d.get("macd")
                macd_signal = d.get("macd_signal")
                rsi = d.get("rsi")
                current_price = d.get("current_price", 0.0)
                ma20 = d.get("ma20", 0.0)
                bb_lower = d.get("bb_lower")

                if None in (macd, macd_signal, rsi) or not current_price:
                    continue

                # 골든크로스: MACD > MACD_signal
                cond_macd = macd > macd_signal
                # RSI 40~65 범위
                cond_rsi = rsi_low <= rsi <= rsi_high
                # 현재가 > MA20
                cond_ma = (ma20 > 0) and (current_price > ma20)

                if cond_macd and cond_rsi and cond_ma:
                    score = (macd - macd_signal) * 100 + (rsi - rsi_low)
                    reasons = [
                        f"단타 매수: MACD골든크로스({macd:.4f}>{macd_signal:.4f})",
                        f"RSI={rsi:.1f}({rsi_low}~{rsi_high})",
                        f"현재가{current_price:,.0f}>MA20({ma20:,.0f})",
                    ]

                    # 볼린저 하단 근접 보너스
                    if bb_lower is not None and current_price <= bb_lower * 1.02:
                        score += bb_bonus
                        reasons.append(f"볼린저하단 근접({bb_lower:,.0f}) 반등 보너스")

                    reason = ". ".join(reasons) + f". 손절-{stop_pct}%/익절+{tp_pct}%"
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
                                "macd_signal": macd_signal,
                                "ma20": ma20,
                                "bb_lower": bb_lower,
                                "stop_pct": stop_pct,
                                "take_profit_pct": tp_pct,
                            },
                        )
                    )
                    logger.info(f"[DayTrading] {symbol} 매수 신호 score={score:.2f} RSI={rsi:.1f}")

            except Exception as e:
                logger.warning(f"[DayTrading] {symbol} 신호 생성 오류: {e}")

        return signals
