"""
텔레그램 봇.
TELEGRAM_BOT_TOKEN 없으면 조용히 스킵.
있으면 /status /portfolio /stop /start /watchlist 명령 지원.
"""
import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_app: Any = None


def _get_app() -> Any:
    global _app
    if not TELEGRAM_BOT_TOKEN:
        return None
    if _app is not None:
        return _app
    try:
        from telegram.ext import Application, CommandHandler
        _app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        _app.add_handler(CommandHandler("status",    cmd_status))
        _app.add_handler(CommandHandler("portfolio", cmd_portfolio))
        _app.add_handler(CommandHandler("stop",      cmd_stop))
        _app.add_handler(CommandHandler("start",     cmd_start))
        _app.add_handler(CommandHandler("watchlist", cmd_watchlist))
        _app.add_handler(CommandHandler("positions", cmd_positions))
        _app.add_handler(CommandHandler("sell",      cmd_sell))
        _app.add_handler(CommandHandler("mode",      cmd_mode))
        _app.add_handler(CommandHandler("seed",      cmd_seed))
        _app.add_handler(CommandHandler("help",      cmd_help))
        logger.info("[Telegram] 봇 핸들러 등록 완료")
    except Exception as e:
        logger.warning(f"[Telegram] 봇 초기화 실패: {e}")
        _app = None
    return _app


async def _send(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug(f"[Telegram] 설정 없음, 건너뜀: {text[:60]}")
        return
    app = _get_app()
    if app is None:
        return
    try:
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"[Telegram] 전송 실패: {e}")


async def notify_start() -> None:
    now = datetime.now().strftime("%H:%M:%S")
    await _send(
        f"🟢 <b>봇 시작</b>\n"
        f"시각: {now}\n"
        f"올랜도킴 전략 자동매매 시작합니다."
    )


async def notify_stop() -> None:
    now = datetime.now().strftime("%H:%M:%S")
    await _send(
        f"🔴 <b>봇 중지</b>\n"
        f"시각: {now}\n"
        f"킬스위치 발동. 모든 자동매매 중단."
    )


async def notify_trade(
    action: str,
    ticker: str,
    qty: int,
    price: float,
    stop_price: float,
    target_price: float,
    reason: str,
    pnl_pct: float = 0.0,
) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    total = price * qty if price > 0 else 0

    if action == "BUY":
        lines = [
            "🟢 <b>매수 체결</b>",
            f"종목: <code>{ticker}</code>",
            f"수량: {qty:,}주",
            f"단가: {price:,.0f}원",
            f"총액: {total:,.0f}원",
            f"손절가: {stop_price:,.0f}원 (-3.5%)",
            f"목표가: {target_price:,.0f}원 (+6.0%)",
            f"시각: {now}",
            f"근거: {reason}",
        ]
    else:
        sign = "+" if pnl_pct >= 0 else ""
        emoji = "🔴" if pnl_pct < 0 else "📈"
        lines = [
            f"{emoji} <b>매도 체결</b>",
            f"종목: <code>{ticker}</code>",
            f"수량: {qty:,}주",
            f"단가: {price:,.0f}원",
            f"총액: {total:,.0f}원",
            f"수익률: {sign}{pnl_pct:.2f}%",
            f"시각: {now}",
            f"근거: {reason}",
        ]

    await _send("\n".join(lines))


async def notify_market_open(positions: list[dict[str, Any]]) -> None:
    now = datetime.now().strftime("%H:%M")
    pos_cnt = len(positions)
    lines = [
        f"🔔 <b>장 시작</b> ({now})",
        f"보유종목: {pos_cnt}개 / 4",
    ]
    if positions:
        for p in positions:
            pnl = p.get("pnl_pct", 0)
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  · {p['symbol']} {p['quantity']}주 ({sign}{pnl:.1f}%)")
    lines.append("올랜도킴 전략 모니터링 시작.")
    await _send("\n".join(lines))


async def notify_market_close(
    portfolio: dict[str, Any],
    positions: list[dict[str, Any]],
    daily_pnl: float,
) -> None:
    now = datetime.now().strftime("%H:%M")
    total = portfolio.get("total_value", 0)
    ret = portfolio.get("return_pct", 0)
    sign = "+" if ret >= 0 else ""
    pnl_sign = "+" if daily_pnl >= 0 else ""

    lines = [
        f"🌙 <b>장 마감 리포트</b> ({now})",
        f"총평가액: <b>{total:,.0f}원</b>",
        f"총수익률: {sign}{ret:.2f}%",
        f"오늘 손익: {pnl_sign}{daily_pnl:,.0f}원",
        f"보유종목: {len(positions)}개",
    ]
    if positions:
        for p in positions:
            pnl = p.get("pnl_pct", 0)
            s = "+" if pnl >= 0 else ""
            lines.append(f"  · {p['symbol']} {p['quantity']}주 ({s}{pnl:.1f}%)")
    await _send("\n".join(lines))


