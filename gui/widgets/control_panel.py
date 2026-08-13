"""상단 컨트롤 패널 — 시작/중지, 매매 모드 선택, 상태 표시."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from gui.styles.theme import (
    ACCENT, BG_SECONDARY, BORDER_COLOR, GREEN, RED, TEXT_PRIMARY, TEXT_SECONDARY,
)


class ControlPanel(QFrame):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(54)
        self._build()

    def _build(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        # 타이틀
        title = QLabel("주식 자동매매 시스템")
        title.setFont(QFont("Noto Sans KR", 13, QFont.Weight.Bold))
        row.addWidget(title)

        row.addStretch()

        # 시장 상태 인디케이터
        for label, color in [("KOSPI ●", GREEN), ("NASDAQ ●", ACCENT)]:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {color}; font-size: 12px;")
            row.addWidget(lbl)

        # 구분선
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {BORDER_COLOR};")
        row.addWidget(sep)

        # 매매 모드 선택
        mode_lbl = QLabel("모드:")
        mode_lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        row.addWidget(mode_lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.setFixedWidth(120)
        self._mode_combo.addItems(["long_term", "swing", "day_trading", "scalping"])
        self._mode_combo.currentTextChanged.connect(self.mode_changed.emit)
        row.addWidget(self._mode_combo)

        # 시작 버튼
        self._start_btn = QPushButton("▶ 시작")
        self._start_btn.setObjectName("startBtn")
        self._start_btn.setFixedWidth(80)
        self._start_btn.clicked.connect(self._on_start)
        row.addWidget(self._start_btn)

        # 중지 버튼
        self._stop_btn = QPushButton("■ 중지")
        self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.setFixedWidth(80)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        row.addWidget(self._stop_btn)

        # 상태 레이블
        self._status_lbl = QLabel("● 대기")
        self._status_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        self._status_lbl.setFixedWidth(80)
        row.addWidget(self._status_lbl)

    def _on_start(self):
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._mode_combo.setEnabled(False)
        self.set_status("시작 중…", ACCENT)
        self.start_requested.emit()

    def _on_stop(self):
        self._stop_btn.setEnabled(False)
        self.set_status("중지 중…", "#FFA726")
        self.stop_requested.emit()

    def set_status(self, text: str, color: str = TEXT_SECONDARY):
        self._status_lbl.setText(f"● {text}")
        self._status_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")

    def on_engine_stopped(self):
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._mode_combo.setEnabled(True)
        self.set_status("중지됨", RED)
