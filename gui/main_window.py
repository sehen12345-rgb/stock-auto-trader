"""메인 윈도우 — 모든 위젯을 조립하고 EngineWorker와 연결."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

from config.constants import APP_NAME, APP_VERSION
from gui.styles.theme import DARK_THEME, GREEN, RED, TEXT_SECONDARY
from gui.widgets.control_panel import ControlPanel
from gui.widgets.decision_widget import DecisionWidget
from gui.widgets.log_widget import LogWidget
from gui.widgets.portfolio_widget import PortfolioWidget
from gui.widgets.watchlist_widget import WatchlistWidget
from gui.workers import EngineWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1400, 900)
        self.setStyleSheet(DARK_THEME)

        self._worker: EngineWorker | None = None
        self._build_ui()
        self._connect_signals()

        # 5초마다 상태바 시각 갱신
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(5000)

    # ── UI 조립 ────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # 상단 컨트롤 패널
        self._ctrl = ControlPanel()
        vbox.addWidget(self._ctrl)

        # 중앙 콘텐츠 영역
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)

        self._watchlist = WatchlistWidget()
        body.addWidget(self._watchlist)

        self._decision = DecisionWidget()
        body.addWidget(self._decision)

        self._portfolio = PortfolioWidget()
        body.addWidget(self._portfolio)

        body.setStretchFactor(1, 1)
        vbox.addWidget(body, stretch=1)

        # 하단 로그 패널
        self._log = LogWidget()
        vbox.addWidget(self._log)

        # 상태바
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("준비 완료 — 시작 버튼을 눌러 봇을 실행하세요.")

    # ── 시그널 연결 ────────────────────────────────────────────────
    def _connect_signals(self):
        self._ctrl.start_requested.connect(self._start_engine)
        self._ctrl.stop_requested.connect(self._stop_engine)
        self._ctrl.mode_changed.connect(self._on_mode_change)

    def _start_engine(self):
        self._worker = EngineWorker(self)
        self._worker.status_changed.connect(self._on_status)
        self._worker.watchlist_updated.connect(self._watchlist.update_data)
        self._worker.portfolio_updated.connect(self._portfolio.update_portfolio)
        self._worker.positions_updated.connect(self._portfolio.update_positions)
        self._worker.decisions_updated.connect(self._decision.update_decisions)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._ctrl.on_engine_stopped)

        self._log.install_loguru_sink()
        self._worker.start_engine()
        self._ctrl.set_status("실행 중", GREEN)
        self._status_bar.showMessage("봇 실행 중…")

    def _stop_engine(self):
        if self._worker:
            self._worker.stop_engine()
        self._status_bar.showMessage("봇 중지 요청됨.")

    def _on_mode_change(self, mode: str):
        if self._worker and self._worker.isRunning():
            self._worker.set_mode(mode)

    def _on_status(self, msg: str):
        self._ctrl.set_status(msg, GREEN if "실행" in msg else TEXT_SECONDARY)
        self._status_bar.showMessage(msg)

    def _on_error(self, msg: str):
        self._ctrl.set_status("오류", RED)
        self._status_bar.showMessage(f"오류: {msg}")

    def _tick_clock(self):
        from datetime import datetime
        now = datetime.now().strftime("%H:%M")
        running = self._worker and self._worker.isRunning()
        state = "실행 중" if running else "중지됨"
        self._status_bar.showMessage(f"{now}  |  봇 {state}")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop_engine()
            self._worker.wait(3000)
        event.accept()
