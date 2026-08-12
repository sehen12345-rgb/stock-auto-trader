from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    symbol: str
    signal_type: SignalType
    strategy_name: str
    price: float
    score: float = 0.0
    quantity: int = 0
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def __repr__(self) -> str:
        return (
            f"Signal(symbol={self.symbol}, type={self.signal_type.value}, "
            f"strategy={self.strategy_name}, price={self.price:.2f}, score={self.score:.2f})"
        )


@dataclass
class StrategyConfig:
    name: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig(name=self.__class__.__name__)
        self.name = self.config.name

    @abstractmethod
    def generate_signals(self, data: Any) -> list[Signal]:
        """데이터를 받아 매수/매도 신호 리스트를 반환한다."""

    @abstractmethod
    def validate_data(self, data: Any) -> bool:
        """전략 실행에 필요한 데이터가 충분한지 검증한다."""

    def get_param(self, key: str, default: Any = None) -> Any:
        return self.config.params.get(key, default)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, enabled={self.config.enabled})"
