"""
Stock Auto Trader MCP 서버.

Claude Code에서 주식 자동매매 봇을 직접 제어할 수 있도록 MCP 도구를 제공한다.
봇 FastAPI 서버(http://localhost:8000)에 HTTP 요청을 보내 결과를 반환한다.

사용법:
  python mcp/server.py
"""
import json
import sys
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BASE_URL = "http://localhost:8000/api"
TIMEOUT = 10.0

app = Server("stock-auto-trader")


def _get(path: str, params: dict | None = None) -> Any:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.get(f"{BASE_URL}{path}", params=params)
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict | None = None) -> Any:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(f"{BASE_URL}{path}", json=body or {})
        r.raise_for_status()
        return r.json()


def _delete(path: str) -> Any:
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.delete(f"{BASE_URL}{path}")
        r.raise_for_status()
        return r.json()


def _fmt(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_status",
            description="봇 실행 상태, 매매 모드, 시장 개장 여부, 마켓 리짐, 팩터 TOP5 조회",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_portfolio",
            description="포트폴리오 요약 — 총평가액, 현금, 투자액, 손익, 수익률",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_positions",
            description="현재 보유 포지션 목록 — 종목, 수량, 평단가, 현재가, 손익률, 손절/목표가",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_decisions",
            description="최근 LLM 매매 판단 이력 (BUY/SELL/HOLD, 확신도, 근거)",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_watchlist",
            description="관심종목 목록 — 종목코드, 이름, 현재가, MA20 상태, 52주고점 대비",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_return_history",
            description="최근 30일 일별 손익 및 누적 손익 히스토리",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_journal",
            description="매매일지 — 날짜별 매수/매도 내역, 손익 요약",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "조회 기간 (기본 7일)", "default": 7},
                },
                "required": [],
            },
        ),
        Tool(
            name="start_bot",
            description="자동매매 봇 시작",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="stop_bot",
            description="자동매매 봇 중지",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="liquidate",
            description="⚠️ 모든 포지션 즉시 전량 청산 + 봇 중지. 긴급 상황에서만 사용.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="set_trading_mode",
            description="매매 모드 변경 — scalping(초단타), day_trading(단타), swing(스윙), long_term(장기/올랜도킴)",
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["scalping", "day_trading", "swing", "long_term"],
                        "description": "변경할 매매 모드",
                    }
                },
                "required": ["mode"],
            },
        ),
        Tool(
            name="add_watchlist",
            description="관심종목 추가 (예: NVDA, 005930)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "종목코드"},
                    "name":   {"type": "string", "description": "종목명 (선택)", "default": ""},
                },
                "required": ["ticker"],
            },
        ),
        Tool(
            name="remove_watchlist",
            description="관심종목 제거",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "제거할 종목코드"},
                },
                "required": ["ticker"],
            },
        ),
        Tool(
            name="get_research",
            description="리서치 노트 조회 — 올랜도킴 분석, 목표가, 분할매수 가격",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "종목코드 필터 (선택)", "default": ""},
                },
                "required": [],
            },
        ),
        Tool(
            name="add_research",
            description="리서치 노트 저장 — 목표가, 분할매수 가격, 손절가 등록",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":       {"type": "string",  "description": "종목코드 (예: NVDA)"},
                    "source":       {"type": "string",  "description": "출처 (예: 올랜도킴, 씨티)"},
                    "rating":       {"type": "string",  "description": "투자의견 (예: BUY, 매수)"},
                    "target_price": {"type": "number",  "description": "목표가"},
                    "summary":      {"type": "string",  "description": "투자 근거 요약"},
                    "catalyst":     {"type": "string",  "description": "핵심 촉매"},
                    "buy_tier_1":   {"type": "number",  "description": "1차 분할매수 가격"},
                    "buy_tier_2":   {"type": "number",  "description": "2차 분할매수 가격"},
                    "buy_tier_3":   {"type": "number",  "description": "3차 분할매수 가격"},
                    "stop_price":   {"type": "number",  "description": "손절가"},
                },
                "required": ["ticker"],
            },
        ),
        Tool(
            name="set_price_alert",
            description="가격 알림 설정 — 특정 가격 도달 시 텔레그램 알림",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":       {"type": "string", "description": "종목코드"},
                    "price":        {"type": "number", "description": "알림 기준 가격"},
                    "condition":    {
                        "type": "string",
                        "enum": ["ABOVE", "BELOW"],
                        "description": "ABOVE=이상, BELOW=이하 도달 시 알림",
                    },
                    "note":         {"type": "string", "description": "메모 (선택)", "default": ""},
                },
                "required": ["ticker", "price", "condition"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "get_status":
            data = _get("/status")
            text = (
                f"봇 상태: {'▶ 실행중' if data.get('running') else '⏹ 중지'}\n"
                f"모드: {data.get('mode')} | 데모: {data.get('demo_mode')}\n"
                f"가동시간: {int(data.get('uptime_seconds', 0) // 60)}분\n"
                f"시장: {'개장' if data.get('market_open') else '마감'} | "
                f"리짐: {data.get('market_regime')} | "
                f"QQQ vs MA200: {data.get('qqq_vs_ma200', 0):+.1f}%\n"
                f"LLM 호출: {data.get('llm_call_count')}회\n"
                f"팩터 TOP5:\n"
                + "\n".join(
                    f"  {i+1}. {x['ticker']}: {x['score']:.0f}점"
                    for i, x in enumerate(data.get("top_factors", []))
                )
            )

        elif name == "get_portfolio":
            data = _get("/portfolio")
            text = (
                f"총평가액: {data.get('total_value', 0):,.0f}원\n"
                f"현금: {data.get('cash', 0):,.0f}원\n"
                f"투자액: {data.get('invested', 0):,.0f}원\n"
                f"손익: {data.get('pnl_amount', 0):+,.0f}원 ({data.get('return_pct', 0):+.2f}%)\n"
                f"시드: {data.get('seed', 0):,.0f}원"
            )

        elif name == "get_positions":
            data = _get("/positions")
            if not data:
                text = "보유 포지션 없음"
            else:
                lines = []
                for p in data:
                    lines.append(
                        f"[{p['symbol']}] {p['quantity']}주 | "
                        f"평단 {p['avg_price']:,.2f} → 현재 {p.get('current_price', 0):,.2f} | "
                        f"손익 {p.get('pnl_pct', 0):+.1f}% | "
                        f"손절 {p.get('stop_price', 0):,.2f} / 목표 {p.get('target_price', 0):,.2f}"
                    )
                text = "\n".join(lines)

        elif name == "get_decisions":
            data = _get("/decisions")
            if not data:
                text = "판단 이력 없음"
            else:
                lines = []
                for d in data[:10]:
                    lines.append(
                        f"[{d.get('timestamp', '')[:16]}] "
                        f"{d.get('decision')} {d.get('ticker', '-')} "
                        f"확신도:{d.get('confidence', 0)}% — {d.get('reason', '')[:60]}"
                    )
                text = "\n".join(lines)

        elif name == "get_watchlist":
            data = _get("/watchlist")
            if not data:
                text = "관심종목 없음"
            else:
                lines = []
                for w in data:
                    pct = w.get("pct_from_high")
                    pct_str = f"-{pct:.1f}%" if pct is not None else "N/A"
                    lines.append(
                        f"{w['ticker']} ({w.get('name', '')}) | "
                        f"현재가 {w.get('current_price') or 'N/A'} | "
                        f"MA20 {'위' if w.get('above_ma20') else '아래'} | "
                        f"52주고점 대비 {pct_str}"
                    )
                text = "\n".join(lines)

        elif name == "get_return_history":
            data = _get("/return-history")
            if not data:
                text = "수익률 이력 없음"
            else:
                recent = [d for d in data if d.get("pnl", 0) != 0][-10:]
                lines = [f"{d['date']}: {d['pnl']:+,.0f}원 (누적 {d['cumulative_pnl']:+,.0f}원)" for d in recent]
                text = "\n".join(lines) if lines else "최근 거래 없음"

        elif name == "get_journal":
            days = arguments.get("days", 7)
            data = _get("/journal", {"days": days})
            text = _fmt(data)

        elif name == "start_bot":
            data = _post("/start")
            text = f"봇 시작: {data.get('status', data)}"

        elif name == "stop_bot":
            data = _post("/stop")
            text = f"봇 중지: {data.get('status', data)}"

        elif name == "liquidate":
            data = _post("/liquidate")
            text = f"⚠️ 전량 청산 실행: {_fmt(data)}"

        elif name == "set_trading_mode":
            mode = arguments["mode"]
            data = _post("/trading-mode", {"mode": mode})
            text = f"매매 모드 변경 완료: {mode}\n{_fmt(data)}"

        elif name == "add_watchlist":
            data = _post("/watchlist", {"ticker": arguments["ticker"], "name": arguments.get("name", "")})
            text = f"관심종목 추가: {arguments['ticker']}"

        elif name == "remove_watchlist":
            ticker = arguments["ticker"]
            data = _delete(f"/watchlist/{ticker}")
            text = f"관심종목 제거: {ticker}"

        elif name == "get_research":
            ticker = arguments.get("ticker", "")
            params = {"ticker": ticker} if ticker else {}
            data = _get("/research", params)
            if not data:
                text = "리서치 노트 없음"
            else:
                lines = []
                for n in data:
                    lines.append(
                        f"[{n.get('created_at', '')[:10]}] {n['ticker']} | "
                        f"{n.get('source', '')} {n.get('rating', '')} | "
                        f"목표가 {n.get('target_price', 0):,.2f} | "
                        f"1차 {n.get('buy_tier_1', 0):,.2f} / "
                        f"2차 {n.get('buy_tier_2', 0):,.2f} / "
                        f"3차 {n.get('buy_tier_3', 0):,.2f}\n"
                        f"  {n.get('summary', '')[:100]}"
                    )
                text = "\n".join(lines)

        elif name == "add_research":
            data = _post("/research", arguments)
            text = f"리서치 노트 저장: {arguments['ticker']}\n{_fmt(data)}"

        elif name == "set_price_alert":
            data = _post("/alerts", {
                "ticker":    arguments["ticker"],
                "price":     arguments["price"],
                "condition": arguments["condition"],
                "note":      arguments.get("note", ""),
            })
            text = (
                f"알림 설정 완료: {arguments['ticker']} "
                f"{arguments['condition']} {arguments['price']:,.2f}\n{_fmt(data)}"
            )

        else:
            text = f"알 수 없는 도구: {name}"

    except httpx.ConnectError:
        text = (
            f"❌ 봇 서버에 연결할 수 없습니다 (http://localhost:8000)\n"
            f"봇이 실행 중인지 확인하세요: python main.py"
        )
    except httpx.HTTPStatusError as e:
        text = f"❌ API 오류 {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        text = f"❌ 오류: {e}"

    return [TextContent(type="text", text=text)]


if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(app))
