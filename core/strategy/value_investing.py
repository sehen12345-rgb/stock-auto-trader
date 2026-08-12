from dataclasses import dataclass
from typing import Any

import pandas as pd
from loguru import logger

from core.strategy.base import BaseStrategy, Signal, SignalType, StrategyConfig


@dataclass
class FundamentalData:
    symbol: str
    current_price: float
    eps: float                      # 주당순이익
    bps: float                      # 주당순자산
    roe: float                      # 자기자본이익률 (%)
    debt_ratio: float               # 부채비율 (%)
    dividend_yield: float           # 배당수익률 (%)
    operating_profit_growth: list[float]   # 최근 3년 영업이익 성장률 (%)
    sector: str = ""
    name: str = ""

    @property
    def per(self) -> float:
        if self.eps <= 0:
            return float("inf")
        return self.current_price / self.eps

    @property
    def pbr(self) -> float:
        if self.bps <= 0:
            return float("inf")
        return self.current_price / self.bps


class ValueInvestingStrategy(BaseStrategy):
    """
    워렌 버핏 스타일 가치투자 전략.
    PER, PBR, ROE, 부채비율, 영업이익 성장률, 배당수익률을 종합 점수화하여 매수 신호를 생성한다.
    """

    DEFAULT_PARAMS = {
        "max_per": 15.0,
        "max_pbr": 1.5,
        "min_roe": 15.0,
        "max_debt_ratio": 50.0,
        "min_dividend_yield": 0.0,
        "top_n": 10,
        "min_score": 25.0,
    }

    def __init__(self, config: StrategyConfig | None = None):
        if config is None:
            config = StrategyConfig(
                name="ValueInvesting",
                params=self.DEFAULT_PARAMS.copy(),
            )
        else:
            for k, v in self.DEFAULT_PARAMS.items():
                config.params.setdefault(k, v)
        super().__init__(config)

    def validate_data(self, data: Any) -> bool:
        if not isinstance(data, list):
            return False
        if not data:
            return False
        return all(isinstance(d, FundamentalData) for d in data)

    def generate_signals(self, data: Any) -> list[Signal]:
        if not self.validate_data(data):
            logger.warning(f"[{self.name}] 유효하지 않은 데이터")
            return []

        scored = []
        for fd in data:
            result = self._score(fd)
            if result is not None:
                scored.append(result)

        scored.sort(key=lambda x: x[1], reverse=True)

        top_n = int(self.get_param("top_n"))
        min_score = float(self.get_param("min_score"))

        signals: list[Signal] = []
        for fd, score, breakdown in scored[:top_n]:
            if score < min_score:
                break
            signals.append(
                Signal(
                    symbol=fd.symbol,
                    signal_type=SignalType.BUY,
                    strategy_name=self.name,
                    price=fd.current_price,
                    score=score,
                    reason=self._format_reason(breakdown),
                    metadata={
                        "per": fd.per,
                        "pbr": fd.pbr,
                        "roe": fd.roe,
                        "debt_ratio": fd.debt_ratio,
                        "dividend_yield": fd.dividend_yield,
                        "score_breakdown": breakdown,
                    },
                )
            )

        logger.info(f"[{self.name}] {len(signals)}개 매수 신호 생성")
        return signals

    def _score(self, fd: FundamentalData) -> tuple[FundamentalData, float, dict] | None:
        """종목 점수를 계산한다. 필터 미통과 시 None 반환."""
        max_per = float(self.get_param("max_per"))
        max_pbr = float(self.get_param("max_pbr"))
        min_roe = float(self.get_param("min_roe"))
        max_debt = float(self.get_param("max_debt_ratio"))
        min_div = float(self.get_param("min_dividend_yield"))

        # 하드 필터 (미통과 시 제외)
        if fd.per > max_per:
            return None
        if fd.pbr > max_pbr:
            return None
        if fd.roe < min_roe:
            return None
        if fd.debt_ratio > max_debt:
            return None
        if fd.dividend_yield < min_div:
            return None
        if len(fd.operating_profit_growth) < 3:
            return None
        if not all(g > 0 for g in fd.operating_profit_growth[-3:]):
            return None

        breakdown: dict[str, float] = {}

        # PER 점수 (0~25): PER이 낮을수록 높은 점수
        per_score = max(0.0, 25.0 * (1.0 - fd.per / max_per))
        breakdown["per"] = round(per_score, 2)

        # PBR 점수 (0~20)
        pbr_score = max(0.0, 20.0 * (1.0 - fd.pbr / max_pbr))
        breakdown["pbr"] = round(pbr_score, 2)

        # ROE 점수 (0~25): 15% 기준, 최대 30% 이상이면 만점
        roe_score = min(25.0, 25.0 * (fd.roe - min_roe) / (30.0 - min_roe))
        breakdown["roe"] = round(roe_score, 2)

        # 부채비율 점수 (0~15): 낮을수록 높은 점수
        debt_score = max(0.0, 15.0 * (1.0 - fd.debt_ratio / max_debt))
        breakdown["debt_ratio"] = round(debt_score, 2)

        # 영업이익 성장률 점수 (0~10): 3년 평균 성장률
        avg_growth = sum(fd.operating_profit_growth[-3:]) / 3.0
        growth_score = min(10.0, avg_growth / 10.0 * 10.0)
        breakdown["op_growth"] = round(growth_score, 2)

        # 배당수익률 점수 (0~5)
        div_score = min(5.0, fd.dividend_yield)
        breakdown["dividend"] = round(div_score, 2)

        total = per_score + pbr_score + roe_score + debt_score + growth_score + div_score
        return fd, round(total, 2), breakdown

    @staticmethod
    def _format_reason(breakdown: dict) -> str:
        parts = [f"{k}:{v:.1f}" for k, v in breakdown.items()]
        return "Score breakdown — " + ", ".join(parts)

    def screen_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        DataFrame으로 종목 스크리닝 결과를 반환하는 편의 메서드.
        필수 컬럼: symbol, current_price, eps, bps, roe, debt_ratio,
                   dividend_yield, op_growth_y1, op_growth_y2, op_growth_y3
        """
        required = ["symbol", "current_price", "eps", "bps", "roe",
                    "debt_ratio", "dividend_yield",
                    "op_growth_y1", "op_growth_y2", "op_growth_y3"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"DataFrame에 필수 컬럼 없음: {missing}")

        fundamentals: list[FundamentalData] = []
        for _, row in df.iterrows():
            fundamentals.append(
                FundamentalData(
                    symbol=str(row["symbol"]),
                    current_price=float(row["current_price"]),
                    eps=float(row["eps"]),
                    bps=float(row["bps"]),
                    roe=float(row["roe"]),
                    debt_ratio=float(row["debt_ratio"]),
                    dividend_yield=float(row["dividend_yield"]),
                    operating_profit_growth=[
                        float(row["op_growth_y1"]),
                        float(row["op_growth_y2"]),
                        float(row["op_growth_y3"]),
                    ],
                    name=str(row.get("name", "")),
                    sector=str(row.get("sector", "")),
                )
            )

        signals = self.generate_signals(fundamentals)
        if not signals:
            return pd.DataFrame()

        records = []
        for sig in signals:
            row = {
                "symbol": sig.symbol,
                "score": sig.score,
                "price": sig.price,
                "reason": sig.reason,
            }
            row.update(sig.metadata.get("score_breakdown", {}))
            records.append(row)

        return pd.DataFrame(records).sort_values("score", ascending=False).reset_index(drop=True)
