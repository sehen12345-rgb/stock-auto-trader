from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStatusBar, QPushButton, QSplitter
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from config.constants import APP_NAME, APP_VERSION


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1400, 900)
        self._apply_dark_theme()
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        layout.addWidget(self._build_body(), stretch=1)
        layout.addWidget(self._build_log_panel())

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("시스템 준비 완료")

    def _build_header(self):
        header = QWidget()
        header.setFixedHeight(50)
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 0, 16, 0)

        title = QLabel(APP_NAME)
        title.setFont(QFont("Noto Sans KR", 14, QFont.Weight.Bold))
        row.addWidget(title)
        row.addStretch()

        for label, color in [("KOSPI ●", "#26A69A"), ("NASDAQ ●", "#5B9BD5")]:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {color}; font-size: 13px;")
            row.addWidget(lbl)

        settings_btn = QPushButton("⚙ 설정")
        settings_btn.setFixedWidth(80)
        row.addWidget(settings_btn)

        return header

    def _build_body(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QLabel("관심종목\n(개발 예정)")
        left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.setFixedWidth(220)
        left.setObjectName("panel")
        splitter.addWidget(left)

        center = QLabel("실시간 차트\n(개발 예정)")
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.setObjectName("panel")
        splitter.addWidget(center)

        right = QLabel("포트폴리오\n(개발 예정)")
        right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.setFixedWidth(280)
        right.setObjectName("panel")
        splitter.addWidget(right)

        splitter.setStretchFactor(1, 1)
        return splitter

    def _build_log_panel(self):
        log = QLabel("로그 패널 (개발 예정)")
        log.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        log.setFixedHeight(120)
        log.setObjectName("logPanel")
        log.setContentsMargins(10, 0, 0, 0)
        return log

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1E1E2E;
                color: #FFFFFF;
                font-family: "Noto Sans KR", sans-serif;
            }
            #header {
                background-color: #2A2A3E;
                border-bottom: 1px solid #404058;
            }
            #panel {
                background-color: #2A2A3E;
                border: 1px solid #404058;
                border-radius: 8px;
                margin: 4px;
                color: #A0A0B8;
                font-size: 13px;
            }
            #logPanel {
                background-color: #2A2A3E;
                border-top: 1px solid #404058;
                color: #A0A0B8;
                font-size: 12px;
            }
            QPushButton {
                background-color: #5B9BD5;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #6AAAE4;
            }
            QStatusBar {
                background-color: #2A2A3E;
                color: #A0A0B8;
                font-size: 11px;
            }
        """)
