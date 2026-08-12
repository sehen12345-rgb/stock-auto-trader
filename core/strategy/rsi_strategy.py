from typing import Any

import pandas as pd
from loguru import logger

from core.strategy.base import BaseStrategy, Signal, SignalType, StrategyConfig


class RSIStrategy(BaseStrategy):
    """
    RSI 과매수/과매도 전략.
    RSI < oversold_threshold → BUY (과매도 구간 반등 기대)
    RSI > overbought_threshold → SELL (과매수 구간 매도)
    """

    DEFAULT_PARAMS = {
        "period": 14,
        "oversold": 30.0,
        "overbought": 70.0,
        "price_col": "close",
        "confirm_bars": 1,   # 신호 확정을 위해 연속으로 조건 충족해야 하는 봉 수
    }

    def __init__(self, config: StrategyConfig | None = None):
        if config is None:
            config = StrategyConfig(
                name="RSI",
                params=self.DEFAULT_PARAMS.copy(),
            )
        else:
            for k, v in self.DEFAULT_PARAMS.items():
                config.params.setdefault(k, v)
        super().__init__(config)

    def validate_data(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        period = int(self.get_param("period"))
        price_col = self.get_param("price_col")
        for symbol, df in data.items():
            if not isinstance(df, pd.DataFrame):
                return False
            if price_col not in df.columns:
                return False
            if len(df) < period + 1:
                logger.warning(f"[{self.name}] {symbol}: 데이터 부족 ({len(df)} < {period + 1})")
                return False
        return True

    def generate_signals(self, data: Any) -> list[Signal]:
        """
        data: {symbol: pd.DataFrame}
              DataFrame 필수 컬럼: close (또는 price_col 파라미터 값)
        """
        if not data:
            return []

        signals: list[Signal] = []
        period = int(self.get_param("period"))
        oversold = float(self.get_param("oversold"))
        overbought = float(self.get_param("overbought"))
        price_col = self.get_param("price_col")
        confirm_bars = int(self.get_param("confirm_bars"))

        for symbol, df in data.items():
            if price_col not in df.columns:
                continue
            if len(df) < period + confirm_bars:
                continue

            df = df.copy()
            df["rsi"] = self._calc_rsi(df[price_col], period)
            df.dropna(subset=["rsi"], inplace=True)

            if len(df) < confirm_bars:
                continue

            recent = df.iloc[-confirm_bars:]
            current_price = float(df.iloc[-1][price_col])
            current_rsi = float(df.iloc[-1]["rsi"])

            # 과매도: 최근 confirm_bars 개 봉 모두 oversold 이하
            if all(recent["rsi"] <= oversold):
                # 이전 봉이 oversold 아래에서 올라오는 경우(전환점) 우선
                prev_rsi = float(df.iloc[-(confirm_bars + 1)]["rsi"]) if len(df) > confirm_bars else current_rsi
                score = (oversold - current_rsi)  # 얼마나 깊이 과매도인지

                signals.append(
                    Signal(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        strategy_name=self.name,
                        price=current_price,
                        score=score,
                        reason=f"RSI 과매도: {current_rsi:.1f} (기준 {oversold})",
                        metadata={
                            "rsi": round(current_rsi, 2),
                            "rsi_prev": round(prev_rsi, 2),
                            "period": period,
                            "oversold_threshold": oversold,
                        },
                    )
                )
                logger.info(f"[{self.name}] {symbol} 과매도 신호 RSI={current_rsi:.1f}")

            # 과매수: 최근 confirm_bars 개 봉 모두 overbought 이상
            elif all(recent["rsi"] >= overbought):
                score = current_rsi - overbought

                signals.append(
                    Signal(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        strategy_name=self.name,
                        price=current_price,
                        score=score,
                        reason=f"RSI 과매수: {current_rsi:.1f} (기준 {overbought})",
                        metadata={
                            "rsi": round(current_rsi, 2),
                            "period": period,
                            "overbought_threshold": overbought,
                        },
                    )
                )
                logger.info(f"[{self.name}] {symbol} 과매수 신호 RSI={current_rsi:.1f}")

        return signals

    @staticmethod
    def _calc_rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def compute_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """RSI 컬럼이 추가된 DataFrame 반환."""
        period = int(self.get_param("period"))
        price_col = self.get_param("price_col")
        df = df.copy()
        df["rsi"] = self._calc_rsi(df[price_col], period)
        return df
