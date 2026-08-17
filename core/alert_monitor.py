"""
가격 알림 모니터 — 백그라운드 루프
60초마다 활성 알림 체크 → 조건 달성 시 텔레그램 전송
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from loguru import logger

from database.alert_repo import AlertRepository


class AlertMonitor:
    INTERVAL = 60
    RESEND_COOLDOWN = 1800

    def __init__(self, fetcher: Any) -> None:
        self.fetcher = fetcher
        self.repo = AlertRepository()
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_sent: dict[int, datetime] = {}
        self._last_reset_date: date = date.today()
        self._market_alert_sent: dict[str, date] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[AlertMonitor] 가격 알림 모니터 시작")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_alerts()
                await self._check_market_moves()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AlertMonitor] 루프 오류: {e}")
            await asyncio.sleep(self.INTERVAL)

    def _maybe_reset_daily(self) -> None:
        today = date.today()
        if today != self._last_reset_date:
            self.repo.reset_daily()
            self._last_sent.clear()
            self._market_alert_sent.clear()
            self._last_reset_date = today
            logger.info("[AlertMonitor] 일일 알림 리셋")

    async def _check_alerts(self) -> None:
        self._maybe_reset_daily()
        alerts = self.repo.find_active()
        if not alerts:
            return

        by_ticker: dict[str, list[dict]] = {}
        for a in alerts:
            by_ticker.setdefault(a["ticker"], []).append(a)

        for ticker, ticker_alerts in by_ticker.items():
            try:
                data = await self.fetcher.fetch(ticker)
                price = data.get("current_price", 0)
                change_pct = data.get("change_pct", 0)
                if price <= 0:
                    continue
                for alert in ticker_alerts:
                    await self._evaluate(alert, price, change_pct)
                    await asyncio.sleep(0.3)
            except Exception as e:
                logger.debug(f"[AlertMonitor] {ticker} 조회 실패: {e}")

    async def _evaluate(self, alert: dict, price: float, change_pct: float) -> None:
        aid = alert["id"]
        atype = alert["alert_type"]
        target = alert.get("target_price", 0)
        chg_threshold = alert.get("change_pct", 0)

        triggered = False
        direction = ""

        if atype == "ABOVE" and target > 0 and price >= target:
            triggered = True
            direction = f"현재가 {price:,.2f} ≥ 목표가 {target:,.2f}"
        elif atype == "BELOW" and target > 0 and price <= target:
            triggered = True
            direction = f"현재가 {price:,.2f} ≤ 목표가 {target:,.2f}"
        elif atype == "CHANGE_PCT" and chg_threshold != 0:
            if chg_threshold > 0 and change_pct >= chg_threshold:
                triggered = True
                direction = f"등락률 +{change_pct:.1f}% ≥ +{chg_threshold:.1f}%"
            elif chg_threshold < 0 and change_pct <= chg_threshold:
                triggered = True
                direction = f"등락률 {change_pct:.1f}% ≤ {chg_threshold:.1f}%"

        if not triggered:
            return

        now = datetime.now()
        last = self._last_sent.get(aid)
        if last and (now - last).total_seconds() < self.RESEND_COOLDOWN:
            return

        self._last_sent[aid] = now
        self.repo.mark_triggered(aid)
        await self._send_price_alert(alert, price, direction)

    async def _send_price_alert(self, alert: dict, current_price: float, direction: str) -> None:
        from notifications.telegram_bot import notify_price_alert
        await notify_price_alert(
            ticker=alert["ticker"],
            name=alert.get("name", ""),
            alert_type=alert["alert_type"],
            target_price=alert.get("target_price", 0),
            current_price=current_price,
            direction=direction,
            memo=alert.get("memo", ""),
        )

    async def _check_market_moves(self) -> None:
        try:
            import yfinance as yf
            today = date.today()
            checks = [("^KS11", "KOSPI", -2.0), ("^IXIC", "NASDAQ", -2.0), ("^GSPC", "S&P500", -2.0)]
            for sym, label, threshold in checks:
                key = f"market_{sym}"
                if self._market_alert_sent.get(key) == today:
                    continue
                try:
                    t = yf.Ticker(sym)
                    info = t.fast_info
                    prev_close = getattr(info, "previous_close", 0) or 0
                    last_price = getattr(info, "last_price", 0) or 0
                    if prev_close <= 0 or last_price <= 0:
                        continue
                    pct = (last_price - prev_close) / prev_close * 100
                    if pct <= threshold:
                        self._market_alert_sent[key] = today
                        await self._send_market_alert(label, last_price, pct)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[AlertMonitor] 시장 체크 실패: {e}")

    async def _send_market_alert(self, label: str, price: float, pct: float) -> None:
        from notifications.telegram_bot import _send
        sign = "+" if pct >= 0 else ""
        await _send(
            f"📉 <b>[시장 급락 알림]</b>\n"
            f"지수: <b>{label}</b>\n"
            f"현재: {price:,.2f}\n"
            f"등락: <b>{sign}{pct:.2f}%</b>\n"
            f"시각: {datetime.now().strftime('%H:%M')}\n"
            f"💡 매수 기회일 수 있습니다. 확인해 보세요!"
        )
