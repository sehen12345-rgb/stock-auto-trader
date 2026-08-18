"""
KIS WebSocket 실시간 시세 구독.

국내주식 H0STCNT0 TR을 구독해 현재가를 메모리 캐시에 유지한다.
DataFetcher가 REST 폴링 대신 이 캐시를 우선 참조한다.
"""
import asyncio
import json
import time
from typing import Any

import requests
import websockets
from loguru import logger

from config.settings import KIS_APP_KEY, KIS_APP_SECRET

_WS_URL = "wss://openapi.koreainvestment.com:9443"

# 실시간 현재가 캐시: {symbol: (price, timestamp)}
_LIVE_PRICES: dict[str, tuple[float, float]] = {}
_LIVE_PRICE_TTL = 60.0  # 60초 이상 갱신 없으면 신뢰하지 않음

_ws_task: asyncio.Task | None = None
_subscribed: set[str] = set()
_approval_key: str = ""
_approval_key_ts: float = 0.0


def get_live_price(symbol: str) -> float | None:
    """WebSocket 캐시에서 현재가 반환. 없거나 만료면 None."""
    entry = _LIVE_PRICES.get(symbol)
    if entry and (time.monotonic() - entry[1]) < _LIVE_PRICE_TTL:
        return entry[0]
    return None


def update_subscriptions(symbols: list[str]) -> None:
    """구독 대상 종목 갱신 (국내주식 코드만, 해외는 WebSocket 미지원)."""
    global _subscribed
    domestic = {s for s in symbols if s.isdigit()}
    _subscribed = domestic


async def _get_approval_key() -> str:
    """WebSocket 접속 승인키 발급 (24시간 유효)."""
    global _approval_key, _approval_key_ts
    now = time.monotonic()
    if _approval_key and (now - _approval_key_ts) < 82800:  # 23시간
        return _approval_key
    try:
        resp = requests.post(
            f"https://openapi.koreainvestment.com:9443/oauth2/Approval",
            json={
                "grant_type": "client_credentials",
                "appkey": KIS_APP_KEY,
                "secretkey": KIS_APP_SECRET,
            },
            timeout=10,
        )
        key = resp.json().get("approval_key", "")
        if key:
            _approval_key = key
            _approval_key_ts = now
            logger.info("[KIS-WS] 승인키 발급 완료")
        return key
    except Exception as e:
        logger.warning(f"[KIS-WS] 승인키 발급 실패: {e}")
        return ""


def _parse_price(raw: str) -> tuple[str, float] | None:
    """H0STCNT0 수신 메시지에서 (symbol, price) 추출."""
    try:
        # 형식: "0|H0STCNT0|001|005930^083000^283000^..."
        parts = raw.split("|")
        if len(parts) < 4 or parts[1] != "H0STCNT0":
            return None
        fields = parts[3].split("^")
        symbol = fields[0]
        price = float(fields[2])
        return symbol, price
    except Exception:
        return None


async def _run_ws() -> None:
    """WebSocket 연결 → 구독 → 수신 루프 (자동 재연결 포함)."""
    backoff = 5
    while True:
        if not _subscribed:
            await asyncio.sleep(10)
            continue
        approval_key = await _get_approval_key()
        if not approval_key:
            await asyncio.sleep(30)
            continue
        try:
            async with websockets.connect(_WS_URL, ping_interval=30, ping_timeout=10) as ws:
                logger.info(f"[KIS-WS] 연결 성공, {len(_subscribed)}종목 구독 시작")
                # 구독 메시지 전송
                for symbol in list(_subscribed):
                    msg = {
                        "header": {
                            "approval_key": approval_key,
                            "custtype": "P",
                            "tr_type": "1",
                            "content-type": "utf-8",
                        },
                        "body": {"input": {"tr_id": "H0STCNT0", "tr_key": symbol}},
                    }
                    await ws.send(json.dumps(msg))
                backoff = 5  # 연결 성공 시 백오프 리셋
                async for message in ws:
                    try:
                        parsed = _parse_price(message)
                        if parsed:
                            symbol, price = parsed
                            _LIVE_PRICES[symbol] = (price, time.monotonic())
                    except Exception:
                        pass
        except asyncio.CancelledError:
            logger.info("[KIS-WS] 구독 태스크 취소")
            break
        except Exception as e:
            logger.warning(f"[KIS-WS] 연결 끊김: {e} — {backoff}초 후 재연결")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)


async def start(symbols: list[str]) -> None:
    """WebSocket 구독 시작. 이미 실행 중이면 종목만 갱신."""
    global _ws_task
    update_subscriptions(symbols)
    if _ws_task and not _ws_task.done():
        return
    _ws_task = asyncio.create_task(_run_ws())
    logger.info(f"[KIS-WS] 구독 태스크 시작: {list(_subscribed)}")


async def stop() -> None:
    global _ws_task
    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
        try:
            await _ws_task
        except asyncio.CancelledError:
            pass
    _ws_task = None
