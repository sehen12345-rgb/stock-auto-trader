import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

ws_router = APIRouter()

_clients: list[WebSocket] = []


async def broadcast(data: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in _clients:
        try:
            await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.remove(ws)


@ws_router.websocket("/ws/live")
async def websocket_live(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.append(websocket)
    logger.info(f"[WS] 클라이언트 연결 (총 {len(_clients)}개)")
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[WS] 연결 종료: {e}")
    finally:
        if websocket in _clients:
            _clients.remove(websocket)
        logger.info(f"[WS] 클라이언트 해제 (남은 {len(_clients)}개)")
