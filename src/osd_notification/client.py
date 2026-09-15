#!/usr/bin/env python3

# File: src/osd_notification/client.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Synchronous client for dispatching notifications to a running
#              osd-notification server, over UDP (JSON) or GNTP (TCP).
#              Supports retry with backoff, configurable timeouts, and
#              optional environment-variable configuration via `envdot`.
# License: MIT


from __future__ import annotations

import json
import os
import socket
import time
from typing import Callable, Optional

from .exceptions import ClientError
from .logging_setup import get_logger
from .protocol import CONTROL_DISMISS_ALL, NotificationPayload

logger = get_logger("OSDNotifier.Client")

try:  # optional: load .env if envdot is installed and present
    from envdot import load_env  # type: ignore

    load_env()
except Exception:
    pass


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


class NotificationClient:
    """Sends notifications to a running osd-notification server.

    Example:
        >>> client = NotificationClient(host="127.0.0.1", udp_port=23064)
        >>> client.send(title="Build Successful", text="All tests passed.")
    """

    def __init__(self, host: Optional[str] = None,
                 gntp_port: Optional[int] = None,
                 udp_port: Optional[int] = None,
                 timeout: float = 5.0,
                 max_retries: int = 2,
                 retry_backoff: float = 0.5):
        self.host = host or _env("host", "127.0.0.1")
        self.gntp_port = gntp_port or int(_env("gntp_port", "23063"))
        self.udp_port = udp_port or int(_env("udp_port", "23064"))
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.retry_backoff = max(0.0, retry_backoff)

    # ------------------------------------------------------------------ #
    # High-level API
    # ------------------------------------------------------------------ #

    def send(self, title: str, text: str = "", icon: Optional[str] = None,
              sticky: bool = False, timeout: Optional[int] = None,
              transport: str = "udp") -> None:
        """Build and send a payload. `transport` is "udp" or "gntp"."""
        payload = NotificationPayload(title=title, text=text, icon=icon,
                                       sticky=sticky, timeout=timeout, source="client")
        if transport == "udp":
            self.send_udp(payload)
        elif transport == "gntp":
            self.send_gntp(payload)
        else:
            raise ClientError(f"Unknown transport: {transport!r} (expected 'udp' or 'gntp')")

    def send_udp(self, payload: NotificationPayload) -> None:
        self._with_retries(lambda: self._send_udp_once(payload))

    def send_gntp(self, payload: NotificationPayload) -> None:
        self._with_retries(lambda: self._send_gntp_once(payload))

    def dismiss_all(self) -> None:
        """Tell the running server to immediately close every currently
        shown notification. Sent over UDP as a small control message,
        distinct from a normal notification payload."""
        self._with_retries(self._send_dismiss_all_once)

    # ------------------------------------------------------------------ #
    # Transport implementations
    # ------------------------------------------------------------------ #

    def _send_udp_once(self, payload: NotificationPayload) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        try:
            sock.sendto(payload.to_json().encode("utf-8"), (self.host, self.udp_port))
            logger.debug("Sent UDP notification to %s:%s: %s", self.host, self.udp_port, payload.title)
        except OSError as exc:
            raise ClientError(f"UDP send to {self.host}:{self.udp_port} failed: {exc}") from exc
        finally:
            sock.close()

    def _send_dismiss_all_once(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        try:
            message = json.dumps({"command": CONTROL_DISMISS_ALL}).encode("utf-8")
            sock.sendto(message, (self.host, self.udp_port))
            logger.debug("Sent dismiss_all control message to %s:%s", self.host, self.udp_port)
        except OSError as exc:
            raise ClientError(f"dismiss_all send to {self.host}:{self.udp_port} failed: {exc}") from exc
        finally:
            sock.close()

    def _send_gntp_once(self, payload: NotificationPayload) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.gntp_port))
            sock.sendall(payload.to_gntp().encode("utf-8"))
            response = sock.recv(1024).decode("utf-8", errors="ignore")
            if "-OK" not in response:
                raise ClientError(f"GNTP server rejected notification: {response.strip()!r}")
            logger.debug("Sent GNTP notification to %s:%s: %s", self.host, self.gntp_port, payload.title)
        except OSError as exc:
            raise ClientError(f"GNTP send to {self.host}:{self.gntp_port} failed: {exc}") from exc
        finally:
            sock.close()

    def _with_retries(self, fn: Callable[[], None]) -> None:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                fn()
                return
            except ClientError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = self.retry_backoff * (2 ** attempt)
                    logger.warning("Attempt %d/%d failed (%s); retrying in %.1fs",
                                   attempt + 1, self.max_retries + 1, exc, delay)
                    time.sleep(delay)
        assert last_exc is not None
        raise last_exc
