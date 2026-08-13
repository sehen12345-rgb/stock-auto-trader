"""관심종목 실시간 시세 테이블."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from gui.styles.theme import BG_SECONDARY, GREEN, RED, TEXT_SECONDARY, YELLOW


class WatchlistWidget(QFrame):
    HEADERS = ["종목", "현재가", "52주고점", "이격도", "거래량비"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedWidth(240)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        title = QLabel("관심종목")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self._table = QTableWidget(0, len(self.HEADERS))
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setShowGrid(False)

        # 컬럼 너비
        self._table.setColumnWidth(0, 70)   # 종목
        self._table.setColumnWidth(1, 70)   # 현재가
        self._table.setColumnWidth(2, 60)   # 52주고점
        self._table.setColumnWidth(3, 50)   # 이격도
        self._table.setColumnWidth(4, 50)   # 거래량비
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

    def update_data(self, items: list[dict]):
        self._table.setRowCount(len(items))
        for row, item in enumerate(items):
            ticker = item.get("ticker", "")
            name = item.get("name", ticker)
            price = item.get("current_price")
            high52 = item.get("week52_high")
            pct_from_high = item.get("pct_from_high")
            vol_ratio = item.get("volume_ratio")

            label = name if len(name) <= 6 else ticker
            self._set(row, 0, label, align=Qt.AlignmentFlag.AlignLeft)
            self._set(row, 1, _fmt_price(price))
            self._set(row, 2, _fmt_price(high52))

            if pct_from_high is not None:
                color = GREEN if pct_from_high < 5 else (YELLOW if pct_from_high < 15 else TEXT_SECONDARY)
                self._set(row, 3, f"-{pct_from_high:.1f}%", color=color)
            else:
                self._set(row, 3, "-")

            if vol_ratio is not None:
                color = GREEN if vol_ratio >= 2.0 else TEXT_SECONDARY
                self._set(row, 4, f"{vol_ratio:.1f}x", color=color)
            else:
                self._set(row, 4, "-")

        self._table.setRowHeight(row, 26) if items else None

    def _set(self, row, col, text, color=None, align=Qt.AlignmentFlag.AlignRight):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        if color:
            item.setForeground(QColor(color))
        self._table.setItem(row, col, item)
        self._table.setRowHeight(row, 26)


def _fmt_price(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float) and v > 0:
        return f"{v:,.0f}" if v >= 100 else f"{v:.2f}"
    if isinstance(v, int) and v > 0:
        return f"{v:,}"
    return "-"
