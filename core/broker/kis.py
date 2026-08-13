import json
import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
from loguru import logger

from config.settings import KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO, KIS_MOCK
from core.broker.base import (
    AccountBalance,
    BaseBroker,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class KISBroker(BaseBroker):
    """
    한국투자증권 KIS Developers REST API 래퍼.
    https://apiportal.koreainvestment.com

    모의투자(KIS_MOCK=True) / 실전투자 모두 지원.
    토큰은 발급 후 24시간 유효하며, 만료 10분 전 자동 갱신한다.
    """

    REAL_BASE = "https://openapi.koreainvestment.com:9443"
    MOCK_BASE = "https://openapivts.koreainvestment.com:29443"

    # TR-ID 매핑 (실전/모의)
    TR_PRICE = "FHKST01010100"                   # 주식 현재가
    TR_OHLCV = "FHKST03010100"                   # 주식 기간별 시세

    TR_BALANCE_REAL = "TTTC8434R"
    TR_BALANCE_MOCK = "VTTC8434R"

    TR_BUY_REAL = "TTTC0802U"
    TR_BUY_MOCK = "VTTC0802U"

    TR_SELL_REAL = "TTTC0801U"
    TR_SELL_MOCK = "VTTC0801U"

    TR_ORDER_CANCEL_REAL = "TTTC0803U"
    TR_ORDER_CANCEL_MOCK = "VTTC0803U"

    TR_ORDER_DETAIL_REAL = "TTTC8001R"
    TR_ORDER_DETAIL_MOCK = "VTTC8001R"

    TR_ORDER_LIST_REAL = "TTTC8036R"
    TR_ORDER_LIST_MOCK = "VTTC8036R"

    def __init__(
        self,
        app_key: str = KIS_APP_KEY,
        app_secret: str = KIS_APP_SECRET,
        account_no: str = KIS_ACCOUNT_NO,
        mock: bool = KIS_MOCK,
    ):
        super().__init__(market="KOSPI")
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no          # ex) "12345678-01"
        self.mock = mock
        self.base_url = self.MOCK_BASE if mock else self.REAL_BASE

        self._access_token: str = ""
        self._token_expires_at: datetime = datetime.min

        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json; charset=utf-8"})

    # ── 연결 ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._issue_token()
            self._connected = True
            logger.info(f"[KIS] 연결 성공 ({'모의' if self.mock else '실전'})")
            return True
        except Exception as exc:
            logger.error(f"[KIS] 연결 실패: {exc}")
            return False

    def disconnect(self) -> None:
        self._session.close()
        self._connected = False
        logger.info("[KIS] 연결 해제")

    # ── 토큰 ────────────────────────────────────────────────────────────

    _TOKEN_CACHE = "data/kis_token.json"

    def _load_cached_token(self) -> bool:
        """파일에 저장된 토큰 로드. 유효하면 True 반환."""
        try:
            if not os.path.exists(self._TOKEN_CACHE):
                return False
            with open(self._TOKEN_CACHE, "r") as f:
                cached = json.load(f)
            expires_at = datetime.fromisoformat(cached["expires_at"])
            if datetime.now() < expires_at - timedelta(minutes=10):
                self._access_token = cached["access_token"]
                self._token_expires_at = expires_at
                self._session.headers.update({"authorization": f"Bearer {self._access_token}"})
                logger.debug(f"[KIS] 캐시된 토큰 사용 (만료: {expires_at:%Y-%m-%d %H:%M})")
                return True
        except Exception:
            pass
        return False

    def _save_token_cache(self) -> None:
        os.makedirs("data", exist_ok=True)
        with open(self._TOKEN_CACHE, "w") as f:
            json.dump({
                "access_token": self._access_token,
                "expires_at": self._token_expires_at.isoformat(),
            }, f)

    def _issue_token(self) -> None:
        if self._load_cached_token():
            return
        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        resp = self._session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        self._session.headers.update({"authorization": f"Bearer {self._access_token}"})
        self._save_token_cache()
        logger.debug(f"[KIS] 토큰 발급 완료 (만료: {self._token_expires_at:%Y-%m-%d %H:%M})")

    def _ensure_token(self) -> None:
        if datetime.now() >= self._token_expires_at - timedelta(minutes=10):
            logger.info("[KIS] 토큰 갱신 중...")
            # 캐시 삭제 후 재발급
            if os.path.exists(self._TOKEN_CACHE):
                os.remove(self._TOKEN_CACHE)
            self._issue_token()

    def _headers(self, tr_id: str, extra: dict | None = None) -> dict:
        self._ensure_token()
        h = {
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        if extra:
            h.update(extra)
        return h

    # ── 시세 ────────────────────────────────────────────────────────────

    def get_current_price(self, symbol: str) -> float:
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}
        resp = self._session.get(
            url, params=params, headers=self._headers(self.TR_PRICE), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {})
        price = float(output.get("stck_prpr", 0))
        logger.debug(f"[KIS] {symbol} 현재가: {price:,.0f}원")
        return price

    def get_ohlcv(self, symbol: str, period: int = 60) -> pd.DataFrame:
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
        }
        resp = self._session.get(
            url, params=params, headers=self._headers(self.TR_PRICE), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        output2 = data.get("output2", [])

        rows = []
        for item in output2[:period]:
            rows.append({
                "date": item.get("stck_bsop_date", ""),
                "open": float(item.get("stck_oprc", 0)),
                "high": float(item.get("stck_hgpr", 0)),
                "low": float(item.get("stck_lwpr", 0)),
                "close": float(item.get("stck_clpr", 0)),
                "volume": int(item.get("acml_vol", 0)),
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            df.sort_values("date", inplace=True)
            df.set_index("date", inplace=True)
        return df

    # ── 계좌 ────────────────────────────────────────────────────────────

    def get_balance(self) -> AccountBalance:
        tr_id = self.TR_BALANCE_MOCK if self.mock else self.TR_BALANCE_REAL
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        acc_no, acc_suffix = self._split_account()
        params = {
            "CANO": acc_no,
            "ACNT_PRDT_CD": acc_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        resp = self._session.get(
            url, params=params, headers=self._headers(tr_id), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        output2 = data.get("output2", [{}])[0]

        return AccountBalance(
            cash=float(output2.get("dnca_tot_amt", 0)),
            total_equity=float(output2.get("tot_evlu_amt", 0)),
            buying_power=float(output2.get("prvs_rcdl_excc_amt", 0)),
            currency="KRW",
            raw=output2,
        )

    def get_positions(self) -> list[Position]:
        tr_id = self.TR_BALANCE_MOCK if self.mock else self.TR_BALANCE_REAL
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        acc_no, acc_suffix = self._split_account()
        params = {
            "CANO": acc_no,
            "ACNT_PRDT_CD": acc_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        resp = self._session.get(
            url, params=params, headers=self._headers(tr_id), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        output1 = data.get("output1", [])

        positions = []
        for item in output1:
            qty = int(item.get("hldg_qty", 0))
            if qty <= 0:
                continue
            positions.append(
                Position(
                    symbol=item.get("pdno", ""),
                    quantity=qty,
                    avg_price=float(item.get("pchs_avg_pric", 0)),
                    current_price=float(item.get("prpr", 0)),
                    market="KOSPI",
                )
            )
        return positions

    # ── 주문 ────────────────────────────────────────────────────────────

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
        if side == OrderSide.BUY:
            tr_id = self.TR_BUY_MOCK if self.mock else self.TR_BUY_REAL
        else:
            tr_id = self.TR_SELL_MOCK if self.mock else self.TR_SELL_REAL

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        acc_no, acc_suffix = self._split_account()

        # 주문 구분: 00=지정가, 01=시장가
        ord_dvsn = "01" if order_type == OrderType.MARKET else "00"

        payload = {
            "CANO": acc_no,
            "ACNT_PRDT_CD": acc_suffix,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(int(price)) if order_type == OrderType.LIMIT else "0",
        }

        resp = self._session.post(
            url,
            json=payload,
            headers=self._headers(tr_id, {"tr_cont": "N"}),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {})

        order = Order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            order_id=output.get("ODNO", ""),
            status=OrderStatus.PENDING,
            raw=output,
        )
        logger.info(f"[KIS] 주문 접수: {side.value} {symbol} {quantity}주 → 주문번호 {order.order_id}")
        return order

    def cancel_order(self, order_id: str) -> bool:
        tr_id = self.TR_ORDER_CANCEL_MOCK if self.mock else self.TR_ORDER_CANCEL_REAL
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
        acc_no, acc_suffix = self._split_account()

        payload = {
            "CANO": acc_no,
            "ACNT_PRDT_CD": acc_suffix,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_id,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",   # 02=취소
            "ORD_QTY": "0",
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }

        resp = self._session.post(
            url, json=payload, headers=self._headers(tr_id, {"tr_cont": "N"}), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        rt_cd = data.get("rt_cd", "9")
        success = rt_cd == "0"
        logger.info(f"[KIS] 주문 취소 {'성공' if success else '실패'}: {order_id}")
        return success

    def get_order(self, order_id: str) -> Order:
        orders = self.get_orders()
        for o in orders:
            if o.order_id == order_id:
                return o
        return Order(symbol="", side=OrderSide.BUY, order_type=OrderType.MARKET,
                     quantity=0, order_id=order_id, status=OrderStatus.REJECTED)

    def get_orders(self, status: OrderStatus | None = None) -> list[Order]:
        tr_id = self.TR_ORDER_LIST_MOCK if self.mock else self.TR_ORDER_LIST_REAL
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        acc_no, acc_suffix = self._split_account()
        today = datetime.now().strftime("%Y%m%d")

        params = {
            "CANO": acc_no,
            "ACNT_PRDT_CD": acc_suffix,
            "INQR_STRT_DT": today,
            "INQR_END_DT": today,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        resp = self._session.get(
            url, params=params, headers=self._headers(tr_id), timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        output1 = data.get("output1", [])

        orders: list[Order] = []
        for item in output1:
            filled_qty = int(item.get("tot_ccld_qty", 0))
            ord_qty = int(item.get("ord_qty", 0))

            if filled_qty >= ord_qty:
                o_status = OrderStatus.FILLED
            elif filled_qty > 0:
                o_status = OrderStatus.PARTIAL
            else:
                o_status = OrderStatus.PENDING

            side_code = item.get("sll_buy_dvsn_cd", "02")
            side = OrderSide.BUY if side_code == "02" else OrderSide.SELL

            ord_dvsn = item.get("ord_dvsn_cd", "01")
            o_type = OrderType.MARKET if ord_dvsn == "01" else OrderType.LIMIT

            o = Order(
                symbol=item.get("pdno", ""),
                side=side,
                order_type=o_type,
                quantity=ord_qty,
                price=float(item.get("ord_unpr", 0)),
                order_id=item.get("odno", ""),
                status=o_status,
                filled_qty=filled_qty,
                filled_price=float(item.get("avg_prvs", 0)),
                raw=item,
            )
            if status is None or o.status == status:
                orders.append(o)

        return orders

    # ── 유틸 ────────────────────────────────────────────────────────────

    def _split_account(self) -> tuple[str, str]:
        """계좌번호 '12345678-01' → ('12345678', '01')"""
        parts = self.account_no.replace("-", "")
        return parts[:8], parts[8:] if len(parts) > 8 else "01"
