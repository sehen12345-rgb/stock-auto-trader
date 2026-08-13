"""시스템 로그 패널 — loguru 싱크 연동."""

import sys

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout

from gui.styles.theme import GREEN, RED, TEXT_SECONDARY, YELLOW


class LogWidget(QFrame):
    """하단 고정 높이 로그 패널."""

    log_received = pyqtSignal(str, str)   # (level, message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedHeight(130)
        self._build()
        self.log_received.connect(self._append)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("시스템 로그")
        title.setObjectName("sectionTitle")
        hdr.addWidget(title)
        hdr.addStretch()
        layout.addLayout(hdr)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._text)

    def _append(self, level: str, message: str):
        level = level.upper()
        color_map = {
            "DEBUG":   TEXT_SECONDARY,
            "INFO":    "#FFFFFF",
            "SUCCESS": GREEN,
            "WARNING": YELLOW,
            "ERROR":   RED,
            "CRITICAL": RED,
        }
        color = color_map.get(level, TEXT_SECONDARY)
        html = f'<span style="color:{color}; font-family:Consolas,monospace; font-size:11px;">{message}</span>'
        self._text.append(html)

        # 최대 500줄 유지
        doc = self._text.document()
        while doc.blockCount() > 500:
            cursor = QTextCursor(doc.begin())
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

        self._text.moveCursor(QTextCursor.MoveOperation.End)

    def install_loguru_sink(self):
        """loguru 로그를 이 위젯으로 리다이렉트."""
        try:
            from loguru import logger
            logger.add(
                self._loguru_sink,
                format="{time:HH:mm:ss} [{level}] {message}",
                level="DEBUG",
                colorize=False,
            )
        except ImportError:
            pass

    def _loguru_sink(self, message):
        record = message.record
        level = record["level"].name
        formatted = message
        self.log_received.emit(level, str(formatted).strip())
