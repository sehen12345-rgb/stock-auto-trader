"""다크 테마 QSS 상수."""

# 색상 팔레트
BG_PRIMARY    = "#1E1E2E"
BG_SECONDARY  = "#2A2A3E"
BG_TERTIARY   = "#333350"
BORDER_COLOR  = "#404058"
ACCENT        = "#5B9BD5"
GREEN         = "#26A69A"
RED           = "#EF5350"
YELLOW        = "#FFA726"
TEXT_PRIMARY  = "#FFFFFF"
TEXT_SECONDARY = "#A0A0B8"
TEXT_DISABLED  = "#606078"

DARK_THEME = f"""
QMainWindow, QWidget {{
    background-color: {BG_PRIMARY};
    color: {TEXT_PRIMARY};
    font-family: "Noto Sans KR", "맑은 고딕", sans-serif;
    font-size: 12px;
}}
QSplitter::handle {{
    background-color: {BORDER_COLOR};
    width: 1px;
    height: 1px;
}}
QTableWidget {{
    background-color: {BG_SECONDARY};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    gridline-color: {BORDER_COLOR};
    outline: 0;
}}
QTableWidget::item {{
    padding: 4px 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {BG_TERTIARY};
    color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background-color: {BG_TERTIARY};
    color: {TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {BORDER_COLOR};
    padding: 4px 8px;
    font-size: 11px;
}}
QHeaderView::section:horizontal {{
    border-right: 1px solid {BORDER_COLOR};
}}
QScrollBar:vertical {{
    background-color: {BG_SECONDARY};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background-color: {BORDER_COLOR};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background-color: {BG_SECONDARY};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background-color: {BORDER_COLOR};
    border-radius: 4px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QPushButton {{
    background-color: {ACCENT};
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: #6AAAE4;
}}
QPushButton:pressed {{
    background-color: #4A8AC4;
}}
QPushButton:disabled {{
    background-color: {BG_TERTIARY};
    color: {TEXT_DISABLED};
}}
QPushButton#startBtn {{
    background-color: {GREEN};
}}
QPushButton#startBtn:hover {{
    background-color: #30B8AB;
}}
QPushButton#stopBtn {{
    background-color: {RED};
}}
QPushButton#stopBtn:hover {{
    background-color: #F76360;
}}
QComboBox {{
    background-color: {BG_TERTIARY};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_SECONDARY};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_COLOR};
    selection-background-color: {BG_TERTIARY};
}}
QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}
QLabel#sectionTitle {{
    color: {TEXT_SECONDARY};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QTextEdit {{
    background-color: {BG_SECONDARY};
    color: {TEXT_SECONDARY};
    border: none;
    font-family: "D2Coding", "Consolas", monospace;
    font-size: 11px;
}}
QStatusBar {{
    background-color: {BG_SECONDARY};
    color: {TEXT_SECONDARY};
    font-size: 11px;
    border-top: 1px solid {BORDER_COLOR};
}}
QFrame#panel {{
    background-color: {BG_SECONDARY};
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
}}
QFrame#header {{
    background-color: {BG_SECONDARY};
    border-bottom: 1px solid {BORDER_COLOR};
}}
"""