async def notify_positions(positions: list[dict[str, Any]]) -> None:
    if not positions:
        await _send("📊 <b>보유 포지션 없음</b>")
        return
    lines = ["📊 <b>현재 포지션</b>"]
    for p in positions:
        pnl = p.get("pnl_pct", 0)
        sign = "+" if pnl >= 0 else ""
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(
            f"  {emoji} <code>{p['symbol']}</code> {p['quantity']}주 "
            f"({sign}{pnl:.1f}%)"
        )
    await _send("\n".join(lines))


async def cmd_status(update: Any, context: Any) -> None:
    try:
        from core.engine import TradingEngine
        engine = TradingEngine()
        status = "가동중 🟢" if engine.running else "중지 🔴"
        mode = "데모" if engine.demo_mode else ("모의" if engine.is_paper else "실전")
        positions = await engine.get_positions()
        uptime = int(engine.uptime_seconds())
        h, r = divmod(uptime, 3600)
        m, s = divmod(r, 60)
        uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
        is_mkt = "장중" if engine._is_market_hours() else "장외"
        await update.message.reply_text(
            f"<b>봇 상태</b>: {status}\n"
            f"<b>모드</b>: {mode} ({is_mkt})\n"
            f"<b>가동시간</b>: {uptime_str}\n"
            f"<b>보유 종목</b>: {len(positions)}개 / 4\n"
            f"<b>LLM 호출</b>: {engine.llm_call_count}회",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_portfolio(update: Any, context: Any) -> None:
    try:
        from core.engine import TradingEngine
        engine = TradingEngine()
        pf = await engine.get_portfolio()
        ret = pf.get("return_pct", 0)
        sign = "+" if ret >= 0 else ""
        emoji = "📈" if ret >= 0 else "📉"
        seed = pf.get("seed", 10_000_000)
        total = pf.get("total_value", 0)
        pnl_amt = total - seed if total > 0 else 0
        pnl_sign = "+" if pnl_amt >= 0 else ""
        await update.message.reply_text(
            f"{emoji} <b>포트폴리오</b>\n"
            f"시드: {seed:,.0f}원\n"
            f"총평가액: <b>{total:,.0f}원</b>\n"
            f"현금: {pf.get('cash', 0):,.0f}원\n"
            f"손익: {pnl_sign}{pnl_amt:,.0f}원\n"
            f"수익률: {sign}{ret:.2f}%",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_stop(update: Any, context: Any) -> None:
    try:
        from core.engine import TradingEngine
        engine = TradingEngine()
        if engine.running:
            await engine.stop()
            await update.message.reply_text("🔴 봇을 중지했습니다.")
        else:
            await update.message.reply_text("이미 중지 상태입니다.")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_start(update: Any, context: Any) -> None:
    try:
        from core.engine import TradingEngine
        engine = TradingEngine()
        if not engine.running:
            await engine.start()
            await update.message.reply_text("🟢 봇을 시작했습니다.")
        else:
            await update.message.reply_text("이미 가동 중입니다.")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_watchlist(update: Any, context: Any) -> None:
    try:
        from core.engine import TradingEngine
        engine = TradingEngine()
        items = await engine.get_watchlist()
        if not items:
            await update.message.reply_text("관심종목이 없습니다.")
            return
        lines = ["📋 <b>관심종목</b>"]
        for item in items:
            price_str = f"{item['current_price']:,.0f}" if item.get('current_price') else "-"
            dist_str = f" 고점까지 -{item['pct_from_high']:.1f}%" if item.get('pct_from_high') is not None else ""
            ma_str = " (MA위)" if item.get("above_ma20") else ""
            lines.append(f"  <code>{item['ticker']}</code> {item.get('name','')} {price_str}원{ma_str}{dist_str}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_positions(update: Any, context: Any) -> None:
    try:
        from core.engine import TradingEngine
        engine = TradingEngine()
        positions = await engine.get_positions()
        if not positions:
            await update.message.reply_text("📊 보유 포지션 없음")
            return
        lines = ["📊 <b>현재 포지션</b>"]
        for p in positions:
            pnl = p.get("pnl_pct", 0)
            sign = "+" if pnl >= 0 else ""
            emoji = "🟢" if pnl >= 0 else "🔴"
            stop = p.get("stop_price", 0)
            target = p.get("target_price", 0)
            lines.append(
                f"{emoji} <code>{p['symbol']}</code> {p['quantity']}주\n"
                f"   매수가: {p['avg_price']:,.0f}  현재: {p.get('current_price',0):,.0f}\n"
                f"   수익률: {sign}{pnl:.2f}%  |  손절: {stop:,.0f}  목표: {target:,.0f}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_sell(update: Any, context: Any) -> None:
    """/sell TICKER — 수동 즉시 매도."""
    try:
        from core.engine import TradingEngine
        engine = TradingEngine()
        args = context.args
        if not args:
            await update.message.reply_text("사용법: /sell 종목코드\n예) /sell 005930")
            return
        ticker = args[0].upper()
        positions = await engine.get_positions()
        pos = next((p for p in positions if p.get("symbol") == ticker), None)
        if pos is None:
            await update.message.reply_text(f"❌ {ticker} 미보유 종목입니다.")
            return
        market_data = {}
        try:
            data = await engine.fetcher.fetch(ticker)
            market_data[ticker] = data
        except Exception:
            market_data[ticker] = {"current_price": pos.get("current_price", 0)}
        await engine._execute(
            {"decision": "SELL", "ticker": ticker, "quantity": pos["quantity"],
             "confidence": 99, "reason": "텔레그램 수동 매도"},
            positions, market_data,
        )
        await update.message.reply_text(f"✅ {ticker} 매도 주문 실행됨")
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_mode(update: Any, context: Any) -> None:
    """/mode [MODE] — 매매 모드 조회 또는 변경."""
    try:
        from core.engine import TradingEngine, TRADING_MODE_CONFIG
        engine = TradingEngine()
        args = context.args
        if not args:
            cfg = TRADING_MODE_CONFIG.get(engine.trading_mode, {})
            await update.message.reply_text(
                f"⚙️ <b>현재 모드: {engine.trading_mode}</b>\n"
                f"틱 간격: {cfg.get('tick_interval')}초\n"
                f"손절: -{cfg.get('stop_pct')}%  목표: +{cfg.get('take_profit_pct')}%\n\n"
                f"변경: /mode scalping | day_trading | swing | long_term",
                parse_mode="HTML",
            )
            return
        new_mode = args[0].lower()
        if new_mode not in TRADING_MODE_CONFIG:
            await update.message.reply_text(f"❌ 지원 모드: scalping, day_trading, swing, long_term")
            return
        engine.set_trading_mode(new_mode)
        cfg = TRADING_MODE_CONFIG[new_mode]
        await update.message.reply_text(
            f"✅ 모드 변경: <b>{new_mode}</b>\n"
            f"손절 -{cfg['stop_pct']}% / 목표 +{cfg['take_profit_pct']}%",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_seed(update: Any, context: Any) -> None:
    """/seed — 현재 시드 및 누적 손익 조회."""
    try:
        import os
        from core.engine import TradingEngine, SEED_AMOUNT
        engine = TradingEngine()
        pf = await engine.get_portfolio()
        total = pf.get("total_value", 0)
        cash = pf.get("cash", 0)
        initial_seed = int(os.getenv("SEED_AMOUNT", "2000000"))
        pnl_amt = total - initial_seed if total > 0 else 0
        pnl_sign = "+" if pnl_amt >= 0 else ""
        emoji = "📈" if pnl_amt >= 0 else "📉"
        await update.message.reply_text(
            f"{emoji} <b>시드 현황</b>\n"
            f"초기 시드: {initial_seed:,}원\n"
            f"현재 시드: <b>{SEED_AMOUNT:,}원</b>\n"
            f"총 평가액: {total:,}원\n"
            f"예수금: {cash:,}원\n"
            f"누적 손익: {pnl_sign}{pnl_amt:,}원",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"오류: {e}")


async def cmd_help(update: Any, context: Any) -> None:
    await update.message.reply_text(
        "📋 <b>사용 가능한 명령어</b>\n\n"
        "/status — 봇 상태 확인\n"
        "/positions — 보유 포지션 (손절/목표가 포함)\n"
        "/portfolio — 포트폴리오 요약\n"
        "/sell 종목코드 — 즉시 매도 (예: /sell 005930)\n"
        "/mode — 현재 매매 모드 확인\n"
        "/mode day_trading — 모드 변경\n"
        "/seed — 시드 및 누적 손익\n"
        "/watchlist — 관심종목 목록\n"
        "/start — 봇 시작\n"
        "/stop — 봇 중지",
        parse_mode="HTML",
    )


async def notify_nasdaq_open(positions: list[dict]) -> None:
    now = datetime.now().strftime("%H:%M")
    lines = [
        f"🌙 <b>나스닥 장 시작</b> ({now})",
        "NVDA / SNDK / AMZN 등 해외 종목 모니터링 시작.",
        f"보유종목: {len(positions)}개 / 4",
    ]
    if positions:
        for p in positions:
            pnl = p.get("pnl_pct", 0)
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  · {p['symbol']} {p['quantity']}주 ({sign}{pnl:.1f}%)")
    await _send("\n".join(lines))


async def run_polling() -> None:
    import asyncio as _asyncio
    app = _get_app()
    if app is None:
        logger.info("[Telegram] 토큰 없음, polling 생략")
        return
    for attempt in range(5):
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            logger.info("[Telegram] polling 시작")
            return
        except Exception as e:
            logger.warning(f"[Telegram] polling 시작 실패 (시도 {attempt+1}/5): {e}")
            await _asyncio.sleep(10 * (attempt + 1))
