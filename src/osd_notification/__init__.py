#!/usr/bin/env python3

# File: src/osd_notification/__init__.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Cross-platform, network-triggerable On-Screen Display notification package.
# License: MIT

"""
osd_notification
=================

Cross-platform, network-triggerable On-Screen Display notification package.

Provides:
    - A frameless, animated Qt notification widget (``OSDNotification``)
    - Threaded GNTP/1.0 TCP and JSON/UDP notification servers
    - A validated, typed configuration manager backed by ``configset``
    - A synchronous client library for dispatching notifications
      (``NotificationClient``)
    - A production CLI (``osd-notification``)

License: MIT
"""

from .config import OSDConfigManager
from .exceptions import (
    OSDNotificationError,
    ConfigError,
    PayloadValidationError,
    ServerError,
    ClientError,
)
from .protocol import NotificationPayload
from .client import NotificationClient
from .server import NotificationServerManager

__all__ = [
    "OSDConfigManager",
    "OSDNotificationError",
    "ConfigError",
    "PayloadValidationError",
    "ServerError",
    "ClientError",
    "NotificationPayload",
    "NotificationClient",
    "NotificationServerManager",
    "__version__",
]

__version__ = "1.1.0"
