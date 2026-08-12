from typing import Any

import pandas as pd
from loguru import logger

from core.strategy.base import BaseStrategy, Signal, SignalType, StrategyConfig


class MACrossStrategy(BaseStrategy):
    """
    이동평균선 교차 전략.
    단기 MA가 장기 MA를 상향 돌파(골든크로스) → BUY
    단기 MA가 장기 MA를 하향 돌파(데드크로스) → SELL
    """

    DEFAULT_PARAMS = {
        "short_window": 20,
        "long_window": 60,
        "price_col": "close",
    }

    def __init__(self, config: StrategyConfig | None = None):
        if config is None:
            config = StrategyConfig(
                name="MACross",
                params=self.DEFAULT_PARAMS.copy(),
            )
        else:
            for k, v in self.DEFAULT_PARAMS.items():
                config.params.setdefault(k, v)
        super().__init__(config)

    def validate_data(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        for symbol, df in data.items():
            if not isinstance(df, pd.DataFrame):
                return False
            price_col = self.get_param("price_col")
            if price_col not in df.columns:
                return False
            long_window = int(self.get_param("long_window"))
            if len(df) < long_window + 1:
                logger.warning(f"[{self.name}] {symbol}: 데이터 부족 ({len(df)} < {long_window + 1})")
                return False
        return True

    def generate_signals(self, data: Any) -> list[Signal]:
        """
        data: {symbol: pd.DataFrame} 형태.
              DataFrame 필수 컬럼: close (또는 price_col 파라미터 값)
        """
        if not data:
            return []

        signals: list[Signal] = []
        short_w = int(self.get_param("short_window"))
        long_w = int(self.get_param("long_window"))
        price_col = self.get_param("price_col")

        for symbol, df in data.items():
            if price_col not in df.columns:
                logger.warning(f"[{self.name}] {symbol}: '{price_col}' 컬럼 없음")
                continue
            if len(df) < long_w + 1:
                continue

            df = df.copy()
            df["ma_short"] = df[price_col].rolling(window=short_w).mean()
            df["ma_long"] = df[price_col].rolling(window=long_w).mean()
            df.dropna(inplace=True)

            if len(df) < 2:
                continue

            prev = df.iloc[-2]
            curr = df.iloc[-1]
            current_price = float(curr[price_col])

            prev_diff = prev["ma_short"] - prev["ma_long"]
            curr_diff = curr["ma_short"] - curr["ma_long"]

            if prev_diff <= 0 and curr_diff > 0:
                # 골든크로스
                signals.append(
                    Signal(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        strategy_name=self.name,
                        price=current_price,
                        score=abs(curr_diff / curr["ma_long"]) * 100,
                        reason=f"골든크로스: MA{short_w}({curr['ma_short']:.2f}) > MA{long_w}({curr['ma_long']:.2f})",
                        metadata={
                            "ma_short": round(curr["ma_short"], 4),
                            "ma_long": round(curr["ma_long"], 4),
                            "short_window": short_w,
                            "long_window": long_w,
                        },
                    )
                )
                logger.info(f"[{self.name}] {symbol} 골든크로스 감지")

            elif prev_diff >= 0 and curr_diff < 0:
                # 데드크로스
                signals.append(
                    Signal(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        strategy_name=self.name,
                        price=current_price,
                        score=abs(curr_diff / curr["ma_long"]) * 100,
                        reason=f"데드크로스: MA{short_w}({curr['ma_short']:.2f}) < MA{long_w}({curr['ma_long']:.2f})",
                        metadata={
                            "ma_short": round(curr["ma_short"], 4),
                            "ma_long": round(curr["ma_long"], 4),
                            "short_window": short_w,
                            "long_window": long_w,
                        },
                    )
                )
                logger.info(f"[{self.name}] {symbol} 데드크로스 감지")

        return signals

    def compute_ma(self, df: pd.DataFrame) -> pd.DataFrame:
        """이동평균 계산 결과를 포함한 DataFrame 반환."""
        short_w = int(self.get_param("short_window"))
        long_w = int(self.get_param("long_window"))
        price_col = self.get_param("price_col")

        df = df.copy()
        df[f"ma{short_w}"] = df[price_col].rolling(window=short_w).mean()
        df[f"ma{long_w}"] = df[price_col].rolling(window=long_w).mean()
        return df
