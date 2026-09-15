#!/usr/bin/env python3

# File: src/osd_notification/server.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Production-grade, threaded GNTP/1.0 TCP and JSON/UDP
#              notification servers. Payloads are size-capped and validated
#              before ever reaching the GUI. `NotificationServerManager`
#              owns the full start/stop lifecycle, including graceful
#              shutdown of sockets and threads.
# License: MIT


from __future__ import annotations

import socket
import socketserver
import threading
from typing import Callable, Optional

from .exceptions import PayloadValidationError, ServerError
from .logging_setup import get_logger
from .protocol import (
    GNTP_OK_RESPONSE,
    NotificationPayload,
    is_known_control_command,
    parse_gntp_headers,
    try_parse_control_command,
)

logger = get_logger("OSDNotifier.Server")

_SOCKET_TIMEOUT_SECONDS = 10
_MAX_HEADER_LINES = 64

PayloadHandler = Callable[[NotificationPayload], None]
ControlHandler = Callable[[str], None]


class GNTPTCPHandler(socketserver.StreamRequestHandler):
    """Parses a single GNTP/1.0 NOTIFY request per connection and forwards a
    validated payload to the server's registered handler."""

    timeout = _SOCKET_TIMEOUT_SECONDS

    def handle(self) -> None:  # noqa: C901 - kept flat for readability
        try:
            request_line = self.rfile.readline(4096).decode("utf-8", errors="ignore").strip()
            if not request_line or not request_line.startswith("GNTP/1.0"):
                logger.debug("Rejected non-GNTP request line: %r", request_line[:80])
                return

            raw_lines = []
            for _ in range(_MAX_HEADER_LINES):
                line = self.rfile.readline(4096)
                if not line:
                    break
                decoded = line.decode("utf-8", errors="ignore").strip()
                if not decoded:
                    break
                raw_lines.append(decoded)

            headers = parse_gntp_headers(raw_lines)

            try:
                payload = NotificationPayload.from_gntp_headers(headers, source="gntp")
            except PayloadValidationError as exc:
                logger.warning("Rejected invalid GNTP payload: %s", exc)
                return

            logger.info("GNTP notification received: %s - %s", payload.title, payload.text)

            handler: Optional[PayloadHandler] = getattr(self.server, "payload_handler", None)
            if handler is not None:
                handler(payload)

            self.wfile.write(GNTP_OK_RESPONSE.encode("utf-8"))
            self.wfile.flush()
        except (ConnectionResetError, socket.timeout) as exc:
            logger.debug("GNTP connection closed early: %s", exc)
        except Exception as exc:  # pragma: no cover - defensive network boundary
            logger.error("Error handling GNTP request: %s", exc)


class ThreadedGNTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args, payload_handler: Optional[PayloadHandler] = None, **kwargs):
        self.payload_handler = payload_handler
        super().__init__(*args, **kwargs)


class UDPNotificationServer:
    """Threaded JSON/UDP notification listener with a bounded receive size,
    tolerant GNTP-style header fallback parsing, and clean shutdown via a
    stop ``Event``."""

    def __init__(self, host: str, port: int, payload_handler: PayloadHandler,
                 max_payload_bytes: int = 65535,
                 control_handler: Optional[ControlHandler] = None):
        self.host = host
        self.port = port
        self.payload_handler = payload_handler
        self.control_handler = control_handler
        self.max_payload_bytes = max_payload_bytes
        self._sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(1.0)  # allows periodic stop_event checks
        try:
            self._sock.bind((self.host, self.port))
        except OSError as exc:
            raise ServerError(f"Could not bind UDP server to {self.host}:{self.port}: {exc}") from exc

        logger.info("UDP server listening on %s:%s", self.host, self.port)
        self._thread = threading.Thread(target=self._serve_forever, daemon=True, name="osd-udp-server")
        self._thread.start()

    def _serve_forever(self) -> None:
        assert self._sock is not None
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(self.max_payload_bytes)
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                logger.exception("UDP recv error")
                continue

            self._handle_datagram(data, addr)

    def _handle_datagram(self, data: bytes, addr) -> None:
        message_str = data.decode("utf-8", errors="ignore")

        command = try_parse_control_command(message_str)
        if command is not None:
            if not is_known_control_command(command):
                logger.warning("Ignoring unrecognized control command from %s: %r", addr, command)
                return
            logger.info("UDP control command received from %s: %s", addr, command)
            if self.control_handler is not None:
                self.control_handler(command)
            return

        try:
            payload = NotificationPayload.from_json(message_str, source=f"udp:{addr[0]}")
        except PayloadValidationError:
            if ":" in message_str:
                headers = parse_gntp_headers(message_str.splitlines())
                try:
                    payload = NotificationPayload.from_gntp_headers(headers, source=f"udp:{addr[0]}")
                except PayloadValidationError as exc:
                    logger.warning("Rejected invalid UDP payload from %s: %s", addr, exc)
                    return
            else:
                try:
                    payload = NotificationPayload(title="UDP Message", text=message_str, source=f"udp:{addr[0]}")
                except PayloadValidationError as exc:
                    logger.warning("Rejected invalid UDP payload from %s: %s", addr, exc)
                    return

        logger.info("UDP notification received from %s: %s", addr, payload.title)
        self.payload_handler(payload)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass


class NotificationServerManager:
    """Owns the lifecycle of both the GNTP TCP server and the UDP server,
    so callers get a single `start()` / `stop()` pair with guaranteed
    cleanup of sockets and threads."""

    def __init__(self, host: str, gntp_port: int, udp_port: int,
                 payload_handler: PayloadHandler, max_payload_bytes: int = 65535,
                 control_handler: Optional[ControlHandler] = None):
        self.host = host
        self.gntp_port = gntp_port
        self.udp_port = udp_port
        self.payload_handler = payload_handler
        self.control_handler = control_handler
        self.max_payload_bytes = max_payload_bytes

        self._gntp_server: Optional[ThreadedGNTPServer] = None
        self._gntp_thread: Optional[threading.Thread] = None
        self._udp_server: Optional[UDPNotificationServer] = None

    @property
    def is_running(self) -> bool:
        return self._gntp_server is not None or self._udp_server is not None

    def start(self) -> None:
        if self.is_running:
            logger.warning("NotificationServerManager.start() called while already running; ignoring.")
            return

        try:
            self._gntp_server = ThreadedGNTPServer(
                (self.host, self.gntp_port), GNTPTCPHandler, payload_handler=self.payload_handler
            )
        except OSError as exc:
            raise ServerError(f"Could not bind GNTP server to {self.host}:{self.gntp_port}: {exc}") from exc

        self._gntp_thread = threading.Thread(
            target=self._gntp_server.serve_forever, daemon=True, name="osd-gntp-server"
        )
        self._gntp_thread.start()
        logger.info("GNTP server listening on %s:%s", self.host, self.gntp_port)

        self._udp_server = UDPNotificationServer(
            self.host, self.udp_port, self.payload_handler, self.max_payload_bytes,
            control_handler=self.control_handler,
        )
        self._udp_server.start()

    def stop(self) -> None:
        if self._gntp_server is not None:
            try:
                self._gntp_server.shutdown()
                self._gntp_server.server_close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Error stopping GNTP server: %s", exc)
            finally:
                self._gntp_server = None

        if self._gntp_thread is not None:
            self._gntp_thread.join(timeout=2.0)
            self._gntp_thread = None

        if self._udp_server is not None:
            self._udp_server.stop()
            self._udp_server = None

        logger.info("Notification servers stopped.")
