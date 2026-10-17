"""Entry point: python main.py"""
from __future__ import annotations

import multiprocessing
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from PyQt6.QtWidgets import QApplication

from ytd_app.ui import MainWindow, setup_app
from ytd_app.version import setup_bundled_environment


def main():
    multiprocessing.freeze_support()
    setup_bundled_environment()
    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Desktop Downloader")
    app.setOrganizationName("LocalTools")
    setup_app(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
