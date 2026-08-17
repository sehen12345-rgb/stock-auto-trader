"""APScheduler 기반 자동매매 스케줄러.

장 시작/종료 알림, 일일 리포트, 경제 이벤트 알림을 자동 처리한다.
engine.start() 호출 후 setup_scheduler(engine)을 실행해 등록한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from core.engine import TradingEngine

_scheduler: Any = None


def setup_scheduler(engine: "TradingEngine") -> None:
    """APScheduler 스케줄러 초기화 및 작업 등록."""
    global _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

        # ── 코스피 장 시작 (09:00) ────────────────────────────────────────────
        _scheduler.add_job(
            _job_kospi_open, CronTrigger(hour=9, minute=0, day_of_week="mon-fri"),
            args=[engine], id="kospi_open", replace_existing=True,
        )

        # ── 코스피 장 마감 전 리포트 (15:25) ─────────────────────────────────
        _scheduler.add_job(
            _job_kospi_close, CronTrigger(hour=15, minute=25, day_of_week="mon-fri"),
            args=[engine], id="kospi_close", replace_existing=True,
        )

        # ── 나스닥 장 시작 (22:30 KST) ───────────────────────────────────────
        _scheduler.add_job(
            _job_nasdaq_open, CronTrigger(hour=22, minute=30, day_of_week="mon-fri"),
            args=[engine], id="nasdaq_open", replace_existing=True,
        )

        # ── 나스닥 장 마감 (05:00 KST 다음날) ────────────────────────────────
        _scheduler.add_job(
            _job_nasdaq_close, CronTrigger(hour=5, minute=0, day_of_week="tue-sat"),
            args=[engine], id="nasdaq_close", replace_existing=True,
        )

        # ── 경제 이벤트 아침 알림 (08:30) ────────────────────────────────────
        _scheduler.add_job(
            _job_econ_alert, CronTrigger(hour=8, minute=30, day_of_week="mon-fri"),
            args=[engine], id="econ_alert", replace_existing=True,
        )

        # ── 주간 성과 리포트 (매주 금요일 16:00) ─────────────────────────────
        _scheduler.add_job(
            _job_weekly_report, CronTrigger(hour=16, minute=0, day_of_week="fri"),
            args=[engine], id="weekly_report", replace_existing=True,
        )

        _scheduler.start()
        logger.info("[Scheduler] APScheduler 시작 완료 (6개 작업 등록)")

    except ImportError:
        logger.warning("[Scheduler] APScheduler 미설치 — pip install APScheduler")
    except Exception as e:
        logger.warning(f"[Scheduler] 초기화 실패: {e}")


def shutdown_scheduler() -> None:
    """스케줄러 종료."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] 종료")


# ── 스케줄 작업 함수들 ────────────────────────────────────────────────────────

async def _job_kospi_open(engine: "TradingEngine") -> None:
    """코스피 장 시작 알림 + 올랜도킴 리포트."""
    try:
        from notifications.telegram_bot import notify_market_open, notify_daily_orlando
        positions = await engine.get_positions()
        await notify_market_open(positions)
        market_data = getattr(engine, "_last_market_data", {})
        await notify_daily_orlando(market_data)
        logger.info("[Scheduler] 코스피 장 시작 알림 전송")
    except Exception as e:
        logger.warning(f"[Scheduler] kospi_open 실패: {e}")


async def _job_kospi_close(engine: "TradingEngine") -> None:
    """코스피 장 마감 리포트."""
    try:
        from notifications.telegram_bot import notify_market_close
        portfolio = await engine.get_portfolio()
        positions = await engine.get_positions()
        await notify_market_close(portfolio, positions, engine._daily_loss)
        logger.info("[Scheduler] 코스피 장 마감 리포트 전송")
    except Exception as e:
        logger.warning(f"[Scheduler] kospi_close 실패: {e}")


