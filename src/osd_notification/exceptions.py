#!/usr/bin/env python3

# File: src/osd_notification/exceptions.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Exception hierarchy for osd_notification.
# License: MIT


from __future__ import annotations


class OSDNotificationError(Exception):
    """Base class for all errors raised by osd_notification."""


class ConfigError(OSDNotificationError):
    """Raised when the configuration file is invalid or cannot be loaded/written."""


class PayloadValidationError(OSDNotificationError):
    """Raised when an inbound or outbound notification payload fails validation."""


class ServerError(OSDNotificationError):
    """Raised when a network server (GNTP/UDP) fails to start, bind, or run."""


class ClientError(OSDNotificationError):
    """Raised when the client fails to deliver a notification to the server."""
