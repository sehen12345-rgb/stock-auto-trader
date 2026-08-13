"""스캘핑 전략.

조건: RSI < 35 AND 거래량 1.5배 이상 AND 현재가 > EMA9
손절: -1%, 익절: +1.5%
"""
from typing import Any

import pandas as pd
from loguru import logger

from core.strategy.base import BaseStrategy, Signal, SignalType, StrategyConfig


class ScalpingStrategy(BaseStrategy):
    """초단기 스캘핑 전략."""

    DEFAULT_PARAMS: dict[str, Any] = {
        "rsi_threshold": 35.0,       # RSI 과매도 기준
        "volume_ratio_min": 1.5,      # 최소 거래량 배율
        "stop_pct": 1.0,              # 손절 %
        "take_profit_pct": 1.5,       # 익절 %
    }

    def __init__(self, config: StrategyConfig | None = None) -> None:
        if config is None:
            config = StrategyConfig(
                name="Scalping",
                params=self.DEFAULT_PARAMS.copy(),
            )
        else:
            for k, v in self.DEFAULT_PARAMS.items():
                config.params.setdefault(k, v)
        super().__init__(config)

    def validate_data(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        for symbol, item in data.items():
            if not isinstance(item, dict):
                return False
        return True

    def generate_signals(self, data: Any) -> list[Signal]:
        """data: {symbol: market_data_dict} (indicators 포함).

        market_data_dict 필요 키: rsi, volume_ratio, current_price, ema9
        """
        if not data:
            return []

        signals: list[Signal] = []
        rsi_thresh = float(self.get_param("rsi_threshold"))
        vol_min = float(self.get_param("volume_ratio_min"))
        stop_pct = float(self.get_param("stop_pct"))
        tp_pct = float(self.get_param("take_profit_pct"))

        for symbol, d in data.items():
            try:
                rsi = d.get("rsi")
                volume_ratio = d.get("volume_ratio", 0.0)
                current_price = d.get("current_price", 0.0)
                ema9 = d.get("ema9")

                if rsi is None or not current_price:
                    continue

                # 매수 조건: RSI < 35, 거래량 1.5배↑, 현재가 > EMA9
                cond_rsi = rsi < rsi_thresh
                cond_vol = volume_ratio >= vol_min
                cond_ema = (ema9 is not None) and (current_price > ema9)

                if cond_rsi and cond_vol and cond_ema:
                    score = (rsi_thresh - rsi) * volume_ratio
                    reason = (
                        f"스캘핑 매수: RSI={rsi:.1f}(<{rsi_thresh}), "
                        f"거래량={volume_ratio:.1f}배(>{vol_min}x), "
                        f"현재가{current_price:,.0f}>EMA9({ema9:,.0f}). "
                        f"손절-{stop_pct}%/익절+{tp_pct}%"
                    )
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
                                "volume_ratio": volume_ratio,
                                "ema9": ema9,
                                "stop_pct": stop_pct,
                                "take_profit_pct": tp_pct,
                            },
                        )
                    )
                    logger.info(f"[Scalping] {symbol} 매수 신호 score={score:.2f} RSI={rsi:.1f}")

            except Exception as e:
                logger.warning(f"[Scalping] {symbol} 신호 생성 오류: {e}")

        return signals
