#!/usr/bin/env python3

# File: src/osd_notification/app.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Wires together the Qt application, the OSD widget, and the
#              optional network servers, with graceful Ctrl+C shutdown.
# License: MIT

from __future__ import annotations

import signal
import sys
from typing import Optional

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon

from .config import OSDConfigManager
from .dispatcher import ControlDispatcher
from .exceptions import ServerError
from .logging_setup import get_logger
from .manager import NotificationManager
from .protocol import CONTROL_DISMISS_ALL, NotificationPayload
from .server import NotificationServerManager
from .tray import SystemTrayManager
from .widget import OSDNotification

logger = get_logger("OSDNotifier.App")


class OSDApplication:
    """Owns the QApplication, the notification manager, and (optionally) the
    background GNTP/UDP servers and the system tray icon, and ties them
    together with clean shutdown."""

    def __init__(self, config: Optional[OSDConfigManager] = None):
        self.config = config or OSDConfigManager()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.manager = NotificationManager(self.config)
        self.control_dispatcher = ControlDispatcher()
        self.control_dispatcher.dismiss_all_requested.connect(self.manager.dismiss_all)

        self.server_manager: Optional[NotificationServerManager] = None
        self.tray: Optional[SystemTrayManager] = None
        self._last_demo_widget: Optional[OSDNotification] = None

    def start_servers(self) -> None:
        host = self.config.get_val("server", "host", "127.0.0.1")
        gntp_port = self.config.get_int("server", "gntp_port", 23053, min_val=1, max_val=65535)
        udp_port = self.config.get_int("server", "udp_port", 23054, min_val=1, max_val=65535)
        max_payload = self.config.get_int("server", "max_payload_bytes", 65535, min_val=256, max_val=1_048_576)

        self.server_manager = NotificationServerManager(
            host=host, gntp_port=gntp_port, udp_port=udp_port,
            payload_handler=self.manager.dispatcher.dispatch,
            max_payload_bytes=max_payload,
            control_handler=self._on_control_command,
        )
        try:
            self.server_manager.start()
        except ServerError as exc:
            logger.error("Failed to start notification servers: %s", exc)
            raise
        logger.info("OSD Notification Server Mode Active (GNTP & UDP listening). Press Ctrl+C to exit.")

    def stop_servers(self) -> None:
        if self.server_manager is not None:
            self.server_manager.stop()
            self.server_manager = None

    def is_server_running(self) -> bool:
        return self.server_manager is not None and self.server_manager.is_running

    def _on_control_command(self, command: str) -> None:
        # Called from a server thread: hop to the Qt main thread via the
        # dispatcher's signal before touching any widget/manager state.
        if command == CONTROL_DISMISS_ALL:
            self.control_dispatcher.dismiss_all_requested.emit()

    def toggle_servers(self) -> None:
        notify = self.config.get_bool("tray", "notify_on_server_toggle", True)
        try:
            if self.is_server_running():
                self.stop_servers()
                if notify and self.tray is not None:
                    self.tray.show_message("OSD Notification", "Servers stopped.")
            else:
                self.start_servers()
                if notify and self.tray is not None:
                    self.tray.show_message("OSD Notification", "Servers started.")
        except ServerError as exc:
            if self.tray is not None:
                self.tray.show_message("OSD Notification", f"Server error: {exc}",
                                        icon=QSystemTrayIcon.Critical)

    def start_tray(self) -> None:
        if not self.config.get_bool("tray", "enabled", True):
            return
        if not SystemTrayManager.is_available():
            logger.warning("System tray unavailable on this platform/session; skipping tray icon.")
            return

        self.tray = SystemTrayManager(
            config=self.config,
            parent=None,
            on_test=self.run_demo,
            on_toggle_server=self.toggle_servers,
            is_server_running=self.is_server_running,
            on_dismiss_all=self.manager.dismiss_all,
            on_quit=self.app.quit,
        )
        self.tray.show()

    def run_demo(self, payload: Optional[NotificationPayload] = None) -> OSDNotification:
        """Show a single local notification with no network involved.

        With no `payload`, shows the default rocket-glyph demo (used by
        bare `--test`). Given a payload (via `--test --text "..."`), it is
        routed through the exact same code path as a network notification
        — this lets you verify wrapping/sizing/stacking behavior directly
        against specific content without needing a server process running
        at all, which also rules out a stale/already-running server as the
        cause of unexpected output.
        """
        if payload is not None:
            widget = self.manager.spawn(payload)
        else:
            widget = self.manager.spawn_glyph("\U0001f680", hex_str="1F680")
        self._last_demo_widget = widget
        return widget

    def run(self, quit_after_demo: bool = False) -> int:
        signal.signal(signal.SIGINT, lambda *_: self.app.quit())

        # A short-interval no-op timer lets Python's signal handler run
        # inside the Qt event loop, which otherwise blocks SIGINT delivery.
        signal_pump = QTimer()
        signal_pump.start(200)
        signal_pump.timeout.connect(lambda: None)

        if quit_after_demo and self._last_demo_widget is not None:
            widget = self._last_demo_widget
            if not widget._is_sticky(None):  # noqa: SLF001 - intentional internal use
                # Quit once the demo notification has actually finished
                # fading out, instead of re-deriving/guessing its duration.
                widget.dismissed.connect(self.app.quit)

        try:
            exit_code = self.app.exec_()
        finally:
            self.shutdown()

        return exit_code

    def shutdown(self) -> None:
        if self.tray is not None:
            self.tray.hide()
            self.tray = None
        self.stop_servers()
