from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: float = 0.0           # 지정가 주문 시 사용
    order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: int = 0
    filled_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    raw: dict[str, Any] = field(default_factory=dict)

    def is_done(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)


@dataclass
class Position:
    symbol: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    market: str = ""

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_price == 0:
            return 0.0
        return (self.current_price - self.avg_price) / self.avg_price * 100.0


@dataclass
class AccountBalance:
    cash: float
    total_equity: float
    buying_power: float
    currency: str = "KRW"
    raw: dict[str, Any] = field(default_factory=dict)


class BaseBroker(ABC):
    def __init__(self, market: str):
        self.market = market
        self._connected = False

    # ── 연결 ────────────────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> bool:
        """API 토큰 발급 등 연결 초기화."""

    @abstractmethod
    def disconnect(self) -> None:
        """연결 해제."""

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── 시세 ────────────────────────────────────────────────────────────

    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""

    @abstractmethod
    def get_ohlcv(self, symbol: str, period: int = 60) -> Any:
        """OHLCV 데이터 조회. 반환: pd.DataFrame (columns: open, high, low, close, volume)."""

    # ── 계좌 ────────────────────────────────────────────────────────────

    @abstractmethod
    def get_balance(self) -> AccountBalance:
        """잔고 조회."""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """보유 종목 조회."""

    # ── 주문 ────────────────────────────────────────────────────────────

    @abstractmethod
    def buy_market(self, symbol: str, quantity: int) -> Order:
        """시장가 매수."""

    @abstractmethod
    def sell_market(self, symbol: str, quantity: int) -> Order:
        """시장가 매도."""

    @abstractmethod
    def buy_limit(self, symbol: str, quantity: int, price: float) -> Order:
        """지정가 매수."""

    @abstractmethod
    def sell_limit(self, symbol: str, quantity: int, price: float) -> Order:
        """지정가 매도."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """주문 취소."""

    @abstractmethod
    def get_order(self, order_id: str) -> Order:
        """주문 상태 조회."""

    @abstractmethod
    def get_orders(self, status: OrderStatus | None = None) -> list[Order]:
        """주문 목록 조회."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(market={self.market}, connected={self._connected})"
