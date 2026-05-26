"""System tray integration."""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget


class AppTray:
    """Minimal tray menu for show/hide and exit."""

    def __init__(self, panel: QWidget) -> None:
        self._panel = panel
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self._tray = QSystemTrayIcon(QIcon(icon), panel)

        menu = QMenu(panel)
        show_action = QAction("显示控制面板", panel)
        show_action.triggered.connect(panel.show)
        quit_action = QAction("退出", panel)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)

    def show(self) -> None:
        self._tray.show()
