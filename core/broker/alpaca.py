from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests
from loguru import logger

from config.settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER
from core.broker.base import (
    AccountBalance,
    BaseBroker,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class AlpacaBroker(BaseBroker):
    """
    Alpaca Markets REST API v2 래퍼.
    https://docs.alpaca.markets/reference

    Paper trading / Live trading 모두 지원.
    alpaca-trade-api 패키지 대신 requests로 직접 구현하여 의존성을 최소화한다.
    """

    LIVE_BASE = "https://api.alpaca.markets"
    PAPER_BASE = "https://paper-api.alpaca.markets"
    DATA_BASE = "https://data.alpaca.markets"

    def __init__(
        self,
        api_key: str = ALPACA_API_KEY,
        secret_key: str = ALPACA_SECRET_KEY,
        paper: bool = ALPACA_PAPER,
    ):
        super().__init__(market="NASDAQ")
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.base_url = self.PAPER_BASE if paper else self.LIVE_BASE

        self._session = requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        })

    # ── 연결 ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            resp = self._session.get(f"{self.base_url}/v2/account", timeout=10)
            resp.raise_for_status()
            account = resp.json()
            self._connected = True
            mode = "Paper" if self.paper else "Live"
            logger.info(f"[Alpaca] 연결 성공 ({mode}) — status: {account.get('status')}")
            return True
        except Exception as exc:
            logger.error(f"[Alpaca] 연결 실패: {exc}")
            return False

    def disconnect(self) -> None:
        self._session.close()
        self._connected = False
        logger.info("[Alpaca] 연결 해제")

    # ── 시세 ────────────────────────────────────────────────────────────

    def get_current_price(self, symbol: str) -> float:
        url = f"{self.DATA_BASE}/v2/stocks/{symbol}/quotes/latest"
        resp = self._session.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        quote = data.get("quote", {})
        # bid/ask 중간값
        bid = float(quote.get("bp", 0))
        ask = float(quote.get("ap", 0))
        if bid > 0 and ask > 0:
            price = (bid + ask) / 2.0
        else:
            price = float(quote.get("bp", 0) or quote.get("ap", 0))
        logger.debug(f"[Alpaca] {symbol} 현재가: ${price:.4f}")
        return price

    def get_ohlcv(self, symbol: str, period: int = 60) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=period * 2)   # 주말 제외 여유분

        url = f"{self.DATA_BASE}/v2/stocks/{symbol}/bars"
        params = {
            "timeframe": "1Day",
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": period,
            "feed": "sip",
            "sort": "asc",
        }
        resp = self._session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        bars = data.get("bars", [])

        if not bars:
            return pd.DataFrame()

        rows = [
            {
                "date": pd.to_datetime(b["t"]),
                "open": float(b["o"]),
                "high": float(b["h"]),
                "low": float(b["l"]),
                "close": float(b["c"]),
                "volume": int(b["v"]),
                "vwap": float(b.get("vw", 0)),
            }
            for b in bars[-period:]
        ]
        df = pd.DataFrame(rows).set_index("date")
        return df

    # ── 계좌 ────────────────────────────────────────────────────────────

    def get_balance(self) -> AccountBalance:
        resp = self._session.get(f"{self.base_url}/v2/account", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return AccountBalance(
            cash=float(data.get("cash", 0)),
            total_equity=float(data.get("equity", 0)),
            buying_power=float(data.get("buying_power", 0)),
            currency="USD",
            raw=data,
        )

    def get_positions(self) -> list[Position]:
        resp = self._session.get(f"{self.base_url}/v2/positions", timeout=10)
        resp.raise_for_status()
        data = resp.json()

        positions: list[Position] = []
        for item in data:
            qty = int(float(item.get("qty", 0)))
            if qty <= 0:
                continue
            positions.append(
                Position(
                    symbol=item.get("symbol", ""),
                    quantity=qty,
                    avg_price=float(item.get("avg_entry_price", 0)),
                    current_price=float(item.get("current_price", 0)),
                    market="NASDAQ",
                )
            )
        return positions

    # ── 주문 ────────────────────────────────────────────────────────────

    def buy_market(self, symbol: str, quantity: int) -> Order:
        return self._place_order(symbol, OrderSide.BUY, OrderType.MARKET, quantity)

    def sell_market(self, symbol: str, quantity: int) -> Order:
        return self._place_order(symbol, OrderSide.SELL, OrderType.MARKET, quantity)

    def buy_limit(self, symbol: str, quantity: int, price: float) -> Order:
        return self._place_order(symbol, OrderSide.BUY, OrderType.LIMIT, quantity, price)

    def sell_limit(self, symbol: str, quantity: int, price: float) -> Order:
        return self._place_order(symbol, OrderSide.SELL, OrderType.LIMIT, quantity, price)

    def _place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: float = 0.0,
    ) -> Order:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "qty": str(quantity),
            "side": side.value.lower(),
            "type": order_type.value.lower(),
            "time_in_force": "day",
        }
        if order_type == OrderType.LIMIT:
            payload["limit_price"] = str(round(price, 2))

        resp = self._session.post(f"{self.base_url}/v2/orders", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        order = Order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            order_id=data.get("id", ""),
            status=self._map_status(data.get("status", "")),
            raw=data,
        )
        logger.info(f"[Alpaca] 주문 접수: {side.value} {symbol} {quantity}주 → {order.order_id}")
        return order

    def cancel_order(self, order_id: str) -> bool:
        resp = self._session.delete(
            f"{self.base_url}/v2/orders/{order_id}", timeout=10
        )
        success = resp.status_code in (200, 204)
        logger.info(f"[Alpaca] 주문 취소 {'성공' if success else '실패'}: {order_id}")
        return success

    def get_order(self, order_id: str) -> Order:
        resp = self._session.get(
            f"{self.base_url}/v2/orders/{order_id}", timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        return self._parse_order(data)

    def get_orders(self, status: OrderStatus | None = None) -> list[Order]:
        params: dict[str, str] = {"limit": "500", "direction": "desc"}
        if status is None:
            params["status"] = "all"
        elif status == OrderStatus.PENDING:
            params["status"] = "open"
        elif status == OrderStatus.FILLED:
            params["status"] = "closed"

        resp = self._session.get(f"{self.base_url}/v2/orders", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        orders = [self._parse_order(item) for item in data]
        if status is not None:
            orders = [o for o in orders if o.status == status]
        return orders

    # ── 유틸 ────────────────────────────────────────────────────────────

    @staticmethod
    def _map_status(raw: str) -> OrderStatus:
        mapping = {
            "new": OrderStatus.PENDING,
            "partially_filled": OrderStatus.PARTIAL,
            "filled": OrderStatus.FILLED,
            "done_for_day": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "pending_new": OrderStatus.PENDING,
            "accepted": OrderStatus.PENDING,
        }
        return mapping.get(raw, OrderStatus.PENDING)

    def _parse_order(self, data: dict) -> Order:
        side_str = data.get("side", "buy")
        side = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
        type_str = data.get("type", "market")
        o_type = OrderType.MARKET if type_str == "market" else OrderType.LIMIT

        filled_qty = int(float(data.get("filled_qty", 0)))
        filled_avg = float(data.get("filled_avg_price") or 0)

        return Order(
            symbol=data.get("symbol", ""),
            side=side,
            order_type=o_type,
            quantity=int(float(data.get("qty", 0))),
            price=float(data.get("limit_price") or 0),
            order_id=data.get("id", ""),
            status=self._map_status(data.get("status", "")),
            filled_qty=filled_qty,
            filled_price=filled_avg,
            raw=data,
        )
