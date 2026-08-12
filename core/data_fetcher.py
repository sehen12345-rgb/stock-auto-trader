from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
from loguru import logger

from config.settings import KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO, KIS_MOCK


class DataFetcher:
    REAL_BASE = "https://openapi.koreainvestment.com:9443"
    MOCK_BASE = "https://openapivts.koreainvestment.com:29443"

    def __init__(self) -> None:
        self.base_url = self.MOCK_BASE if KIS_MOCK else self.REAL_BASE
        self._access_token = ""
        self._token_expires_at = datetime.min
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json; charset=utf-8"})

    def _ensure_token(self) -> None:
        if datetime.now() < self._token_expires_at - timedelta(minutes=10):
            return
        url = f"{self.base_url}/oauth2/tokenP"
        resp = self._session.post(url, json={
            "grant_type": "client_credentials",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = datetime.now() + timedelta(seconds=int(data.get("expires_in", 86400)))
        self._session.headers.update({"authorization": f"Bearer {self._access_token}"})

    def _get(self, path: str, tr_id: str, params: dict[str, str]) -> dict[str, Any]:
        self._ensure_token()
        headers = {
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": tr_id,
        }
        resp = self._session.get(
            f"{self.base_url}{path}",
            headers=headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch(self, ticker: str) -> dict[str, Any]:
        try:
            return self._fetch_sync(ticker)
        except Exception as e:
            logger.warning(f"[Fetcher] {ticker} KIS 조회 실패 (더미 반환): {e}")
            return self._dummy(ticker)

    def _fetch_sync(self, ticker: str) -> dict[str, Any]:
        price_data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
            },
        )
        output = price_data.get("output", {})
        current_price = float(output.get("stck_prpr", 0))
        volume = int(output.get("acml_vol", 0))

        ohlcv_data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            "FHKST03010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        outputs2 = ohlcv_data.get("output2", [])

        closes = [float(r.get("stck_clpr", 0)) for r in outputs2[:20] if r.get("stck_clpr")]
        volumes = [int(r.get("acml_vol", 0)) for r in outputs2[:20] if r.get("acml_vol")]
        highs = [float(r.get("stck_hgpr", 0)) for r in outputs2[:252] if r.get("stck_hgpr")]

        ma20 = round(sum(closes) / len(closes), 2) if closes else 0.0
        avg_volume_20 = int(sum(volumes) / len(volumes)) if volumes else 0
        week52_high = max(highs) if highs else 0.0

        return {
            "ticker": ticker,
            "current_price": current_price,
            "volume": volume,
            "ma20": ma20,
            "avg_volume_20": avg_volume_20,
            "week52_high": week52_high,
            "above_ma20": current_price > ma20 if ma20 > 0 else False,
            "volume_surge": volume >= avg_volume_20 * 1.5 if avg_volume_20 > 0 else False,
        }

    async def fetch_portfolio(self) -> dict[str, Any]:
        try:
            data = self._get(
                "/uapi/domestic-stock/v1/trading/inquire-balance",
                "VTTC8434R" if KIS_MOCK else "TTTC8434R",
                {
                    "CANO": KIS_ACCOUNT_NO.split("-")[0] if "-" in KIS_ACCOUNT_NO else KIS_ACCOUNT_NO,
                    "ACNT_PRDT_CD": KIS_ACCOUNT_NO.split("-")[1] if "-" in KIS_ACCOUNT_NO else "01",
                    "AFHR_FLPR_YN": "N",
                    "OFL_YN": "",
                    "INQR_DVSN": "02",
                    "UNPR_DVSN": "01",
                    "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N",
                    "PRCS_DVSN": "01",
                    "CTX_AREA_FK100": "",
                    "CTX_AREA_NK100": "",
                },
            )
            output2 = data.get("output2", [{}])[0] if data.get("output2") else {}
            total_value = float(output2.get("tot_evlu_amt", 0))
            cash = float(output2.get("dnca_tot_amt", 0))
            pnl_pct = float(output2.get("evlu_pfls_rt", 0))
            return {"total_value": total_value, "cash": cash, "return_pct": pnl_pct}
        except Exception as e:
            logger.warning(f"[Fetcher] 포트폴리오 조회 실패: {e}")
            return {"total_value": 0, "cash": 0, "return_pct": 0.0}

    @staticmethod
    def _dummy(ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "current_price": 0.0,
            "volume": 0,
            "ma20": 0.0,
            "avg_volume_20": 0,
            "week52_high": 0.0,
            "above_ma20": False,
            "volume_surge": False,
        }
