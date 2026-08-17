from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.engine import TradingEngine
from database.research_repo import get_research_repo

router = APIRouter()
engine = TradingEngine()


class WatchlistAddRequest(BaseModel):
    ticker: str
    name: str = ""


class TradingModeRequest(BaseModel):
    mode: str  # "scalping" | "day_trading" | "swing" | "long_term"


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str = "long_term"  # "scalping" | "day_trading" | "swing" | "long_term"
    period_days: int = 90


class ResearchNoteRequest(BaseModel):
    ticker: str
    source: str = ""
    rating: str = ""
    target_price: float = 0.0
    current_price: float = 0.0
    summary: str = ""
    content: str = ""
    catalyst: str = ""
    buy_tier_1: float = 0.0
    buy_tier_2: float = 0.0
    buy_tier_3: float = 0.0
    stop_price: float = 0.0
    horizon: str = ""


@router.get("/status")
async def get_status() -> dict[str, Any]:
    try:
        return {
            "running": engine.running,
            "mode": "paper" if engine.is_paper else "live",
            "demo_mode": engine.demo_mode,
            "uptime_seconds": engine.uptime_seconds(),
            "last_tick": engine.last_tick.isoformat() if engine.last_tick else None,
            "llm_call_count": engine.llm_call_count,
            "market_open": engine._is_market_hours() or engine._is_nasdaq_hours(),
            "market_regime": engine._market_regime.get("regime", "neutral"),
            "qqq_vs_ma200": engine._market_regime.get("pct_from_ma200", 0),
            "top_factors": [
                {"ticker": t, "score": s}
                for t, s in sorted(engine._factor_scores.items(), key=lambda x: x[1], reverse=True)[:5]
            ],
        }
    except Exception as e:
        return {"running": False, "mode": "unknown", "demo_mode": False,
                "uptime_seconds": 0, "last_tick": None, "llm_call_count": 0,
                "market_open": False, "error": str(e)}


@router.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    import os
    seed = int(os.getenv("SEED_AMOUNT", "2000000"))
    try:
        return await engine.get_portfolio()
    except Exception:
        return {"total_value": seed, "cash": seed, "invested": 0,
                "pnl_amount": 0, "return_pct": 0.0, "seed": seed, "api_error": True}


@router.get("/positions")
async def get_positions() -> list[dict[str, Any]]:
    try:
        return await engine.get_positions()
    except Exception:
        return []


@router.get("/decisions")
async def get_decisions() -> list[dict[str, Any]]:
    try:
        return engine.get_recent_decisions(limit=20)
    except Exception:
        return []


@router.get("/watchlist")
async def get_watchlist() -> list[dict[str, Any]]:
    try:
        return await engine.get_watchlist()
    except Exception:
        return []


@router.post("/start")
async def start_bot() -> dict[str, str]:
    if engine.running:
        return {"status": "already_running"}
    await engine.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_bot() -> dict[str, str]:
    if not engine.running:
        return {"status": "already_stopped"}
    await engine.stop()
    return {"status": "stopped"}


@router.post("/liquidate")
async def liquidate_all() -> dict[str, Any]:
    """보유 포지션 전량 즉시 청산 + 봇 중지."""
    positions = await engine.get_positions()
    await engine._close_all_positions("수동 전체 청산 요청")
    if engine.running:
        await engine.stop()
    return {"status": "ok", "count": len(positions),
            "symbols": [p.get("symbol") for p in positions],
            "bot_stopped": True}


@router.post("/watchlist")
async def add_watchlist(req: WatchlistAddRequest) -> dict[str, str]:
    engine.add_to_watchlist(req.ticker, req.name)
    return {"status": "added", "ticker": req.ticker}


@router.delete("/watchlist/{ticker}")
async def remove_watchlist(ticker: str) -> dict[str, str]:
    engine.remove_from_watchlist(ticker)
    return {"status": "removed", "ticker": ticker}


@router.get("/return-history")
async def get_return_history() -> list[dict[str, Any]]:
    try:
        return await engine.get_return_history()
    except Exception:
        return []


