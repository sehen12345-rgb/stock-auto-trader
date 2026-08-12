import asyncio
from datetime import datetime
from typing import Any

from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_app: Application | None = None


def _get_app() -> Application | None:
    global _app
    if _app is None and TELEGRAM_BOT_TOKEN:
        _app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        _register_handlers(_app)
    return _app


def _register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))


async def _send(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug(f"[Telegram] 설정 없음, 건너뜀: {text[:50]}")
        return
    app = _get_app()
    if app is None:
        return
    try:
        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"[Telegram] 전송 실패: {e}")


async def notify_start() -> None:
    await _send("🟢 <b>봇 시작</b>\n장 모니터링을 시작합니다.")


async def notify_stop() -> None:
    await _send("🔴 <b>봇 중지</b>\n킬스위치 발동.")


async def notify_trade(action: str, ticker: str, qty: int, reason: str) -> None:
    emoji = "📈" if action == "BUY" else "📉"
    text = (
        f"{emoji} <b>{action} 체결</b>\n"
        f"종목: {ticker}\n"
        f"수량: {qty}주\n"
        f"근거: {reason}"
    )
    await _send(text)


async def notify_positions(positions: list[dict[str, Any]]) -> None:
    if not positions:
        await _send("📊 <b>보유 포지션 없음</b>")
        return
    lines = ["📊 <b>현재 포지션</b>"]
    for p in positions:
        pnl = p.get("pnl_pct", 0)
        sign = "+" if pnl >= 0 else ""
        lines.append(f"  {p['symbol']}: {p['quantity']}주 ({sign}{pnl:.1f}%)")
    await _send("\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core.engine import TradingEngine
    engine = TradingEngine()
    status = "가동중 🟢" if engine.running else "중지 🔴"
    mode = "모의" if engine.is_paper else "실전"
    positions = await engine.get_positions()
    await update.message.reply_text(
        f"<b>봇 상태</b>: {status}\n"
        f"<b>모드</b>: {mode}\n"
        f"<b>보유 종목</b>: {len(positions)}개\n"
        f"<b>LLM 호출</b>: {engine.llm_call_count}회",
        parse_mode="HTML",
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core.engine import TradingEngine
    engine = TradingEngine()
    if engine.running:
        await engine.stop()
        await update.message.reply_text("🔴 봇을 중지했습니다.")
    else:
        await update.message.reply_text("이미 중지 상태입니다.")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from core.engine import TradingEngine
    engine = TradingEngine()
    pf = await engine.get_portfolio()
    sign = "+" if pf.get("return_pct", 0) >= 0 else ""
    await update.message.reply_text(
        f"<b>포트폴리오</b>\n"
        f"총평가액: {pf.get('total_value', 0):,.0f}원\n"
        f"현금: {pf.get('cash', 0):,.0f}원\n"
        f"수익률: {sign}{pf.get('return_pct', 0):.2f}%",
        parse_mode="HTML",
    )


async def run_polling() -> None:
    app = _get_app()
    if app is None:
        logger.warning("[Telegram] 토큰 없음, polling 생략")
        return
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("[Telegram] polling 시작")
