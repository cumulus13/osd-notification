#!/usr/bin/env python3

# File: src/osd_notification/protocol.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Wire-format definitions for osd_notification — the validated
#              `NotificationPayload` model, GNTP/1.0 header encode/decode,
#              and safe icon-path resolution shared by client and server.
# License: MIT


from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .exceptions import PayloadValidationError

GNTP_PROTOCOL_LINE = "GNTP/1.0 NOTIFY NONE"
GNTP_OK_RESPONSE = "GNTP/1.0 -OK NONE\r\nResponse-Action: NOTIFY\r\n\r\n"

_MAX_TITLE_LEN = 200
_MAX_TEXT_LEN = 4000
_ALLOWED_ICON_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".ico", ".svg"}


@dataclass
class NotificationPayload:
    """A validated notification payload shared by the client and both servers.

    Raises ``PayloadValidationError`` on construction if any field is out of
    the accepted range, preventing malformed/oversized data from ever
    reaching the Qt widget or being sent over the wire.
    """

    title: str = "Notification"
    text: str = ""
    icon: Optional[str] = None
    sticky: bool = False
    timeout: Optional[int] = None
    source: str = field(default="unknown", compare=False)

    def __post_init__(self) -> None:
        self.title = (self.title or "Notification").strip()[:_MAX_TITLE_LEN]
        self.text = (self.text or "").strip()[:_MAX_TEXT_LEN]

        if not self.title:
            raise PayloadValidationError("Notification title cannot be empty.")

        if self.timeout is not None:
            try:
                self.timeout = max(0, min(int(self.timeout), 60_000))
            except (TypeError, ValueError) as exc:
                raise PayloadValidationError(f"Invalid timeout value: {self.timeout!r}") from exc

        if self.icon is not None:
            self.icon = str(self.icon).strip() or None

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, object]:
        return {
            "title": self.title,
            "text": self.text,
            "icon": self.icon,
            "sticky": self.sticky,
            "timeout": self.timeout,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def to_gntp(self, application_name: str = "OSD Notification") -> str:
        lines = [
            GNTP_PROTOCOL_LINE,
            f"Application-Name: {application_name}",
            "Notification-Name: System Alert",
            f"Notification-Title: {self.title}",
            f"Notification-Text: {self.text}",
        ]
        if self.icon:
            lines.append(f"Notification-Icon: {self.icon}")
        lines.append(f"Notification-Sticky: {'true' if self.sticky else 'false'}")
        return "\r\n".join(lines) + "\r\n\r\n"

    @classmethod
    def from_dict(cls, data: Dict[str, object], source: str = "unknown") -> "NotificationPayload":
        if not isinstance(data, dict):
            raise PayloadValidationError(f"Payload must be a JSON object, got {type(data).__name__}")
        return cls(
            title=str(data.get("title", "Notification")),
            text=str(data.get("text", "")),
            icon=data.get("icon") if data.get("icon") is not None else None,  # type: ignore[arg-type]
            sticky=bool(data.get("sticky", False)),
            timeout=data.get("timeout"),  # type: ignore[arg-type]
            source=source,
        )

    @classmethod
    def from_json(cls, raw: str, source: str = "unknown") -> "NotificationPayload":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PayloadValidationError(f"Invalid JSON payload: {exc}") from exc
        return cls.from_dict(data, source=source)

    @classmethod
    def from_gntp_headers(cls, headers: Dict[str, str], source: str = "gntp") -> "NotificationPayload":
        title = headers.get("notification-title") or headers.get("title", "GNTP Alert")
        text = headers.get("notification-text") or headers.get("text", "")
        icon = headers.get("notification-icon") or headers.get("icon")
        sticky_raw = headers.get("notification-sticky", "false").strip().lower()
        timeout_raw = headers.get("notification-timeout") or headers.get("timeout")
        timeout = None
        if timeout_raw:
            try:
                timeout = int(timeout_raw)
            except ValueError:
                timeout = None
        return cls(
            title=title,
            text=text,
            icon=icon,
            sticky=sticky_raw in ("true", "1", "yes"),
            timeout=timeout,
            source=source,
        )


def parse_gntp_headers(raw_lines: List[str]) -> Dict[str, str]:
    """Parse `Key: Value` header lines (already newline-split) into a dict.
    Malformed lines (no colon) are silently skipped rather than raising,
    matching the tolerant behavior GNTP clients expect."""
    headers: Dict[str, str] = {}
    for line in raw_lines:
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        headers[key.strip().lower()] = val.strip()
    return headers


def resolve_icon_path(icon: Optional[str], allowed_dirs: List[Path]) -> Optional[Path]:
    """Resolve an inbound icon reference to a real, safe filesystem path.

    Returns ``None`` if the icon is absent, does not exist, has a
    disallowed extension, or resolves outside every directory in
    ``allowed_dirs`` (defense against path traversal from network input).
    """
    if not icon:
        return None

    candidate = icon
    if candidate.startswith("file://"):
        candidate = candidate[len("file://"):]

    try:
        path = Path(candidate).expanduser().resolve()
    except (OSError, RuntimeError):
        return None

    if path.suffix.lower() not in _ALLOWED_ICON_EXTENSIONS:
        return None
    if not path.is_file():
        return None

    for allowed in allowed_dirs:
        try:
            path.relative_to(allowed)
            return path
        except ValueError:
            continue

    return None
