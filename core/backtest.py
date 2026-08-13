"""간단한 벡터화 백테스트 엔진.

RSI 기반 신호 생성 → 손절/익절 시뮬레이션.
"""
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

from core.indicators import compute_all


class Backtest:
    """전략 백테스트 클래스."""

    def run(
        self,
        df: pd.DataFrame,
        strategy_name: str,
        stop_pct: float,
        take_profit_pct: float,
    ) -> dict[str, Any]:
        """백테스트 실행.

        Args:
            df: OHLCV DataFrame (컬럼: open, high, low, close, volume, 소문자)
            strategy_name: "scalping" | "day_trading" | "swing" | "long_term"
            stop_pct: 손절 % (예: 2.0 → -2%)
            take_profit_pct: 익절 % (예: 4.0 → +4%)

        Returns:
            {
                "total_trades": int,
                "win_rate": float,          # 0~100%
                "profit_factor": float,
                "max_drawdown": float,
                "total_return": float,
                "sharpe_ratio": float,
                "trades": list[dict]        # 각 거래 내역
            }
        """
        empty_result: dict[str, Any] = {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "sharpe_ratio": 0.0,
            "trades": [],
        }

        try:
            if df is None or df.empty:
                return empty_result

            required = {"open", "high", "low", "close", "volume"}
            if not required.issubset(df.columns):
                logger.warning(f"[Backtest] 필수 컬럼 없음: {required - set(df.columns)}")
                return empty_result

            df = df.copy().reset_index(drop=True)

            # 전략별 신호 생성
            entry_indices = self._generate_entry_signals(df, strategy_name)
            if not entry_indices:
                return empty_result

            trades: list[dict[str, Any]] = []
            in_position = False
            entry_price = 0.0
            entry_idx = 0

            for idx in entry_indices:
                if in_position:
                    continue  # 이미 포지션 보유 중

                if idx >= len(df) - 1:
                    continue

                entry_price = float(df.iloc[idx]["close"])
                entry_idx = idx
                stop_price = entry_price * (1 - stop_pct / 100)
                target_price = entry_price * (1 + take_profit_pct / 100)
                in_position = True

                # 이후 봉 순회하며 손절/익절 체크
                exit_price = 0.0
                exit_idx = idx
                exit_reason = "기간종료"

                for j in range(idx + 1, len(df)):
                    row_low = float(df.iloc[j]["low"])
                    row_high = float(df.iloc[j]["high"])
                    row_close = float(df.iloc[j]["close"])

                    if row_low <= stop_price:
                        exit_price = stop_price
                        exit_idx = j
                        exit_reason = "손절"
                        break
                    elif row_high >= target_price:
                        exit_price = target_price
                        exit_idx = j
                        exit_reason = "익절"
                        break
                else:
                    exit_price = float(df.iloc[-1]["close"])
                    exit_idx = len(df) - 1

                pnl_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": exit_idx,
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "pnl_pct": round(pnl_pct, 4),
                    "exit_reason": exit_reason,
                })
                in_position = False

            if not trades:
                return empty_result

            return self._calc_stats(trades)

        except Exception as e:
            logger.error(f"[Backtest] 실행 오류: {e}")
            return empty_result

    # ── 신호 생성 ──────────────────────────────────────────────────────────

    def _generate_entry_signals(self, df: pd.DataFrame, strategy_name: str) -> list[int]:
        """전략별 매수 진입 인덱스 리스트 반환."""
        try:
            indicators = compute_all(df)
            rsi_series = self._calc_rsi_series(df["close"], 14)

            if strategy_name == "scalping":
                return self._scalping_signals(df, rsi_series)
            elif strategy_name == "day_trading":
                return self._day_trading_signals(df, rsi_series)
            elif strategy_name == "swing":
                return self._swing_signals(df, rsi_series)
            else:  # long_term (올랜도킴)
                return self._long_term_signals(df, rsi_series)
        except Exception as e:
            logger.warning(f"[Backtest] 신호 생성 오류: {e}")
            return []

    def _scalping_signals(self, df: pd.DataFrame, rsi: pd.Series) -> list[int]:
        """RSI<35, 거래량 급증, 단기 반등."""
        signals = []
        avg_vol = df["volume"].rolling(20).mean()
        ema9 = df["close"].ewm(span=9, adjust=False).mean()
        for i in range(30, len(df)):
            try:
                if (rsi.iloc[i] < 35
                        and df["volume"].iloc[i] >= avg_vol.iloc[i] * 1.5
                        and df["close"].iloc[i] > ema9.iloc[i]):
                    signals.append(i)
            except Exception:
                pass
        return signals

    def _day_trading_signals(self, df: pd.DataFrame, rsi: pd.Series) -> list[int]:
        """MACD 골든크로스, RSI 40~65, MA20 위."""
        signals = []
        ma20 = df["close"].rolling(20).mean()
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        for i in range(30, len(df)):
            try:
                prev_cross = macd_line.iloc[i - 1] <= signal_line.iloc[i - 1]
                curr_cross = macd_line.iloc[i] > signal_line.iloc[i]
                if (prev_cross and curr_cross
                        and 40 <= rsi.iloc[i] <= 65
                        and df["close"].iloc[i] > ma20.iloc[i]):
                    signals.append(i)
            except Exception:
                pass
        return signals

    def _swing_signals(self, df: pd.DataFrame, rsi: pd.Series) -> list[int]:
        """눌림목 + MA20 위 + RSI 40~60 + MACD>0."""
        signals = []
        ma20 = df["close"].rolling(20).mean()
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        for i in range(30, len(df)):
            try:
                # 눌림목: 최근 5봉 고점 대비 3~10% 하락 후 반등
                window = df["close"].iloc[max(0, i - 5):i + 1]
                peak = window.max()
                trough = window.min()
                current = df["close"].iloc[i]
                prev = df["close"].iloc[i - 1]
                drawdown = (peak - trough) / peak * 100 if peak > 0 else 0
                pullback = 3.0 <= drawdown <= 10.0 and current > prev

                if (pullback
                        and df["close"].iloc[i] > ma20.iloc[i]
                        and 40 <= rsi.iloc[i] <= 60
                        and macd_line.iloc[i] > 0):
                    signals.append(i)
            except Exception:
                pass
        return signals

    def _long_term_signals(self, df: pd.DataFrame, rsi: pd.Series) -> list[int]:
        """MA20 위 + 거래량 급증 (올랜도킴 기본)."""
        signals = []
        ma20 = df["close"].rolling(20).mean()
        avg_vol = df["volume"].rolling(20).mean()
        for i in range(25, len(df)):
            try:
                if (df["close"].iloc[i] > ma20.iloc[i]
                        and df["volume"].iloc[i] >= avg_vol.iloc[i] * 1.5):
                    signals.append(i)
            except Exception:
                pass
        return signals

    # ── 통계 계산 ──────────────────────────────────────────────────────────

    @staticmethod
    def _calc_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
        """승률, PF, MDD, 샤프 계산."""
        pnls = [t["pnl_pct"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_rate = len(wins) / len(pnls) * 100 if pnls else 0.0
        total_return = sum(pnls)

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # 최대 낙폭 (누적 수익 기준)
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        # 샤프 비율 (연간화 없이 단순 평균/표준편차)
        if len(pnls) > 1:
            mean_ret = np.mean(pnls)
            std_ret = np.std(pnls, ddof=1)
            sharpe = (mean_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 9999.0,
            "max_drawdown": round(max_drawdown, 4),
            "total_return": round(total_return, 4),
            "sharpe_ratio": round(sharpe, 4),
            "trades": trades,
        }

    @staticmethod
    def _calc_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
        rs = gain / loss.replace(0, float("nan"))
        return 100.0 - (100.0 / (1.0 + rs))