async def _job_nasdaq_open(engine: "TradingEngine") -> None:
    """나스닥 장 시작 알림."""
    try:
        from notifications.telegram_bot import notify_nasdaq_open, notify_daily_orlando
        positions = await engine.get_positions()
        await notify_nasdaq_open(positions)
        market_data = getattr(engine, "_last_market_data", {})
        await notify_daily_orlando(market_data)
        logger.info("[Scheduler] 나스닥 장 시작 알림 전송")
    except Exception as e:
        logger.warning(f"[Scheduler] nasdaq_open 실패: {e}")


async def _job_nasdaq_close(engine: "TradingEngine") -> None:
    """나스닥 장 마감 요약."""
    try:
        from notifications.telegram_bot import _send
        portfolio = await engine.get_portfolio()
        total = portfolio.get("total_value", 0)
        ret = portfolio.get("return_pct", 0)
        sign = "+" if ret >= 0 else ""
        now = datetime.now().strftime("%m/%d %H:%M")
        await _send(
            f"🌅 <b>나스닥 장 마감</b> ({now})\n"
            f"총평가액: {total:,.0f}원\n"
            f"누적수익률: {sign}{ret:.2f}%\n"
            f"오늘 손익: {'+' if engine._daily_loss >= 0 else ''}{engine._daily_loss:,.0f}원"
        )
        logger.info("[Scheduler] 나스닥 장 마감 알림 전송")
    except Exception as e:
        logger.warning(f"[Scheduler] nasdaq_close 실패: {e}")


async def _job_econ_alert(engine: "TradingEngine") -> None:
    """오늘 고영향 경제 이벤트 아침 알림."""
    try:
        from core.econ_calendar import get_upcoming_events
        from notifications.telegram_bot import _send

        events = get_upcoming_events(days_ahead=3)
        if not events:
            return

        now = datetime.now().strftime("%m/%d")
        lines = [f"📅 <b>경제 이벤트 알림</b> ({now})", ""]
        for e in events[:5]:
            impact_emoji = "🔴" if e["impact"] == "high" else "🟡"
            lines.append(
                f"{impact_emoji} <b>{e['event']}</b>\n"
                f"   날짜: {e['date']} | {e.get('country', 'US')}\n"
            )

        high_today = [e for e in events if e["date"] == datetime.now().strftime("%Y-%m-%d")]
        if high_today:
            lines.append("⚠️ <b>오늘 고영향 이벤트 → 신규 매수 자동 차단</b>")

        await _send("\n".join(lines))
        logger.info(f"[Scheduler] 경제 이벤트 알림: {len(events)}건")
    except Exception as e:
        logger.warning(f"[Scheduler] econ_alert 실패: {e}")


async def _job_weekly_report(engine: "TradingEngine") -> None:
    """주간 성과 리포트 (금요일 16:00)."""
    try:
        from notifications.telegram_bot import _send
        from database.models import TradeRepository
        from database.db import get_db
        import datetime as _dt

        repo = TradeRepository(get_db())
        today = _dt.date.today()
        week_pnl = 0.0
        trade_count = 0

        for i in range(5):
            d = today - _dt.timedelta(days=i)
            date_str = d.strftime("%Y-%m-%d")
            week_pnl += repo.daily_pnl(date_str)
            trades = repo.find_by_date(date_str)
            trade_count += len([t for t in trades if t.side == "SELL" and t.status == "FILLED"])

        portfolio = await engine.get_portfolio()
        total = portfolio.get("total_value", 0)
        ret = portfolio.get("return_pct", 0)
        sign_w = "+" if week_pnl >= 0 else ""
        sign_t = "+" if ret >= 0 else ""
        emoji = "📈" if week_pnl >= 0 else "📉"

        await _send(
            f"{emoji} <b>주간 성과 리포트</b>\n"
            f"이번 주 손익: {sign_w}{week_pnl:,.0f}원\n"
            f"이번 주 매매: {trade_count}건\n"
            f"누적 수익률: {sign_t}{ret:.2f}%\n"
            f"총 평가액: {total:,.0f}원\n"
            f"매매 모드: {engine.trading_mode}"
        )
        logger.info("[Scheduler] 주간 리포트 전송")
    except Exception as e:
        logger.warning(f"[Scheduler] weekly_report 실패: {e}")
