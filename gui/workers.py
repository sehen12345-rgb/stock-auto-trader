"""QThread 기반 엔진 워커 — asyncio 루프를 별도 스레드에서 실행."""

import asyncio
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal


class EngineWorker(QThread):
    """TradingEngine을 asyncio 이벤트 루프와 함께 백그라운드 스레드에서 실행."""

    status_changed = pyqtSignal(str)          # 상태 메시지
    watchlist_updated = pyqtSignal(list)      # 관심종목 데이터
    portfolio_updated = pyqtSignal(dict)      # 포트폴리오 요약
    positions_updated = pyqtSignal(list)      # 보유 포지션
    decisions_updated = pyqtSignal(list)      # AI 판단 목록
    error_occurred = pyqtSignal(str)          # 에러 메시지

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    # ── 공개 API (GUI 스레드에서 호출) ──────────────────────────
    def start_engine(self):
        if not self.isRunning():
            self.start()

    def stop_engine(self):
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def set_mode(self, mode: str):
        if self._loop:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._set_mode(mode), loop=self._loop)
            )

    # ── QThread.run() ────────────────────────────────────────────
    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._running = True
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self._loop.close()
            self._loop = None

    # ── 내부 비동기 메서드 ────────────────────────────────────────
    async def _main(self):
        from core.engine import TradingEngine
        engine = TradingEngine()
        await engine.start()
        self.status_changed.emit("실행 중")

        try:
            while self._running:
                await self._refresh(engine)
                await asyncio.sleep(5)
        finally:
            await engine.stop()
            self.status_changed.emit("중지됨")

    async def _refresh(self, engine):
        try:
            watchlist = await engine.get_watchlist()
            self.watchlist_updated.emit(watchlist)
        except Exception:
            pass

        try:
            portfolio = await engine.get_portfolio()
            self.portfolio_updated.emit(portfolio)
        except Exception:
            pass

        try:
            positions = await engine.get_positions()
            self.positions_updated.emit(positions)
        except Exception:
            pass

        try:
            decisions = engine.get_recent_decisions(30)
            self.decisions_updated.emit(decisions)
        except Exception:
            pass

    async def _set_mode(self, mode: str):
        from core.engine import TradingEngine
        try:
            TradingEngine().set_trading_mode(mode)
            self.status_changed.emit(f"모드 변경: {mode}")
        except Exception as e:
            self.error_occurred.emit(str(e))
