from typing import Any

from loguru import logger

from core.strategy.base import BaseStrategy, Signal, SignalType, StrategyConfig
from core.strategy.ma_cross import MACrossStrategy
from core.strategy.rsi_strategy import RSIStrategy
from core.strategy.value_investing import ValueInvestingStrategy


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "value_investing": ValueInvestingStrategy,
    "ma_cross": MACrossStrategy,
    "rsi": RSIStrategy,
}


class StrategyManager:
    """
    전략 통합 관리자.
    여러 전략을 등록하고 순차 실행하여 신호를 통합한다.
    동일 종목에 복수 신호가 있을 경우 voting 방식으로 최종 신호를 결정한다.
    """

    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {}

    # ── 전략 등록 / 제거 ────────────────────────────────────────────────

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy
        logger.info(f"[StrategyManager] 전략 등록: {strategy.name}")

    def unregister(self, name: str) -> None:
        if name in self._strategies:
            del self._strategies[name]
            logger.info(f"[StrategyManager] 전략 제거: {name}")

    def enable(self, name: str) -> None:
        if name in self._strategies:
            self._strategies[name].config.enabled = True

    def disable(self, name: str) -> None:
        if name in self._strategies:
            self._strategies[name].config.enabled = False

    @classmethod
    def from_config(cls, configs: list[dict]) -> "StrategyManager":
        """
        설정 딕셔너리 리스트로 StrategyManager 인스턴스를 생성한다.
        config 예시:
            [
                {"type": "ma_cross", "name": "MA_20_60", "enabled": true,
                 "params": {"short_window": 20, "long_window": 60}},
                {"type": "rsi", "name": "RSI_14", "params": {"period": 14}},
            ]
        """
        manager = cls()
        for cfg in configs:
            strategy_type = cfg.get("type", "")
            if strategy_type not in STRATEGY_REGISTRY:
                logger.warning(f"[StrategyManager] 알 수 없는 전략 타입: {strategy_type}")
                continue

            s_config = StrategyConfig(
                name=cfg.get("name", strategy_type),
                enabled=cfg.get("enabled", True),
                params=cfg.get("params", {}),
            )
            strategy = STRATEGY_REGISTRY[strategy_type](config=s_config)
            manager.register(strategy)

        return manager

    # ── 신호 생성 ────────────────────────────────────────────────────────

    def run_all(self, data_map: dict[str, Any]) -> list[Signal]:
        """
        data_map: {"strategy_name": data} 또는 {"strategy_type": data} 형태.
                  전략 이름이 키에 없으면 모든 활성 전략에 동일 데이터를 전달한다.
        반환: 중복 제거 및 투표를 거친 최종 신호 리스트
        """
        all_signals: list[Signal] = []

        for name, strategy in self._strategies.items():
            if not strategy.config.enabled:
                continue

            data = data_map.get(name) or data_map.get("default")
            if data is None:
                logger.debug(f"[StrategyManager] {name}: 데이터 없음, 건너뜀")
                continue

            try:
                signals = strategy.generate_signals(data)
                all_signals.extend(signals)
                logger.debug(f"[StrategyManager] {name}: {len(signals)}개 신호")
            except Exception as exc:
                logger.error(f"[StrategyManager] {name} 실행 중 오류: {exc}")

        return self._aggregate(all_signals)

    def run_one(self, name: str, data: Any) -> list[Signal]:
        """특정 전략 하나만 실행한다."""
        if name not in self._strategies:
            logger.warning(f"[StrategyManager] 전략 없음: {name}")
            return []
        strategy = self._strategies[name]
        if not strategy.config.enabled:
            logger.warning(f"[StrategyManager] 비활성 전략: {name}")
            return []
        return strategy.generate_signals(data)

    # ── 신호 통합 (voting) ───────────────────────────────────────────────

    def _aggregate(self, signals: list[Signal]) -> list[Signal]:
        """
        동일 symbol에 대해 여러 전략의 신호를 집계한다.
        - BUY/SELL 중 다수결로 최종 타입 결정
        - 점수는 평균값 사용
        - HOLD는 BUY·SELL이 동수일 때 적용
        """
        from collections import defaultdict

        grouped: dict[str, list[Signal]] = defaultdict(list)
        for sig in signals:
            grouped[sig.symbol].append(sig)

        final: list[Signal] = []
        for symbol, sigs in grouped.items():
            buy_sigs = [s for s in sigs if s.signal_type == SignalType.BUY]
            sell_sigs = [s for s in sigs if s.signal_type == SignalType.SELL]

            if len(buy_sigs) > len(sell_sigs):
                winner = SignalType.BUY
                base_sigs = buy_sigs
            elif len(sell_sigs) > len(buy_sigs):
                winner = SignalType.SELL
                base_sigs = sell_sigs
            else:
                winner = SignalType.HOLD
                base_sigs = sigs

            avg_score = sum(s.score for s in base_sigs) / len(base_sigs)
            avg_price = sum(s.price for s in base_sigs) / len(base_sigs)
            strategies_used = ", ".join(s.strategy_name for s in base_sigs)

            final.append(
                Signal(
                    symbol=symbol,
                    signal_type=winner,
                    strategy_name=f"Aggregated({strategies_used})",
                    price=avg_price,
                    score=avg_score,
                    reason=f"투표 결과: BUY {len(buy_sigs)} vs SELL {len(sell_sigs)}",
                    metadata={
                        "buy_count": len(buy_sigs),
                        "sell_count": len(sell_sigs),
                        "strategies": [s.strategy_name for s in sigs],
                    },
                )
            )

        final.sort(key=lambda s: s.score, reverse=True)
        return final

    # ── 조회 ────────────────────────────────────────────────────────────

    def list_strategies(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "type": type(s).__name__,
                "enabled": s.config.enabled,
                "params": s.config.params,
            }
            for s in self._strategies.values()
        ]

    def get(self, name: str) -> BaseStrategy | None:
        return self._strategies.get(name)

    def __len__(self) -> int:
        return len(self._strategies)

    def __repr__(self) -> str:
        names = list(self._strategies.keys())
        return f"StrategyManager(strategies={names})"
