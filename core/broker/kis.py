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

    # 해외주식 TR-ID
    TR_OVERSEAS_PRICE = "HHDFS00000300"        # 해외주식 현재가
    TR_OVERSEAS_OHLCV = "HHDFS76240000"        # 해외주식 일봉
    TR_OVERSEAS_BUY_REAL = "TTTT1002U"
    TR_OVERSEAS_BUY_MOCK = "VTTT1002U"
    TR_OVERSEAS_SELL_REAL = "TTTT1006U"
    TR_OVERSEAS_SELL_MOCK = "VTTT1006U"
    TR_OVERSEAS_BALANCE_REAL = "TTTS3012R"
    TR_OVERSEAS_BALANCE_MOCK = "VTTS3012R"

    # 클래스 공유 rate limiter — 모든 인스턴스 합산 (EGW00201 방지)
    _class_last_api_call: float = 0.0
    _class_api_interval: float = 1.05  # 초당 1회 미만
    # 해외주식 주문불가 텔레그램 알림 (중복 방지 — 세션당 1회만)
    _overseas_blocked_notified: bool = False

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
        self._token_expires_at: datetime = datetime(2000, 1, 1)  # 안전한 과거값 (datetime.min은 OverflowError 유발)

        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json; charset=utf-8"})

    # ── 연결 ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        for attempt in range(3):
            try:
                self._issue_token()
                self._connected = True
                logger.info(f"[KIS] 연결 성공 ({'모의' if self.mock else '실전'})")
                return True
            except Exception as exc:
                logger.warning(f"[KIS] 연결 실패 (시도 {attempt+1}/3): {exc}")
                if attempt < 2:
                    import time as _t
                    _t.sleep(3 * (attempt + 1))
        logger.error("[KIS] 연결 최종 실패 — 봇 계속 실행하되 주문 불가")
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

    def _rate_limit(self) -> None:
        """클래스 공유 rate limiter — EGW00201(초당 거래횟수 초과) 방지."""
        import time as _t
        now = _t.monotonic()
        wait = KISBroker._class_api_interval - (now - KISBroker._class_last_api_call)
        if wait > 0:
            _t.sleep(wait)
        KISBroker._class_last_api_call = _t.monotonic()

    def _headers(self, tr_id: str, extra: dict | None = None) -> dict:
        self._ensure_token()
        self._rate_limit()
        h = {
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }
        if extra:
            h.update(extra)
        return h

    # ── 환율 ────────────────────────────────────────────────────────────

    _usd_krw_cache: float = 0.0
    _usd_krw_ts: float = 0.0
    _USD_KRW_TTL: float = 600.0  # 10분 캐시

    def get_usd_krw_rate(self) -> float:
        """USD/KRW 실시간 환율 조회 (10분 캐시). 실패 시 환경변수 fallback."""
        import time as _t
        now = _t.monotonic()
        if KISBroker._usd_krw_cache > 0 and (now - KISBroker._usd_krw_ts) < KISBroker._USD_KRW_TTL:
            return KISBroker._usd_krw_cache
        try:
            # KIS 해외주식 현재가 API로 USD/KRW 환율 역산
            # 기준: USDKRW FX 시세 (TR: FHDFS00000300)
            url = f"{self.base_url}/uapi/overseas-price/v1/quotations/price"
            params = {"AUTH": "", "EXCD": "FX", "SYMB": "USDKRW"}
            resp = self._session.get(url, params=params,
                                     headers=self._headers("HHDFS00000300"), timeout=5)
            resp.raise_for_status()
            data = resp.json()
            rate = float(data.get("output", {}).get("last", 0))
            if rate > 0:
                KISBroker._usd_krw_cache = rate
                KISBroker._usd_krw_ts = now
                logger.debug(f"[KIS] USD/KRW 환율: {rate:,.2f}")
                return rate
        except Exception as e:
            logger.debug(f"[KIS] 환율 조회 실패, fallback 사용: {e}")
        fallback = float(os.getenv("USD_KRW_RATE", "1380"))
        KISBroker._usd_krw_cache = fallback
        KISBroker._usd_krw_ts = now
        return fallback

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
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=period * 2)).strftime("%Y%m%d")
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0",
            "FID_INPUT_DATE_1": start,
            "FID_INPUT_DATE_2": today,
        }
        resp = self._session.get(
            url, params=params, headers=self._headers(self.TR_OHLCV), timeout=10
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
        """국내 + 해외 잔고를 합산해 반환. 장 외 시간에도 최대한 조회한다."""
        acc_no, acc_suffix = self._split_account()

        # ── 국내 잔고 (KRW) ───────────────────────────────────────────────
        krw_cash = 0.0
        krw_equity = 0.0
        krw_buying_power = 0.0
        raw_domestic: dict = {}
        try:
            tr_id = self.TR_BALANCE_MOCK if self.mock else self.TR_BALANCE_REAL
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
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
            resp = self._session.get(url, params=params, headers=self._headers(tr_id), timeout=10)
            resp.raise_for_status()
            output2 = resp.json().get("output2", [{}])[0]
            krw_cash = float(output2.get("dnca_tot_amt", 0))
            krw_equity = float(output2.get("tot_evlu_amt", 0))
            krw_buying_power = float(output2.get("prvs_rcdl_excc_amt", 0))
            raw_domestic = output2
        except Exception as e:
            logger.debug(f"[KIS] 국내 잔고 조회 불가 (장 외 시간일 수 있음): {e}")

        # ── 해외 잔고 (USD → KRW 환산) ──────────────────────────────────
        usd_total = 0.0
        usd_available = 0.0  # 실제 주문가능 USD
        try:
            tr_id_os = self.TR_OVERSEAS_BALANCE_MOCK if self.mock else self.TR_OVERSEAS_BALANCE_REAL
            url_os = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"
            for excd in ("NAS", "NYS"):
                params_os = {
                    "CANO": acc_no,
                    "ACNT_PRDT_CD": acc_suffix,
                    "OVRS_EXCG_CD": excd,
                    "TR_CRCY_CD": "USD",
                    "CTX_AREA_FK200": "",
                    "CTX_AREA_NK200": "",
                }
                resp_os = self._session.get(url_os, params=params_os, headers=self._headers(tr_id_os), timeout=10)
                resp_os.raise_for_status()
                data_os = resp_os.json()
                output2_os = data_os.get("output2", {})
                if isinstance(output2_os, list):
                    output2_os = output2_os[0] if output2_os else {}
                # tot_evlu_pfls_amt: 총평가손익금액 (보유주식 평가)
                usd_total += float(output2_os.get("tot_evlu_pfls_amt", 0) or 0)
                # frcr_buy_amt_smtl1: 외화매수금액 합계 → 주문가능 가용 USD
                usd_available += float(output2_os.get("frcr_buy_amt_smtl1", 0) or 0)
        except Exception as e:
            logger.debug(f"[KIS] 해외 잔고 조회 불가: {e}")

        self._usd_available = usd_available  # 엔진에서 참조용

        usd_krw = self.get_usd_krw_rate()
        usd_in_krw = round(usd_total * usd_krw, 0)

        total_equity = (krw_equity or krw_cash) + usd_in_krw
        total_cash = krw_cash + usd_in_krw

        return AccountBalance(
            cash=total_cash,
            total_equity=total_equity,
            buying_power=krw_buying_power,
            currency="KRW",
            raw=raw_domestic,
        )

    def get_positions(self) -> list[Position]:
        """KOSPI 국내주식 보유 잔고 조회. 장 외 시간에는 빈 리스트 반환."""
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
        try:
            resp = self._session.get(
                url, params=params, headers=self._headers(tr_id), timeout=10
            )
            resp.raise_for_status()
        except Exception as e:
            # KIS는 장 외 시간에 domestic balance API가 500 반환 — 정상 동작
            logger.debug(f"[KIS] 국내주식 잔고 조회 불가 (장 외 시간일 수 있음): {e}")
            return []
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

    def get_overseas_positions(self) -> list[Position]:
        """NASDAQ/NYSE 해외주식 보유 잔고 조회 (TTTS3012R)."""
        tr_id = self.TR_OVERSEAS_BALANCE_MOCK if self.mock else self.TR_OVERSEAS_BALANCE_REAL
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance"
        acc_no, acc_suffix = self._split_account()

        positions = []
        # 거래소별로 조회 (NASD, NYSE)
        for excd in ("NAS", "NYS"):
            params = {
                "CANO": acc_no,
                "ACNT_PRDT_CD": acc_suffix,
                "OVRS_EXCG_CD": excd,
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            }
            try:
                resp = self._session.get(
                    url, params=params, headers=self._headers(tr_id), timeout=10
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("output1", []):
                    qty = int(item.get("ovrs_cblc_qty", 0))
                    if qty <= 0:
                        continue
                    positions.append(
                        Position(
                            symbol=item.get("ovrs_pdno", ""),
                            quantity=qty,
                            avg_price=float(item.get("pchs_avg_pric", 0)),
                            current_price=float(item.get("now_pric2", 0)),
                            market="NASDAQ",
                        )
                    )
            except Exception as e:
                logger.debug(f"[KIS] 해외주식 잔고 조회 불가 ({excd}): {e}")
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

    def buy_conditional(self, symbol: str, quantity: int, price: float) -> Order:
        """조건부지정가 매수: 지정가로 접수, 당일 미체결 시 장마감 직전 시장가 자동 전환."""
        return self._place_order(symbol, OrderSide.BUY, OrderType.CONDITIONAL, quantity, price)

    def sell_conditional(self, symbol: str, quantity: int, price: float) -> Order:
        """조건부지정가 매도."""
        return self._place_order(symbol, OrderSide.SELL, OrderType.CONDITIONAL, quantity, price)

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

        # 주문 구분
        # 00=지정가, 01=시장가, 03=조건부지정가(당일 미체결시 장마감 직전 시장가 자동전환)
        # 05=장전 시간외, 06=장후 시간외
        if order_type == OrderType.MARKET:
            ord_dvsn = "01"
        elif order_type == OrderType.CONDITIONAL:  # 조건부지정가
            ord_dvsn = "03"
        else:
            ord_dvsn = "00"  # 지정가

        payload = {
            "CANO": acc_no,
            "ACNT_PRDT_CD": acc_suffix,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(int(price)) if order_type != OrderType.MARKET else "0",
        }

        resp = self._session.post(
            url,
            json=payload,
            headers=self._headers(tr_id, {"tr_cont": "N"}),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rt_cd = data.get("rt_cd", "9")
        output = data.get("output", {})
        order_id = output.get("ODNO", "")

        if rt_cd != "0" or not order_id:
            msg = data.get("msg1", "") or data.get("msg_cd", "")
            logger.warning(f"[KIS] 주문 거부됨: {side.value} {symbol} rt_cd={rt_cd} msg={msg}")
            return Order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                order_id="",
                status=OrderStatus.REJECTED,
                raw=data,
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

    def get_order_history(self, days: int = 30) -> list[Order]:
        """당일 국내주식 체결 이력 조회 (KIS API는 당일만 지원)."""
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
        try:
            resp = self._session.get(
                url, params=params, headers=self._headers(tr_id), timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("rt_cd") != "0":
                logger.debug(f"[KIS] 당일 체결 이력 조회 실패: {data.get('msg1', '')}")
                return []
            output1 = data.get("output1") or []
            orders: list[Order] = []
            for item in output1:
                filled_qty = int(item.get("tot_ccld_qty", 0))
                if filled_qty <= 0:
                    continue
                side_code = item.get("sll_buy_dvsn_cd", "02")
                side = OrderSide.BUY if side_code == "02" else OrderSide.SELL
                ord_dvsn = item.get("ord_dvsn_cd", "01")
                o_type = OrderType.MARKET if ord_dvsn == "01" else OrderType.LIMIT
                ccld_time = item.get("ccld_cnfm_tm", "") or ""
                if len(ccld_time) >= 6:
                    created_at = f"{datetime.now().strftime('%Y-%m-%d')}T{ccld_time[:2]}:{ccld_time[2:4]}:{ccld_time[4:6]}"
                else:
                    created_at = datetime.now().strftime("%Y-%m-%dT09:00:00")
                o = Order(
                    symbol=item.get("pdno", ""),
                    side=side,
                    order_type=o_type,
                    quantity=int(item.get("ord_qty", 0)),
                    price=float(item.get("ord_unpr", 0)),
                    order_id=item.get("odno", ""),
                    status=OrderStatus.FILLED,
                    filled_qty=filled_qty,
                    filled_price=float(item.get("avg_prvs", 0)),
                    raw={**item, "_created_at": created_at, "_market": "KOSPI"},
                )
                orders.append(o)
            return orders
        except Exception as e:
            logger.debug(f"[KIS] 당일 체결 이력 조회 실패: {e}")
            return []

    def get_overseas_order_history(self) -> list[Order]:
        """당일 해외주식 체결 이력 조회 (NASD + NYSE)."""
        TR_REAL = "TTTS3035R"
        TR_MOCK = "VTTS3035R"
        tr_id = TR_MOCK if self.mock else TR_REAL
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-ccnl"
        acc_no, acc_suffix = self._split_account()
        today = datetime.now().strftime("%Y%m%d")

        orders: list[Order] = []
        for excd in ("NAS", "NYS"):
            params = {
                "CANO": acc_no,
                "ACNT_PRDT_CD": acc_suffix,
                "PDNO": "",
                "ORD_STRT_DT": today,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "00",
                "CCLD_NCCS_DVSN": "01",   # 체결만
                "OVRS_EXCG_CD": excd,
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": "",
            }
            try:
                resp = self._session.get(
                    url, params=params, headers=self._headers(tr_id), timeout=10
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("rt_cd") != "0":
                    logger.debug(f"[KIS] 해외 체결 이력 조회 실패 ({excd}): {data.get('msg1', '')}")
                    continue
                for item in (data.get("output") or []):
                    filled_qty = int(item.get("ft_ccld_qty", 0))
                    if filled_qty <= 0:
                        continue
                    side_code = item.get("sll_buy_dvsn_cd", "02")
                    side = OrderSide.BUY if side_code == "02" else OrderSide.SELL
                    ord_time = item.get("ord_tmd", "") or ""
                    if len(ord_time) >= 6:
                        created_at = (
                            f"{datetime.now().strftime('%Y-%m-%d')}"
                            f"T{ord_time[:2]}:{ord_time[2:4]}:{ord_time[4:6]}"
                        )
                    else:
                        created_at = datetime.now().strftime("%Y-%m-%dT22:30:00")
                    market = "NYSE" if excd == "NYSE" else "NASDAQ"
                    orders.append(Order(
                        symbol=item.get("pdno", ""),
                        side=side,
                        order_type=OrderType.MARKET,
                        quantity=int(item.get("ft_ord_qty", 0)),
                        price=float(item.get("ft_ccld_unpr3", 0)),
                        order_id=item.get("odno", ""),
                        status=OrderStatus.FILLED,
                        filled_qty=filled_qty,
                        filled_price=float(item.get("ft_ccld_unpr3", 0)),
                        raw={**item, "_created_at": created_at, "_market": market},
                    ))
            except Exception as e:
                logger.debug(f"[KIS] 해외 체결 이력 조회 실패 ({excd}): {e}")

        return orders

    # ── 해외주식 ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_overseas(symbol: str) -> bool:
        """알파벳으로만 구성된 티커는 해외주식으로 판단."""
        return symbol.isalpha()

    @staticmethod
    def _get_exchange(symbol: str) -> str:
        """티커별 거래소 코드 반환. 기본 NASDAQ."""
        nyse = {
            # 기존 NYSE
            "BRK", "JPM", "BAC", "GS", "MS", "WMT", "CAT", "GE", "GEV", "LLY", "UNH",
            # 추가: 관심 종목 중 NYSE 상장
            "TSM",   # TSMC ADR — NYSE
            "VRT",   # Vertiv — NYSE
            "DELL",  # Dell Technologies — NYSE
            "BE",    # Bloom Energy — NYSE
        }
        # DDOG, NVDA, AVGO, MU, AMD, MRVL, AMZN, MSFT, GOOG, TSLA, PLTR, IONQ → NASDAQ (기본값)
        # 가격조회 API: NAS / NYS 사용
        return "NYS" if symbol.upper() in nyse else "NAS"

    @staticmethod
    def _get_order_exchange(symbol: str) -> str:
        """주문 API용 거래소 코드. 가격조회(NAS)와 다름 — 주문은 NASD/NYSE 필요."""
        nyse = {
            "BRK", "JPM", "BAC", "GS", "MS", "WMT", "CAT", "GE", "GEV", "LLY", "UNH",
            "TSM", "VRT", "DELL", "BE",
        }
        return "NYSE" if symbol.upper() in nyse else "NASD"

    def get_overseas_price(self, symbol: str) -> float:
        excd = self._get_exchange(symbol)
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/price"
        params = {"AUTH": "", "EXCD": excd, "SYMB": symbol.upper()}
        try:
            resp = self._session.get(
                url, params=params,
                headers=self._headers(self.TR_OVERSEAS_PRICE), timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            price = float(data.get("output", {}).get("last", 0))
            logger.debug(f"[KIS] {symbol} 해외 현재가: ${price:.2f}")
            return price
        except Exception as e:
            logger.warning(f"[KIS] {symbol} 해외 시세 조회 실패: {e}")
            return 0.0

    def get_overseas_ohlcv(self, symbol: str, period: int = 60) -> pd.DataFrame:
        excd = self._get_exchange(symbol)
        url = f"{self.base_url}/uapi/overseas-price/v1/quotations/dailyprice"
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "AUTH": "", "EXCD": excd, "SYMB": symbol.upper(),
            "GUBN": "0", "BYMD": today, "MODP": "0",
        }
        try:
            resp = self._session.get(
                url, params=params,
                headers=self._headers(self.TR_OVERSEAS_OHLCV), timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            output2 = data.get("output2", [])
            rows = []
            for item in output2[:period]:
                rows.append({
                    "date": item.get("xymd", ""),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("clos", 0)),
                    "volume": int(item.get("tvol", 0)),
                })
            df = pd.DataFrame(rows)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
                df.sort_values("date", inplace=True)
                df.set_index("date", inplace=True)
            return df
        except Exception as e:
            logger.debug(f"[KIS] {symbol} 해외 OHLCV 조회 불가 (장 외 또는 미지원 종목): {e}")
            return pd.DataFrame()

    def buy_overseas_market(self, symbol: str, quantity: int) -> Order:
        return self._place_overseas_order(symbol, OrderSide.BUY, quantity)

    def sell_overseas_market(self, symbol: str, quantity: int) -> Order:
        return self._place_overseas_order(symbol, OrderSide.SELL, quantity)

    def _place_overseas_order(self, symbol: str, side: OrderSide, quantity: int) -> Order:
        tr_id = (self.TR_OVERSEAS_BUY_MOCK if self.mock else self.TR_OVERSEAS_BUY_REAL) \
            if side == OrderSide.BUY \
            else (self.TR_OVERSEAS_SELL_MOCK if self.mock else self.TR_OVERSEAS_SELL_REAL)
        url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
        acc_no, acc_suffix = self._split_account()
        excd = self._get_order_exchange(symbol)  # 주문용: NASD/NYSE
        price = self.get_overseas_price(symbol)
        payload = {
            "CANO": acc_no,
            "ACNT_PRDT_CD": acc_suffix,
            "OVRS_EXCG_CD": excd,
            "PDNO": symbol.upper(),
            "ORD_DVSN": "00",           # 지정가 (해외는 시장가 미지원)
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
        }
        try:
            resp = self._session.post(
                url, json=payload,
                headers=self._headers(tr_id, {"tr_cont": "N"}), timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            rt_cd = data.get("rt_cd", "9")
            output = data.get("output", {})
            order_id = output.get("ODNO", "")
            if rt_cd != "0" or not order_id:
                msg = data.get("msg1", "") or data.get("msg_cd", "")
                logger.warning(f"[KIS] 해외 주문 거부됨: {side.value} {symbol} rt_cd={rt_cd} msg={msg}")
                # 주문불가 → 해외주식 미신청 가능성 안내
                if rt_cd == "7" and "주문불가" in msg:
                    excd_cur = self._get_exchange(symbol)
                    exchange_name = "NYSE" if excd_cur == "NYS" else "NASDAQ"
                    logger.warning(
                        f"[KIS] {symbol} ({exchange_name}) 주문불가 — "
                        f"KIS 앱 > 해외주식 > {exchange_name} 거래 신청 필요. "
                        f"또는 해외주식 매매 서비스 미신청 상태일 수 있음. "
                        f"KIS 앱 > 메뉴 > 계좌관리 > 해외주식 서비스 신청 확인"
                    )
                    # 텔레그램 알림 (세션당 최초 1회만)
                    if not KISBroker._overseas_blocked_notified:
                        KISBroker._overseas_blocked_notified = True
                        try:
                            from notifications.telegram_bot import send_sync
                            send_sync(
                                f"⚠️ KIS 해외주식 주문 불가\n"
                                f"종목: {symbol} ({exchange_name})\n"
                                f"오류코드: rt_cd={rt_cd}\n\n"
                                f"📱 KIS 앱에서 해외주식 매매 서비스를 신청해주세요:\n"
                                f"KIS 앱 → 메뉴 → 계좌관리 → 해외주식 서비스 신청\n"
                                f"또는 KIS 앱 → 해외주식 → NASDAQ/NYSE 거래신청"
                            )
                        except Exception:
                            pass
                return Order(symbol=symbol, side=side, order_type=OrderType.LIMIT,
                             quantity=quantity, price=price, status=OrderStatus.REJECTED, raw=data)
            order = Order(
                symbol=symbol,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=price,
                order_id=order_id,
                status=OrderStatus.PENDING,
                raw=output,
            )
            logger.info(f"[KIS] 해외 주문: {side.value} {symbol} {quantity}주 @ ${price:.2f}")
            return order
        except Exception as e:
            logger.error(f"[KIS] 해외 주문 실패 {symbol}: {e}")
            return Order(symbol=symbol, side=side, order_type=OrderType.LIMIT,
                         quantity=quantity, price=price, status=OrderStatus.REJECTED)

    # ── 유틸 ────────────────────────────────────────────────────────────

    def _split_account(self) -> tuple[str, str]:
        """계좌번호 '12345678-01' → ('12345678', '01')"""
        parts = self.account_no.replace("-", "")
        return parts[:8], parts[8:] if len(parts) > 8 else "01"
