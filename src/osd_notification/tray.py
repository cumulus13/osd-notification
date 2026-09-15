#!/usr/bin/env python3
"""
File: tray.py
Description: System tray integration for osd-notification. Provides a
             QSystemTrayIcon with a context menu (test notification,
             start/stop servers, open config, quit), a generated fallback
             icon when no icon file is configured, and native OS balloon
             messages as an optional secondary notification path.
License: MIT
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon, QWidget

from .config import OSDConfigManager
from .logging_setup import get_logger

logger = get_logger("OSDNotifier.Tray")

_FALLBACK_ICON_SIZE = 64


def _build_fallback_icon(color: str = "#89B4FA") -> QIcon:
    """Render a simple filled-circle icon in-memory so the tray never
    depends on a bundled icon asset that might be missing."""
    pixmap = QPixmap(_FALLBACK_ICON_SIZE, _FALLBACK_ICON_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))  # transparent background

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(QColor(color).darker(130))
        margin = 4
        painter.drawEllipse(margin, margin,
                             _FALLBACK_ICON_SIZE - 2 * margin,
                             _FALLBACK_ICON_SIZE - 2 * margin)
    finally:
        painter.end()

    return QIcon(pixmap)


def _load_icon(config: OSDConfigManager) -> QIcon:
    icon_path = config.get_val("tray", "icon_path", "")
    if icon_path:
        path = Path(icon_path).expanduser()
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
            logger.warning("Configured tray icon_path is not a valid image: %s", path)
        else:
            logger.warning("Configured tray icon_path does not exist: %s", path)

    return _build_fallback_icon(config.get_color("appearance", "border_color", "#89B4FA"))


class SystemTrayManager:
    """Owns the tray icon and its context menu. Every action is wired
    through plain callables passed in by the caller (typically
    ``OSDApplication``) rather than importing it directly, to keep this
    module free of a circular dependency and independently testable.

    Parameters
    ----------
    config:
        The active :class:`OSDConfigManager`; supplies the icon, tooltip,
        and enable/disable defaults from the ``[tray]`` section.
    parent:
        Optional Qt parent widget (keeps the tray icon alive for the
        lifetime of the parent).
    on_test:
        Called when "Show Test Notification" is clicked.
    on_toggle_server:
        Called when "Start Server" / "Stop Server" is clicked. Should
        start or stop the notification servers itself.
    is_server_running:
        Returns the current server state, used to label the toggle action
        and refresh it whenever the menu is shown.
    on_dismiss_all:
        Called when "Dismiss All Notifications" is clicked. Should close
        every currently visible notification immediately.
    on_open_config:
        Called when "Open Config File" is clicked. Defaults to revealing
        ``config.config_path`` in the OS file manager.
    on_quit:
        Called when "Quit" is clicked. Required.
    """

    def __init__(self, config: OSDConfigManager, parent: Optional[QWidget] = None,
                 on_test: Optional[Callable[[], None]] = None,
                 on_toggle_server: Optional[Callable[[], None]] = None,
                 is_server_running: Optional[Callable[[], bool]] = None,
                 on_dismiss_all: Optional[Callable[[], None]] = None,
                 on_open_config: Optional[Callable[[], None]] = None,
                 on_quit: Optional[Callable[[], None]] = None):
        if on_quit is None:
            raise ValueError("SystemTrayManager requires an on_quit callback.")

        self.config = config
        self._on_test = on_test
        self._on_toggle_server = on_toggle_server
        self._is_server_running = is_server_running or (lambda: False)
        self._on_dismiss_all = on_dismiss_all
        self._on_open_config = on_open_config or self._default_open_config
        self._on_quit = on_quit

        self.tray_icon = QSystemTrayIcon(_load_icon(config), parent)
        self.tray_icon.setToolTip(config.get_val("tray", "tooltip", "OSD Notification"))

        self.menu = QMenu(parent)
        self._build_menu()
        self.tray_icon.setContextMenu(self.menu)

        self.tray_icon.activated.connect(self._handle_activation)

    # ------------------------------------------------------------------ #
    # Menu construction
    # ------------------------------------------------------------------ #

    def _build_menu(self) -> None:
        self.test_action = QAction("Show Test Notification", self.menu)
        self.test_action.triggered.connect(self._handle_test)
        self.test_action.setEnabled(self._on_test is not None)
        self.menu.addAction(self.test_action)

        self.toggle_server_action = QAction("Start Server", self.menu)
        self.toggle_server_action.triggered.connect(self._handle_toggle_server)
        self.toggle_server_action.setEnabled(self._on_toggle_server is not None)
        self.menu.addAction(self.toggle_server_action)

        self.dismiss_all_action = QAction("Dismiss All Notifications", self.menu)
        self.dismiss_all_action.triggered.connect(self._handle_dismiss_all)
        self.dismiss_all_action.setEnabled(self._on_dismiss_all is not None)
        self.menu.addAction(self.dismiss_all_action)

        self.menu.addSeparator()

        self.open_config_action = QAction("Open Config File", self.menu)
        self.open_config_action.triggered.connect(self._on_open_config)
        self.menu.addAction(self.open_config_action)

        self.menu.addSeparator()

        self.quit_action = QAction("Quit", self.menu)
        self.quit_action.triggered.connect(self._handle_quit)
        self.menu.addAction(self.quit_action)

        self.menu.aboutToShow.connect(self._refresh_toggle_label)

    def _refresh_toggle_label(self) -> None:
        if self._on_toggle_server is None:
            return
        running = self._is_server_running()
        self.toggle_server_action.setText("Stop Server" if running else "Start Server")

    # ------------------------------------------------------------------ #
    # Action handlers
    # ------------------------------------------------------------------ #

    def _handle_test(self) -> None:
        if self._on_test is not None:
            try:
                self._on_test()
            except Exception:
                logger.exception("Tray 'Show Test Notification' handler failed.")

    def _handle_toggle_server(self) -> None:
        if self._on_toggle_server is not None:
            try:
                self._on_toggle_server()
            except Exception:
                logger.exception("Tray 'Start/Stop Server' handler failed.")
            self._refresh_toggle_label()

    def _handle_dismiss_all(self) -> None:
        if self._on_dismiss_all is not None:
            try:
                self._on_dismiss_all()
            except Exception:
                logger.exception("Tray 'Dismiss All Notifications' handler failed.")

    def _default_open_config(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.config_path.parent)))

    def _handle_quit(self) -> None:
        try:
            self._on_quit()
        except Exception:
            logger.exception("Tray 'Quit' handler failed.")

    def _handle_activation(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Double-click / trigger (left click on most platforms) shows a
        # quick test notification if the caller wired one up.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._handle_test()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        if not self.is_available():
            logger.warning("No system tray detected on this platform/session; tray icon not shown.")
            return
        self.tray_icon.show()

    def hide(self) -> None:
        self.tray_icon.hide()

    def set_tooltip(self, text: str) -> None:
        self.tray_icon.setToolTip(text)

    def show_message(self, title: str, text: str,
                      icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.Information,
                      msec: int = 5000) -> None:
        """Show a native OS balloon/toast via the tray icon, independent of
        the custom OSD widget. Useful for server status changes."""
        if not self.tray_icon.isVisible():
            return
        self.tray_icon.showMessage(title, text, icon, msec)
