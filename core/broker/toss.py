import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
from loguru import logger

from config.settings import (
    TOSS_APP_KEY,
    TOSS_APP_SECRET,
    TOSS_ACCOUNT_NO,
    TOSS_MOCK,
)
from core.broker.base import (
    AccountBalance,
    BaseBroker,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)

# ────────────────────────────────────────────────────────────────────────────
# NOTE: 토스증권 Open API 엔드포인트는 공식 문서(https://corp.tossinvest.com/ko/open-api)
#       에서 발급받은 실제 경로로 교체하세요.
#       현재는 OAuth2 표준 패턴 + 토스증권 API 구조 기반으로 작성되었습니다.
# ────────────────────────────────────────────────────────────────────────────


class TossBroker(BaseBroker):
    """
    토스증권 Open API REST 래퍼.
    https://corp.tossinvest.com/ko/open-api

    - OAuth2 Client Credentials 방식 토큰 인증
    - 실전(TOSS_MOCK=false) / 샌드박스(TOSS_MOCK=true) 분기
    - KIS 브로커와 동일한 BaseBroker 인터페이스
    """

    REAL_BASE = "https://openapi.tossinvest.com"
    MOCK_BASE = "https://sandbox.tossinvest.com"

    def __init__(
        self,
        app_key: str = TOSS_APP_KEY,
        app_secret: str = TOSS_APP_SECRET,
        account_no: str = TOSS_ACCOUNT_NO,
        mock: bool = TOSS_MOCK,
    ):
        super().__init__(market="KOSPI")
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.mock = mock
        self.base_url = self.MOCK_BASE if mock else self.REAL_BASE

        self._access_token: str = ""
        self._token_expires_at: datetime = datetime.min

        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ── 연결 ────────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._issue_token()
            self._connected = True
            mode = "샌드박스" if self.mock else "실전"
            logger.info(f"[Toss] 연결 성공 ({mode})")
            return True
        except Exception as exc:
            logger.error(f"[Toss] 연결 실패: {exc}")
            return False

    def disconnect(self) -> None:
        self._session.close()
        self._connected = False
        logger.info("[Toss] 연결 해제")

    # ── 토큰 ────────────────────────────────────────────────────────────────

    def _issue_token(self) -> None:
        """OAuth2 Client Credentials 방식으로 Access Token 발급."""
        url = f"{self.base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.app_key,
            "client_secret": self.app_secret,
        }
        resp = self._session.post(url, json=payload, timeout=10)
        self._raise_for_status(resp, context="토큰 발급")

        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        self._session.headers.update({"Authorization": f"Bearer {self._access_token}"})
        logger.debug(f"[Toss] 토큰 발급 완료 (만료: {self._token_expires_at:%Y-%m-%d %H:%M})")

    def _ensure_token(self) -> None:
        """만료 10분 전 자동 갱신."""
        if datetime.now() >= self._token_expires_at - timedelta(minutes=10):
            logger.info("[Toss] 토큰 갱신 중...")
            self._issue_token()

    # ── 에러 처리 ────────────────────────────────────────────────────────────

    def _raise_for_status(self, resp: requests.Response, context: str = "") -> None:
        """HTTP 에러 및 API 에러코드 통합 처리."""
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass
            code = body.get("code", resp.status_code)
            msg = body.get("message", str(exc))
            logger.error(f"[Toss] {context} 오류 [{code}]: {msg}")
            raise RuntimeError(f"[Toss] {context} 실패 ({code}): {msg}") from exc

        # 200 OK지만 API 레벨 오류 처리
        try:
            body = resp.json()
            if isinstance(body, dict):
                error_code = body.get("errorCode") or body.get("error_code")
                if error_code:
                    msg = body.get("message", "알 수 없는 오류")
                    logger.error(f"[Toss] {context} API 오류 [{error_code}]: {msg}")
                    raise RuntimeError(f"[Toss] {context} API 오류 ({error_code}): {msg}")
        except (ValueError, RuntimeError):
            raise
        except Exception:
            pass

    def _get(self, path: str, params: dict | None = None) -> Any:
        self._ensure_token()
        resp = self._session.get(
            f"{self.base_url}{path}", params=params, timeout=10
        )
        self._raise_for_status(resp, context=f"GET {path}")
        return resp.json()

    def _post(self, path: str, payload: dict) -> Any:
        self._ensure_token()
        resp = self._session.post(
            f"{self.base_url}{path}", json=payload, timeout=10
        )
        self._raise_for_status(resp, context=f"POST {path}")
        return resp.json()

    def _delete(self, path: str, payload: dict | None = None) -> Any:
        self._ensure_token()
        resp = self._session.delete(
            f"{self.base_url}{path}", json=payload, timeout=10
        )
        self._raise_for_status(resp, context=f"DELETE {path}")
        return resp.json()

    # ── 시세 ────────────────────────────────────────────────────────────────

    def get_current_price(self, symbol: str) -> float:
        """종목 현재가 조회."""
        data = self._get(f"/v1/domestic-stock/quotations/price/{symbol}")
        price = float(
            data.get("currentPrice")
            or data.get("price")
            or data.get("output", {}).get("currentPrice", 0)
        )
        logger.debug(f"[Toss] {symbol} 현재가: {price:,.0f}원")
        return price

    def get_ohlcv(self, symbol: str, period: int = 60) -> pd.DataFrame:
        """일봉 OHLCV 조회 (최근 period일)."""
        data = self._get(
            f"/v1/domestic-stock/quotations/daily-price/{symbol}",
            params={"period": "D", "count": period},
        )
        items = data if isinstance(data, list) else data.get("output", data.get("items", []))

        rows = []
        for item in items[:period]:
            rows.append({
                "date": item.get("date") or item.get("stck_bsop_date", ""),
                "open": float(item.get("open") or item.get("openPrice", 0)),
                "high": float(item.get("high") or item.get("highPrice", 0)),
                "low": float(item.get("low") or item.get("lowPrice", 0)),
                "close": float(item.get("close") or item.get("closePrice", 0)),
                "volume": int(item.get("volume") or item.get("tradingVolume", 0)),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df.sort_values("date", inplace=True)
            df.set_index("date", inplace=True)
        return df

    # ── 계좌 ────────────────────────────────────────────────────────────────

    def get_balance(self) -> AccountBalance:
        """계좌 잔고 및 주문 가능 금액 조회."""
        data = self._get(
            f"/v1/accounts/{self.account_no}/balance"
        )
        output = data if isinstance(data, dict) else data.get("output", {})

        cash = float(
            output.get("cash")
            or output.get("availableAmount")
            or output.get("dnca_tot_amt", 0)
        )
        total = float(
            output.get("totalAsset")
            or output.get("totalEquity")
            or output.get("tot_evlu_amt", 0)
        )
        buying_power = float(
            output.get("buyingPower")
            or output.get("ordAbleAmt")
            or output.get("prvs_rcdl_excc_amt", cash)
        )

        return AccountBalance(
            cash=cash,
            total_equity=total,
            buying_power=buying_power,
            currency="KRW",
            raw=output,
        )

    def get_positions(self) -> list[Position]:
        """보유 종목 조회."""
        data = self._get(f"/v1/accounts/{self.account_no}/positions")
        items = data if isinstance(data, list) else data.get("output", data.get("positions", []))

        positions: list[Position] = []
        for item in items:
            qty = int(item.get("quantity") or item.get("holdingQty") or item.get("hldg_qty", 0))
            if qty <= 0:
                continue
            positions.append(
                Position(
                    symbol=item.get("symbol") or item.get("stockCode") or item.get("pdno", ""),
                    quantity=qty,
                    avg_price=float(
                        item.get("avgPrice")
                        or item.get("averagePrice")
                        or item.get("pchs_avg_pric", 0)
                    ),
                    current_price=float(
                        item.get("currentPrice")
                        or item.get("price")
                        or item.get("prpr", 0)
                    ),
                    market="KOSPI",
                )
            )
        return positions

    # ── 주문 ────────────────────────────────────────────────────────────────

    def buy_market(self, symbol: str, quantity: int) -> Order:
        return self._place_order(symbol, OrderSide.BUY, OrderType.MARKET, quantity, 0)

    def sell_market(self, symbol: str, quantity: int) -> Order:
        return self._place_order(symbol, OrderSide.SELL, OrderType.MARKET, quantity, 0)

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
        price: float,
    ) -> Order:
        payload: dict[str, Any] = {
            "accountNumber": self.account_no,
            "symbol": symbol,
            "side": side.value,           # "BUY" / "SELL"
            "orderType": order_type.value, # "MARKET" / "LIMIT"
            "quantity": quantity,
        }
        if order_type == OrderType.LIMIT:
            payload["price"] = int(price)

        data = self._post("/v1/domestic-stock/orders", payload)
        output = data if isinstance(data, dict) else data.get("output", {})

        order_id = str(
            output.get("orderId")
            or output.get("orderNo")
            or output.get("ODNO", "")
        )
        order = Order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            order_id=order_id,
            status=OrderStatus.PENDING,
            raw=output,
        )
        logger.info(
            f"[Toss] 주문 접수: {side.value} {symbol} {quantity}주"
            f"{f' @ {price:,.0f}원' if order_type == OrderType.LIMIT else ' (시장가)'}"
            f" → 주문번호 {order_id}"
        )
        return order

    def cancel_order(self, order_id: str) -> bool:
        """주문 취소."""
        try:
            self._delete(
                f"/v1/domestic-stock/orders/{order_id}",
                payload={"accountNumber": self.account_no},
            )
            logger.info(f"[Toss] 주문 취소 성공: {order_id}")
            return True
        except Exception as exc:
            logger.warning(f"[Toss] 주문 취소 실패 {order_id}: {exc}")
            return False

    def get_order(self, order_id: str) -> Order:
        """단건 주문 상태 조회."""
        try:
            data = self._get(
                f"/v1/domestic-stock/orders/{order_id}",
                params={"accountNumber": self.account_no},
            )
            return self._parse_order(data)
        except Exception as exc:
            logger.warning(f"[Toss] 주문 조회 실패 {order_id}: {exc}")
            return Order(
                symbol="",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=0,
                order_id=order_id,
                status=OrderStatus.REJECTED,
            )

    def get_orders(self, status: OrderStatus | None = None) -> list[Order]:
        """당일 주문 체결 내역 조회."""
        today = datetime.now().strftime("%Y-%m-%d")
        data = self._get(
            f"/v1/accounts/{self.account_no}/orders",
            params={"date": today},
        )
        items = data if isinstance(data, list) else data.get("output", data.get("orders", []))

        orders: list[Order] = []
        for item in items:
            order = self._parse_order(item)
            if status is None or order.status == status:
                orders.append(order)
        return orders

    def _parse_order(self, item: dict) -> Order:
        """API 응답 dict → Order 변환."""
        filled_qty = int(
            item.get("filledQuantity")
            or item.get("executedQty")
            or item.get("tot_ccld_qty", 0)
        )
        total_qty = int(
            item.get("quantity")
            or item.get("orderQuantity")
            or item.get("ord_qty", 0)
        )

        raw_status = (
            item.get("status")
            or item.get("orderStatus")
            or ""
        ).upper()

        if raw_status in ("FILLED", "EXECUTED", "COMPLETE", "COMPLETED") or (
            total_qty > 0 and filled_qty >= total_qty
        ):
            o_status = OrderStatus.FILLED
        elif raw_status in ("CANCELLED", "CANCELED"):
            o_status = OrderStatus.CANCELLED
        elif raw_status in ("REJECTED",):
            o_status = OrderStatus.REJECTED
        elif filled_qty > 0:
            o_status = OrderStatus.PARTIAL
        else:
            o_status = OrderStatus.PENDING

        raw_side = (item.get("side") or item.get("orderSide") or "BUY").upper()
        side = OrderSide.BUY if raw_side in ("BUY", "02") else OrderSide.SELL

        raw_type = (item.get("orderType") or item.get("type") or "MARKET").upper()
        o_type = OrderType.LIMIT if raw_type == "LIMIT" else OrderType.MARKET

        return Order(
            symbol=item.get("symbol") or item.get("stockCode") or item.get("pdno", ""),
            side=side,
            order_type=o_type,
            quantity=total_qty,
            price=float(item.get("price") or item.get("orderPrice") or 0),
            order_id=str(item.get("orderId") or item.get("orderNo") or item.get("odno", "")),
            status=o_status,
            filled_qty=filled_qty,
            filled_price=float(
                item.get("avgFilledPrice")
                or item.get("avgExecutedPrice")
                or item.get("avg_prvs", 0)
            ),
            raw=item,
        )
