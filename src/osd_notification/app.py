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
from PyQt5.QtWidgets import QApplication

from .config import OSDConfigManager
from .exceptions import ServerError
from .logging_setup import get_logger
from .server import NotificationServerManager
from .widget import OSDNotification

logger = get_logger("OSDNotifier.App")


class OSDApplication:
    """Owns the QApplication, the notification widget, and (optionally) the
    background GNTP/UDP servers, and ties them together with clean shutdown."""

    def __init__(self, config: Optional[OSDConfigManager] = None):
        self.config = config or OSDConfigManager()
        self.app = QApplication(sys.argv)
        self.widget = OSDNotification(self.config)
        self.server_manager: Optional[NotificationServerManager] = None

    def start_servers(self) -> None:
        host = self.config.get_val("server", "host", "127.0.0.1")
        gntp_port = self.config.get_int("server", "gntp_port", 23053, min_val=1, max_val=65535)
        udp_port = self.config.get_int("server", "udp_port", 23054, min_val=1, max_val=65535)
        max_payload = self.config.get_int("server", "max_payload_bytes", 65535, min_val=256, max_val=1_048_576)

        self.server_manager = NotificationServerManager(
            host=host, gntp_port=gntp_port, udp_port=udp_port,
            payload_handler=self.widget.dispatcher.dispatch,
            max_payload_bytes=max_payload,
        )
        try:
            self.server_manager.start()
        except ServerError as exc:
            logger.error("Failed to start notification servers: %s", exc)
            raise
        logger.info("OSD Notification Server Mode Active (GNTP & UDP listening). Press Ctrl+C to exit.")

    def run_demo(self) -> None:
        """Show a single local demo notification (used by `--test`)."""
        self.widget.show_character("\U0001f680", hex_str="1F680")

    def run(self, quit_after_demo: bool = False) -> int:
        signal.signal(signal.SIGINT, lambda *_: self.app.quit())

        # A short-interval no-op timer lets Python's signal handler run
        # inside the Qt event loop, which otherwise blocks SIGINT delivery.
        signal_pump = QTimer()
        signal_pump.start(200)
        signal_pump.timeout.connect(lambda: None)

        if quit_after_demo:
            is_sticky = self.widget._is_sticky(None)  # noqa: SLF001 - intentional internal use
            if not is_sticky:
                timeout = self.widget._get_timeout(None)  # noqa: SLF001
                total_duration = 250 + timeout + 350 + 100
                QTimer.singleShot(total_duration, self.app.quit)

        try:
            exit_code = self.app.exec_()
        finally:
            self.shutdown()

        return exit_code

    def shutdown(self) -> None:
        if self.server_manager is not None:
            self.server_manager.stop()
            self.server_manager = None
