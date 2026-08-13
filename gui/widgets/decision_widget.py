"""AI 판단 피드 위젯."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from gui.styles.theme import BG_TERTIARY, GREEN, RED, TEXT_SECONDARY, YELLOW


class DecisionWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 10, 8, 8)
        outer.setSpacing(6)

        title = QLabel("AI 판단 피드")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        scroll.setWidget(self._container)
        outer.addWidget(scroll)

    def update_decisions(self, decisions: list[dict]):
        # 기존 아이템 제거 (stretch 제외)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for d in reversed(decisions[:20]):
            card = _DecisionCard(d)
            self._list_layout.insertWidget(0, card)


class _DecisionCard(QFrame):
    _COLORS = {"BUY": GREEN, "SELL": RED, "HOLD": YELLOW}

    def __init__(self, data: dict):
        super().__init__()
        decision = data.get("decision", "HOLD")
        ticker = data.get("ticker", "-")
        confidence = data.get("confidence", 0)
        reason = data.get("reason", "")
        ts = data.get("timestamp", "")

        color = self._COLORS.get(decision, TEXT_SECONDARY)

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {BG_TERTIARY};
                border-left: 3px solid {color};
                border-radius: 4px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        # 헤더 행
        header_lbl = QLabel(f"{decision}  {ticker}  확신도 {confidence}%")
        header_lbl.setFont(QFont("Noto Sans KR", 11, QFont.Weight.Bold))
        header_lbl.setStyleSheet(f"color: {color};")
        layout.addWidget(header_lbl)

        # 근거
        if reason:
            reason_lbl = QLabel(reason[:120] + ("…" if len(reason) > 120 else ""))
            reason_lbl.setWordWrap(True)
            reason_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            layout.addWidget(reason_lbl)

        # 타임스탬프
        if ts:
            ts_lbl = QLabel(ts[11:19] if len(ts) >= 19 else ts)
            ts_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
            layout.addWidget(ts_lbl)
