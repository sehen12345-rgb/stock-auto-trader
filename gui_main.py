"""PyQt6 앱 진입점."""

import sys

from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("주식 자동매매 시스템")
    app.setOrganizationName("StockAutoTrader")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
