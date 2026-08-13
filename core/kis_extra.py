"""KIS API 추가 데이터 모듈.

외국인/기관 순매수 동향, 프로그램 매매 동향 등을 조회한다.
모든 API 호출은 try/except로 감싸고 실패 시 기본값을 반환한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from core.broker.kis import KISBroker

# 투자자별 순매수 TR-ID
TR_INVESTOR = "FHKST01010900"


def get_investor_trend(symbol: str, broker: "KISBroker") -> dict[str, Any]:
    """외국인/기관 순매수 조회.

    KIS API: /uapi/domestic-stock/v1/quotations/inquire-investor

    Args:
        symbol: 종목코드 (예: "005930")
        broker: KISBroker 인스턴스

    Returns:
        dict with keys:
            foreign_net (int): 외국인 순매수 (양수=순매수, 음수=순매도)
            institution_net (int): 기관 순매수
            individual_net (int): 개인 순매수
            foreign_buying (bool): 외국인 순매수 양수 여부
        실패 시: 기본값 반환
    """
    default: dict[str, Any] = {
        "foreign_net": 0,
        "institution_net": 0,
        "individual_net": 0,
        "foreign_buying": False,
    }

    try:
        # 해외주식은 지원하지 않음
        if broker._is_overseas(symbol):
            return default

        broker._ensure_token()
        url = f"{broker.base_url}/uapi/domestic-stock/v1/quotations/inquire-investor"
        headers = broker._headers(TR_INVESTOR)
        headers["content-type"] = "application/json; charset=utf-8"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }

        resp = broker._session.get(url, headers=headers, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        output = data.get("output", {})
        if not output:
            # output이 리스트인 경우
            output_list = data.get("output1", [])
            if output_list:
                output = output_list[0]

        def _int(key: str) -> int:
            try:
                return int(str(output.get(key, "0")).replace(",", "").replace("+", "") or "0")
            except (ValueError, TypeError):
                return 0

        # KIS API 필드명 매핑 (실제 필드명은 API 문서 참조)
        # prsn_ntby_qty: 개인 순매수 수량
        # frgn_ntby_qty: 외국인 순매수 수량
        # orgn_ntby_qty: 기관 순매수 수량
        foreign_net = _int("frgn_ntby_qty")
        institution_net = _int("orgn_ntby_qty")
        individual_net = _int("prsn_ntby_qty")

        result = {
            "foreign_net": foreign_net,
            "institution_net": institution_net,
            "individual_net": individual_net,
            "foreign_buying": foreign_net > 0,
        }
        logger.debug(
            f"[KISExtra] {symbol} 외국인={foreign_net:+,} "
            f"기관={institution_net:+,} 개인={individual_net:+,}"
        )
        return result

    except Exception as e:
        logger.debug(f"[KISExtra] {symbol} 투자자 동향 조회 실패: {e}")
        return default


def get_program_trading(symbol: str, broker: "KISBroker") -> dict[str, Any]:
    """프로그램 매매 동향 조회.

    Args:
        symbol: 종목코드
        broker: KISBroker 인스턴스

    Returns:
        dict with keys:
            program_net (int): 프로그램 순매수 수량
        실패 시: {"program_net": 0}
    """
    default: dict[str, Any] = {"program_net": 0}

    try:
        if broker._is_overseas(symbol):
            return default

        broker._ensure_token()
        # KIS 프로그램 매매 API (예시, 실제 TR-ID 확인 필요)
        url = f"{broker.base_url}/uapi/domestic-stock/v1/quotations/inquire-program-trade-by-stock"
        headers = broker._headers("FHPPG04650100")
        headers["content-type"] = "application/json; charset=utf-8"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_INPUT_DATE_1": "",
        }

        resp = broker._session.get(url, headers=headers, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        output = data.get("output", [])
        if isinstance(output, list) and output:
            first = output[0]
        elif isinstance(output, dict):
            first = output
        else:
            return default

        def _int(key: str) -> int:
            try:
                return int(str(first.get(key, "0")).replace(",", "").replace("+", "") or "0")
            except (ValueError, TypeError):
                return 0

        program_net = _int("pgm_ntby_qty")
        logger.debug(f"[KISExtra] {symbol} 프로그램 순매수={program_net:+,}")
        return {"program_net": program_net}

    except Exception as e:
        logger.debug(f"[KISExtra] {symbol} 프로그램 매매 조회 실패: {e}")
        return default
