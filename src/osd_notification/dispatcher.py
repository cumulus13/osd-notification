#!/usr/bin/env python3

# File: src/osd_notification/dispatcher.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Thread-safe Qt signal dispatcher bridging background network
#              server threads and the main-thread GUI event loop. Never touch
#              Qt widgets directly from a server thread — emit through this
#              instead.
# License: MIT


from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from .protocol import NotificationPayload


class NotificationDispatcher(QObject):
    """Emits ``show_notification`` on the Qt main thread when a network
    server thread receives a validated payload."""

    show_notification = pyqtSignal(object)  # payload: NotificationPayload

    def dispatch(self, payload: NotificationPayload) -> None:
        self.show_notification.emit(payload)


class ControlDispatcher(QObject):
    """Emits control-command signals on the Qt main thread when a network
    server thread receives one (e.g. a "dismiss all" UDP control message).
    Qt widgets/managers must only be touched from the main thread, so this
    exists for the same reason NotificationDispatcher does."""

    dismiss_all_requested = pyqtSignal()
