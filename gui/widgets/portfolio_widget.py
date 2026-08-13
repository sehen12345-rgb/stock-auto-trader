"""포트폴리오 요약 + 보유 포지션 테이블."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from gui.styles.theme import (
    BG_TERTIARY, GREEN, RED, TEXT_PRIMARY, TEXT_SECONDARY, YELLOW,
)


class PortfolioWidget(QFrame):
    POS_HEADERS = ["종목", "수량", "평균가", "현재가", "손익%"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedWidth(300)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        title = QLabel("포트폴리오")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # 요약 카드
        self._summary = _SummaryCard()
        layout.addWidget(self._summary)

        # 포지션 테이블
        pos_title = QLabel("보유 종목")
        pos_title.setObjectName("sectionTitle")
        layout.addWidget(pos_title)

        self._pos_table = QTableWidget(0, len(self.POS_HEADERS))
        self._pos_table.setHorizontalHeaderLabels(self.POS_HEADERS)
        self._pos_table.verticalHeader().setVisible(False)
        self._pos_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pos_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pos_table.setShowGrid(False)
        self._pos_table.setColumnWidth(0, 60)
        self._pos_table.setColumnWidth(1, 40)
        self._pos_table.setColumnWidth(2, 60)
        self._pos_table.setColumnWidth(3, 60)
        self._pos_table.setColumnWidth(4, 55)
        self._pos_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._pos_table)

    def update_portfolio(self, data: dict):
        self._summary.update(data)

    def update_positions(self, positions: list[dict]):
        self._pos_table.setRowCount(len(positions))
        for row, pos in enumerate(positions):
            sym = pos.get("symbol", "")
            qty = pos.get("quantity", 0)
            avg = pos.get("avg_price", 0)
            cur = pos.get("current_price", 0)
            pnl = pos.get("pnl_pct", 0.0)

            color = GREEN if pnl >= 0 else RED
            pnl_str = f"+{pnl:.2f}%" if pnl >= 0 else f"{pnl:.2f}%"

            self._set(row, 0, sym, align=Qt.AlignmentFlag.AlignLeft)
            self._set(row, 1, str(qty))
            self._set(row, 2, _fmt(avg))
            self._set(row, 3, _fmt(cur))
            self._set(row, 4, pnl_str, color=color)

    def _set(self, row, col, text, color=None, align=Qt.AlignmentFlag.AlignRight):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        if color:
            item.setForeground(QColor(color))
        self._pos_table.setItem(row, col, item)
        self._pos_table.setRowHeight(row, 26)


class _SummaryCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background-color: {BG_TERTIARY}; border-radius: 6px; border: none;")
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(4)

        def _lbl(text, bold=False):
            l = QLabel(text)
            if bold:
                l.setFont(QFont("Noto Sans KR", 12, QFont.Weight.Bold))
            else:
                l.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            return l

        grid.addWidget(_lbl("총 평가액"), 0, 0)
        self._total = _lbl("- 원", bold=True)
        grid.addWidget(self._total, 0, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(_lbl("현금"), 1, 0)
        self._cash = _lbl("-")
        grid.addWidget(self._cash, 1, 1, Qt.AlignmentFlag.AlignRight)

        grid.addWidget(_lbl("수익률"), 2, 0)
        self._return = _lbl("-")
        grid.addWidget(self._return, 2, 1, Qt.AlignmentFlag.AlignRight)

    def update(self, data: dict):
        total = data.get("total_value", 0)
        cash = data.get("cash", 0)
        ret = data.get("return_pct", 0.0)

        self._total.setText(f"{total:,.0f} 원" if total else "- 원")
        self._cash.setText(f"{cash:,.0f} 원" if cash else "-")

        if ret is not None:
            color = GREEN if ret >= 0 else RED
            sign = "+" if ret >= 0 else ""
            self._return.setText(f"{sign}{ret:.2f}%")
            self._return.setStyleSheet(f"color: {color}; font-size: 12px;")
        else:
            self._return.setText("-")


def _fmt(v) -> str:
    if not v:
        return "-"
    return f"{v:,.0f}" if v >= 100 else f"{v:.2f}"