# ── 매매 모드 ──────────────────────────────────────────────────────────────

@router.get("/trading-mode")
async def get_trading_mode() -> dict[str, Any]:
    """현재 매매 모드 반환."""
    from core.engine import TRADING_MODE_CONFIG
    mode = engine.trading_mode
    cfg = TRADING_MODE_CONFIG.get(mode, {})
    return {
        "mode": mode,
        "tick_interval": cfg.get("tick_interval", 30),
        "stop_pct": cfg.get("stop_pct", 3.5),
        "take_profit_pct": cfg.get("take_profit_pct", 6.0),
        "trailing_stop_pct": 2.0,
    }


@router.post("/trading-mode")
async def set_trading_mode(req: TradingModeRequest) -> dict[str, Any]:
    """매매 모드 변경."""
    from core.engine import TRADING_MODE_CONFIG
    if req.mode not in TRADING_MODE_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 모드: {req.mode}. 허용: {list(TRADING_MODE_CONFIG.keys())}",
        )
    engine.set_trading_mode(req.mode)
    return {"status": "ok", "mode": req.mode}


# ── 백테스트 ───────────────────────────────────────────────────────────────

@router.post("/backtest")
async def run_backtest(req: BacktestRequest) -> dict[str, Any]:
    """백테스트 실행.

    ticker의 과거 OHLCV 데이터를 받아 strategy 기반 백테스트 결과를 반환한다.
    DEMO_MODE 또는 DataFetcher를 통해 OHLCV를 받는다.
    """
    import os
    from loguru import logger

    DEMO_MODE_FLAG: bool = os.getenv("DEMO_MODE", "false").lower() == "true"

    try:
        from core.backtest import Backtest
        from core.engine import TRADING_MODE_CONFIG

        mode_cfg = TRADING_MODE_CONFIG.get(req.strategy, {})
        stop_pct = mode_cfg.get("stop_pct", 3.5)
        tp_pct = mode_cfg.get("take_profit_pct", 6.0)

        import pandas as pd

        if DEMO_MODE_FLAG:
            # 데모 모드: 랜덤 OHLCV 생성
            import numpy as np
            import random
            n = min(req.period_days, 252)
            base = 50000.0
            closes = [base]
            for _ in range(n - 1):
                closes.append(closes[-1] * (1 + random.gauss(0.001, 0.02)))
            highs = [c * random.uniform(1.0, 1.03) for c in closes]
            lows = [c * random.uniform(0.97, 1.0) for c in closes]
            opens = [c * random.uniform(0.98, 1.02) for c in closes]
            vols = [int(random.uniform(500000, 2000000)) for _ in closes]
            df = pd.DataFrame({
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": vols,
            })
        else:
            try:
                from core.data_fetcher import DataFetcher
                fetcher = DataFetcher()
                df = await fetcher.fetch_ohlcv(req.ticker, period=req.period_days)
            except Exception as e:
                logger.warning(f"[Backtest API] OHLCV 조회 실패, 더미 사용: {e}")
                df = pd.DataFrame()

        if df is None or df.empty:
            return {
                "error": "OHLCV 데이터 없음",
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "total_return": 0.0,
                "sharpe_ratio": 0.0,
                "trades": [],
            }

        bt = Backtest()
        result = bt.run(df, strategy_name=req.strategy, stop_pct=stop_pct, take_profit_pct=tp_pct)
        result["ticker"] = req.ticker
        result["strategy"] = req.strategy
        result["period_days"] = req.period_days
        result["stop_pct"] = stop_pct
        result["take_profit_pct"] = tp_pct
        # trades 리스트 최대 100개
        result["trades"] = result.get("trades", [])[:100]
        return result

    except Exception as e:
        logger.error(f"[Backtest API] 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── 리서치 노트 ────────────────────────────────────────────────────────────

@router.post("/research")
async def save_research(req: ResearchNoteRequest) -> dict[str, Any]:
    """리서치 노트 저장."""
    repo = get_research_repo()
    note_id = repo.save(req.model_dump())
    return {"status": "saved", "id": note_id}


@router.get("/research")
async def list_research(ticker: str = "") -> list[dict[str, Any]]:
    """리서치 노트 목록. ticker 쿼리 파라미터로 필터링 가능."""
    repo = get_research_repo()
    if ticker:
        return repo.find_by_ticker(ticker.upper(), limit=50)
    return repo.find_all(limit=50)


@router.delete("/research/{note_id}")
async def delete_research(note_id: int) -> dict[str, Any]:
    """리서치 노트 삭제."""
    repo = get_research_repo()
    repo.delete(note_id)
    return {"status": "deleted", "id": note_id}


@router.post("/research/{note_id}/create-alerts")
async def create_research_alerts(note_id: int) -> dict[str, Any]:
    """리서치 노트의 분할매수 가격대로 텔레그램 알림 자동 생성."""
    from database.alert_repo import get_alert_repo

    repo = get_research_repo()
    note = repo.find_by_id(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="리서치 노트 없음")

    alert_repo = get_alert_repo()
    ticker = note["ticker"]
    source = note.get("source", "올랜도킴")
    created = []

    tiers = [
        (note.get("buy_tier_1", 0), "1차 분할매수"),
        (note.get("buy_tier_2", 0), "2차 분할매수"),
        (note.get("buy_tier_3", 0), "3차 분할매수"),
    ]
    for price, label in tiers:
        if price and price > 0:
            aid = alert_repo.save(
                ticker=ticker,
                name=label,
                alert_type="BELOW",
                target_price=price,
                memo=f"[{source}] {label} 구간 | 목표가 {note.get('target_price', 0)} | 손절 {note.get('stop_price', 0)}",
            )
            created.append({"id": aid, "label": label, "price": price})

    # 목표가 도달 알림도 생성
    if note.get("target_price", 0) > 0:
        aid = alert_repo.save(
            ticker=ticker,
            name="목표가 도달",
            alert_type="ABOVE",
            target_price=note["target_price"],
            memo=f"[{source}] 목표가 도달 — 매도 검토",
        )
        created.append({"id": aid, "label": "목표가", "price": note["target_price"]})

    return {"status": "ok", "created": len(created), "alerts": created}


class ResearchParseRequest(BaseModel):
    ticker: str
    raw_text: str

@router.post("/research/parse")
async def parse_research(req: ResearchParseRequest) -> dict[str, Any]:
    """원문 리서치 텍스트를 Claude가 파싱해서 구조화된 형태로 반환."""
    import os
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY 없음")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""다음 리서치 텍스트를 파싱해서 JSON으로 반환하세요. 종목코드: {req.ticker}

텍스트:
{req.raw_text}

반드시 아래 JSON 형식만 반환 (설명 없이):
{{
  "source": "분석가/출처명",
  "rating": "Buy/Outperform/Hold 등",
  "target_price": 숫자(없으면 0),
  "current_price": 숫자(없으면 0),
  "summary": "핵심 요약 2-3문장",
  "catalyst": "주요 촉매/이벤트",
  "buy_tier_1": 숫자(1차 분할매수가, 없으면 0),
  "buy_tier_2": 숫자(2차 분할매수가, 없으면 0),
  "buy_tier_3": 숫자(3차 분할매수가, 없으면 0),
  "stop_price": 숫자(손절가, 없으면 0),
  "horizon": "투자 기간(예: 6개월, 1년)"
}}"""
            }]
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        import json
        parsed = json.loads(text)
        parsed["ticker"] = req.ticker.upper()
        return parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 가격 알림 ─────────────────────────────────────────────────────────────────

class AlertRequest(BaseModel):
    ticker: str
    name: str = ""
    alert_type: str  # "ABOVE" | "BELOW" | "CHANGE_PCT"
    target_price: float = 0.0
    change_pct: float = 0.0
    memo: str = ""


@router.get("/alerts")
async def list_alerts() -> list[dict[str, Any]]:
    from database.alert_repo import get_alert_repo
    return get_alert_repo().find_all()


@router.post("/alerts")
async def create_alert(req: AlertRequest) -> dict[str, Any]:
    from database.alert_repo import get_alert_repo
    if req.alert_type not in ("ABOVE", "BELOW", "CHANGE_PCT"):
        raise HTTPException(status_code=400, detail="alert_type: ABOVE | BELOW | CHANGE_PCT")
    aid = get_alert_repo().save(
        ticker=req.ticker.upper(),
        name=req.name,
        alert_type=req.alert_type,
        target_price=req.target_price,
        change_pct=req.change_pct,
        memo=req.memo,
    )
    return {"status": "created", "id": aid}


@router.post("/alerts/{alert_id}/reactivate")
async def reactivate_alert(alert_id: int) -> dict[str, Any]:
    from database.alert_repo import get_alert_repo
    get_alert_repo().reactivate(alert_id)
    return {"status": "reactivated", "id": alert_id}


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: int) -> dict[str, Any]:
    from database.alert_repo import get_alert_repo
    get_alert_repo().delete(alert_id)
    return {"status": "deleted", "id": alert_id}


# ── 매매 일지 ──────────────────────────────────────────────────────────────────

@router.get("/toss-balance")
async def get_toss_balance() -> dict[str, Any]:
    """토스증권 잔고 조회 (읽기전용)."""
    import os
    key     = os.getenv("TOSS_APP_KEY", "")
    secret  = os.getenv("TOSS_APP_SECRET", "")
    account = os.getenv("TOSS_ACCOUNT_NO", "")
    if not all([key, secret, account]):
        return {"available": False, "error": "토스 API 자격증명 없음 (.env 설정 필요)"}
    try:
        from core.broker.toss import TossBroker
        broker = TossBroker()
        if not broker.connect():
            return {"available": False, "error": "토스 연결 실패"}
        bal = broker.get_balance()
        return {
            "available": True,
            "cash": bal.cash,
            "total_equity": bal.total_equity,
            "buying_power": bal.buying_power,
            "currency": getattr(bal, "currency", "KRW"),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


@router.get("/journal")
async def get_journal(days: int = 30) -> list[dict[str, Any]]:
    """최근 N일 매매 일지 (날짜별 요약)."""
    from database.models import TradeRepository
    from database.db import get_db
    import datetime as _dt

    repo = TradeRepository(get_db())
    result = []
    today = _dt.date.today()

    for i in range(days):
        d = today - _dt.timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        trades = repo.find_by_date(date_str)
        if not trades:
            continue

        buys   = [t for t in trades if t.side == "BUY"  and t.status == "FILLED"]
        sells  = [t for t in trades if t.side == "SELL" and t.status == "FILLED"]
        daily_pnl = sum(t.pnl for t in sells)
        wins   = [t for t in sells if t.pnl > 0]
        losses = [t for t in sells if t.pnl < 0]

        trade_list = []
        for t in sorted(trades, key=lambda x: x.created_at):
            trade_list.append({
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.filled_price or t.price,
                "pnl": round(t.pnl, 0),
                "status": t.status,
                "time": t.created_at[11:16],
            })

        result.append({
            "date": date_str,
            "pnl": round(daily_pnl, 0),
            "buy_count": len(buys),
            "sell_count": len(sells),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(len(wins) / len(sells) * 100, 1) if sells else 0,
            "trades": trade_list,
        })

    return result


# ── 기기 간 DB 동기화 ───────────────────────────────────────────────────────────

class SyncImportRequest(BaseModel):
    trades: list[dict[str, Any]] = []
    research: list[dict[str, Any]] = []


@router.get("/sync/export")
async def sync_export() -> dict[str, Any]:
    """현재 기기의 매매일지 + 리서치 노트를 JSON으로 내보내기."""
    from database.models import TradeRepository
    from database.db import get_db
    import socket

    db = get_db()
    repo = TradeRepository(db)

    trades = repo.find_all(limit=10000)
    trade_list = [
        {
            "symbol": t.symbol, "side": t.side, "order_type": t.order_type,
            "quantity": t.quantity, "price": t.price,
            "filled_qty": t.filled_qty, "filled_price": t.filled_price,
            "order_id": t.order_id, "status": t.status,
            "market": t.market, "strategy": t.strategy,
            "pnl": t.pnl, "created_at": t.created_at,
        }
        for t in trades
    ]

    research_rows = db.execute("SELECT * FROM research_notes ORDER BY created_at", ())
    research_list = [dict(r) for r in research_rows]

    return {
        "device": socket.gethostname(),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "trade_count": len(trade_list),
        "research_count": len(research_list),
        "trades": trade_list,
        "research": research_list,
    }


@router.post("/sync/import")
async def sync_import(req: SyncImportRequest) -> dict[str, Any]:
    """다른 기기의 매매일지 + 리서치 노트를 가져와서 병합 (중복 제거)."""
    from database.db import get_db

    db = get_db()
    trade_added = 0
    research_added = 0

    # ── trades 병합 ─────────────────────────────────────────────────
    existing_order_ids = {
        row["order_id"]
        for row in db.execute("SELECT order_id FROM trades WHERE order_id != ''", ())
    }
    existing_keys = {
        (row["symbol"], row["side"], row["created_at"])
        for row in db.execute("SELECT symbol, side, created_at FROM trades", ())
    }

    for t in req.trades:
        oid = t.get("order_id", "")
        key = (t.get("symbol", ""), t.get("side", ""), t.get("created_at", ""))
        if (oid and oid in existing_order_ids) or (key in existing_keys):
            continue
        db.insert(
            """INSERT INTO trades
               (symbol, side, order_type, quantity, price,
                filled_qty, filled_price, order_id, status,
                market, strategy, pnl, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                t.get("symbol", ""), t.get("side", ""), t.get("order_type", "MARKET"),
                t.get("quantity", 0), t.get("price", 0),
                t.get("filled_qty", 0), t.get("filled_price", 0),
                oid, t.get("status", "FILLED"),
                t.get("market", ""), t.get("strategy", ""),
                t.get("pnl", 0), t.get("created_at", ""), t.get("created_at", ""),
            ),
        )
        if oid:
            existing_order_ids.add(oid)
        existing_keys.add(key)
        trade_added += 1

    # ── research_notes 병합 ──────────────────────────────────────────
    existing_research = {
        (row["ticker"], row["created_at"])
        for row in db.execute("SELECT ticker, created_at FROM research_notes", ())
    }

    for r in req.research:
        rkey = (r.get("ticker", ""), r.get("created_at", ""))
        if rkey in existing_research:
            continue
        db.insert(
            """INSERT INTO research_notes
               (ticker, source, rating, target_price, current_price,
                summary, content, catalyst,
                buy_tier_1, buy_tier_2, buy_tier_3, stop_price, horizon,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r.get("ticker", ""), r.get("source", ""), r.get("rating", ""),
                r.get("target_price", 0), r.get("current_price", 0),
                r.get("summary", ""), r.get("content", ""), r.get("catalyst", ""),
                r.get("buy_tier_1", 0), r.get("buy_tier_2", 0), r.get("buy_tier_3", 0),
                r.get("stop_price", 0), r.get("horizon", ""),
                r.get("created_at", ""), r.get("updated_at", ""),
            ),
        )
        existing_research.add(rkey)
        research_added += 1

    return {
        "status": "ok",
        "trade_added": trade_added,
        "research_added": research_added,
    }


@router.post("/sync/pull")
async def sync_pull(body: dict[str, Any]) -> dict[str, Any]:
    """상대 기기 URL에서 데이터를 직접 당겨와서 병합.

    body: {"url": "http://192.168.x.x:8000"}
    """
    import httpx

    peer_url = body.get("url", "").rstrip("/")
    if not peer_url:
        raise HTTPException(status_code=400, detail="url 필요 (예: http://192.168.1.10:8000)")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{peer_url}/api/sync/export")
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"상대 기기 접속 실패: {e}")

    req = SyncImportRequest(
        trades=data.get("trades", []),
        research=data.get("research", []),
    )
    result = await sync_import(req)
    result["peer"] = data.get("device", peer_url)
    result["peer_trades"] = data.get("trade_count", 0)
    result["peer_research"] = data.get("research_count", 0)
    return result
