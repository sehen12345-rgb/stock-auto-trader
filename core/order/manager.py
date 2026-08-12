from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from loguru import logger

from core.broker.base import BaseBroker, Order, OrderSide, OrderStatus, OrderType, Position
from core.strategy.base import Signal, SignalType


@dataclass
class RiskConfig:
    stop_loss_pct: float = 5.0        # 손절 기준 (%)
    take_profit_pct: float = 10.0     # 익절 기준 (%)
    max_daily_loss: float = 100_000   # 일 최대 손실 한도 (KRW 또는 USD)
    max_position_size: float = 0.2    # 종목당 최대 비중 (계좌 대비 %)
    max_positions: int = 10           # 최대 보유 종목 수


@dataclass
class PositionState:
    symbol: str
    quantity: int
    avg_price: float
    broker_market: str
    open_at: datetime = field(default_factory=datetime.now)
    stop_price: float = 0.0
    target_price: float = 0.0
    peak_price: float = 0.0          # trailing stop 계산용


class OrderManager:
    """
    주문 관리자.
    - 신호(Signal)를 받아 브로커에 실제 주문 전달
    - 손절/익절 자동 감시 및 실행
    - 일 손실 한도 초과 시 신규 주문 차단
    - 포지션 상태 추적
    """

    def __init__(self, risk: RiskConfig | None = None):
        self.risk = risk or RiskConfig()
        self._brokers: dict[str, BaseBroker] = {}           # market → broker
        self._positions: dict[str, PositionState] = {}      # symbol → state
        self._daily_pnl: float = 0.0
        self._pnl_date: date = date.today()
        self._orders: list[Order] = []

    # ── 브로커 등록 ──────────────────────────────────────────────────────

    def register_broker(self, broker: BaseBroker) -> None:
        self._brokers[broker.market] = broker
        logger.info(f"[OrderManager] 브로커 등록: {broker.market}")

    def get_broker(self, market: str) -> BaseBroker | None:
        return self._brokers.get(market)

    # ── 신호 → 주문 ──────────────────────────────────────────────────────

    def process_signal(self, signal: Signal, market: str = "KOSPI") -> Order | None:
        """전략 신호를 받아 주문을 실행한다."""
        if not self._check_daily_loss_limit():
            logger.warning(f"[OrderManager] 일 손실 한도 초과, 주문 차단: {signal.symbol}")
            return None

        broker = self._brokers.get(market)
        if broker is None:
            logger.error(f"[OrderManager] 브로커 없음: {market}")
            return None

        if signal.signal_type == SignalType.BUY:
            return self._execute_buy(signal, broker, market)
        elif signal.signal_type == SignalType.SELL:
            return self._execute_sell(signal, broker)
        else:
            logger.debug(f"[OrderManager] HOLD 신호 무시: {signal.symbol}")
            return None

    def _execute_buy(self, signal: Signal, broker: BaseBroker, market: str) -> Order | None:
        if signal.symbol in self._positions:
            logger.info(f"[OrderManager] 이미 보유 중인 종목: {signal.symbol}")
            return None

        if len(self._positions) >= self.risk.max_positions:
            logger.warning(f"[OrderManager] 최대 보유 종목 수 초과: {self.risk.max_positions}")
            return None

        quantity = signal.quantity
        if quantity <= 0:
            quantity = self._calc_quantity(signal.price, broker, market)
        if quantity <= 0:
            logger.warning(f"[OrderManager] 매수 수량 0: {signal.symbol}")
            return None

        order = broker.buy_market(signal.symbol, quantity)
        self._orders.append(order)

        if order.status not in (OrderStatus.REJECTED,):
            price = signal.price
            stop_price = price * (1 - self.risk.stop_loss_pct / 100)
            target_price = price * (1 + self.risk.take_profit_pct / 100)

            self._positions[signal.symbol] = PositionState(
                symbol=signal.symbol,
                quantity=quantity,
                avg_price=price,
                broker_market=market,
                stop_price=stop_price,
                target_price=target_price,
                peak_price=price,
            )
            logger.info(
                f"[OrderManager] 매수 완료: {signal.symbol} {quantity}주 "
                f"손절={stop_price:.2f} 익절={target_price:.2f}"
            )

        return order

    def _execute_sell(self, signal: Signal, broker: BaseBroker) -> Order | None:
        state = self._positions.get(signal.symbol)
        if state is None:
            logger.warning(f"[OrderManager] 보유하지 않은 종목: {signal.symbol}")
            return None

        order = broker.sell_market(signal.symbol, state.quantity)
        self._orders.append(order)

        if order.status not in (OrderStatus.REJECTED,):
            pnl = (signal.price - state.avg_price) * state.quantity
            self._record_pnl(pnl)
            del self._positions[signal.symbol]
            logger.info(
                f"[OrderManager] 매도 완료: {signal.symbol} PnL={pnl:+.2f}"
            )

        return order

    # ── 손절/익절 감시 ────────────────────────────────────────────────────

    def check_stop_conditions(self) -> list[Order]:
        """보유 포지션에 대해 손절/익절 조건을 점검하고 필요 시 주문한다."""
        triggered: list[Order] = []

        for symbol, state in list(self._positions.items()):
            broker = self._brokers.get(state.broker_market)
            if broker is None:
                continue

            try:
                current_price = broker.get_current_price(symbol)
            except Exception as exc:
                logger.error(f"[OrderManager] {symbol} 가격 조회 실패: {exc}")
                continue

            # trailing stop: 신고가 갱신 시 stop 가격 상향
            if current_price > state.peak_price:
                state.peak_price = current_price
                state.stop_price = current_price * (1 - self.risk.stop_loss_pct / 100)

            reason = None
            if current_price <= state.stop_price:
                reason = f"손절: {current_price:.2f} <= {state.stop_price:.2f}"
            elif current_price >= state.target_price:
                reason = f"익절: {current_price:.2f} >= {state.target_price:.2f}"

            if reason:
                logger.info(f"[OrderManager] {symbol} {reason} → 매도 실행")
                order = broker.sell_market(symbol, state.quantity)
                self._orders.append(order)

                pnl = (current_price - state.avg_price) * state.quantity
                self._record_pnl(pnl)
                del self._positions[symbol]
                triggered.append(order)

        return triggered

    # ── 포지션 조회 ──────────────────────────────────────────────────────

    def get_positions(self) -> dict[str, PositionState]:
        return dict(self._positions)

    def sync_positions(self) -> None:
        """브로커 실제 잔고와 내부 포지션 상태를 동기화한다."""
        for market, broker in self._brokers.items():
            try:
                real_positions: list[Position] = broker.get_positions()
                real_symbols = {p.symbol for p in real_positions}

                # 브로커에서 사라진 포지션 제거
                for symbol in list(self._positions.keys()):
                    state = self._positions[symbol]
                    if state.broker_market == market and symbol not in real_symbols:
                        logger.warning(f"[OrderManager] 포지션 동기화: {symbol} 제거")
                        del self._positions[symbol]

                # 새로 추가된 포지션 등록
                for pos in real_positions:
                    if pos.symbol not in self._positions:
                        stop = pos.avg_price * (1 - self.risk.stop_loss_pct / 100)
                        target = pos.avg_price * (1 + self.risk.take_profit_pct / 100)
                        self._positions[pos.symbol] = PositionState(
                            symbol=pos.symbol,
                            quantity=pos.quantity,
                            avg_price=pos.avg_price,
                            broker_market=market,
                            stop_price=stop,
                            target_price=target,
                            peak_price=pos.current_price,
                        )
                        logger.info(f"[OrderManager] 포지션 동기화: {pos.symbol} 추가")

            except Exception as exc:
                logger.error(f"[OrderManager] {market} 동기화 실패: {exc}")

    # ── 손실 한도 ────────────────────────────────────────────────────────

    def _check_daily_loss_limit(self) -> bool:
        today = date.today()
        if today != self._pnl_date:
            self._daily_pnl = 0.0
            self._pnl_date = today
        return self._daily_pnl > -abs(self.risk.max_daily_loss)

    def _record_pnl(self, pnl: float) -> None:
        self._daily_pnl += pnl
        logger.info(f"[OrderManager] 일 누적 PnL: {self._daily_pnl:+.2f}")
        if not self._check_daily_loss_limit():
            logger.warning(
                f"[OrderManager] ⚠ 일 손실 한도 도달 ({self._daily_pnl:.2f} / "
                f"-{self.risk.max_daily_loss:.2f})"
            )

    # ── 수량 계산 ────────────────────────────────────────────────────────

    def _calc_quantity(self, price: float, broker: BaseBroker, market: str) -> int:
        """계좌 대비 최대 포지션 비중으로 매수 수량을 계산한다."""
        try:
            balance = broker.get_balance()
            max_amount = balance.buying_power * (self.risk.max_position_size / 100)
            qty = int(max_amount // price)
            return max(0, qty)
        except Exception as exc:
            logger.error(f"[OrderManager] 수량 계산 실패: {exc}")
            return 0

    # ── 주문 이력 ────────────────────────────────────────────────────────

    def get_order_history(self) -> list[Order]:
        return list(self._orders)

    def get_daily_pnl(self) -> float:
        return self._daily_pnl

    def __repr__(self) -> str:
        return (
            f"OrderManager(positions={len(self._positions)}, "
            f"daily_pnl={self._daily_pnl:+.2f}, "
            f"brokers={list(self._brokers.keys())})"
        )
