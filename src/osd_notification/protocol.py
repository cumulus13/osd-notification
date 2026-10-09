#!/usr/bin/env python3

# File: src/osd_notification/protocol.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Wire-format definitions for osd_notification — the validated
#              `NotificationPayload` model, GNTP/1.0 header encode/decode,
#              and safe icon-path resolution shared by client and server.
# License: MIT


from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .exceptions import PayloadValidationError

try:
    from . debugger import debug, logger, is_debug  # type: ignore
except:
    from debugger import debug, logger, is_debug  # type: ignore

GNTP_PROTOCOL_LINE = "GNTP/1.0 NOTIFY NONE"
GNTP_OK_RESPONSE = "GNTP/1.0 -OK NONE\r\nResponse-Action: NOTIFY\r\n\r\n"

# GNTP 1.0 spec: Notification-Icon is either an http(s):// URL, or a
# reference to an inline binary resource transmitted as a separate block
# after the headers, named by this URI scheme. A bare local filesystem path
# (what this project used before) is NOT part of the spec — it only ever
# worked because our own client and server privately agreed on it, and
# only when both run on the same machine.
GNTP_RESOURCE_SCHEME = "x-growl-resource://"
MAX_ICON_BYTES = 2 * 1024 * 1024  # 2 MiB — generous for a notification icon

CONTROL_DISMISS_ALL = "dismiss_all"
_KNOWN_CONTROL_COMMANDS = {CONTROL_DISMISS_ALL}

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
    icon_data: Optional[bytes] = field(default=None, compare=False, repr=False)
    """Raw icon image bytes, when the icon arrived as an inline resource
    (GNTP `x-growl-resource://`) or embedded base64 (UDP/JSON) rather than
    a filesystem reference. Takes priority over `icon` for rendering —
    no filesystem resolution needed, it's self-contained data."""

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

        debug(self_icon = self.icon)
        if self.icon_data is not None:
            if not isinstance(self.icon_data, (bytes, bytearray)):
                raise PayloadValidationError(
                    f"icon_data must be bytes, got {type(self.icon_data).__name__}"
                )
            if len(self.icon_data) > MAX_ICON_BYTES:
                raise PayloadValidationError(
                    f"icon_data too large ({len(self.icon_data)} bytes, "
                    f"max {MAX_ICON_BYTES})"
                )
            self.icon_data = bytes(self.icon_data)

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {
            "title": self.title,
            "text": self.text,
            "icon": self.icon,
            "sticky": self.sticky,
            "timeout": self.timeout,
        }
        if self.icon_data is not None:
            data["icon_base64"] = base64.b64encode(self.icon_data).decode("ascii")
        return data

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
        if self.timeout is not None:
            lines.append(f"Notification-Timeout: {self.timeout}")
        return "\r\n".join(lines) + "\r\n\r\n"

    def to_gntp1(self, application_name: str = "OSD Notification") -> str:
        lines = [
            GNTP_PROTOCOL_LINE,
            f"Application-Name: {application_name}",
            "Notification-Name: System Alert",
            f"Notification-Title: {self.title}",
            f"Notification-Text: {self.text}",
        ]
        debug(self_icon = self.icon)
        if self.icon:
            lines.append(f"Notification-Icon: {self.icon}")
        lines.append(f"Notification-Sticky: {'true' if self.sticky else 'false'}")
        return "\r\n".join(lines) + "\r\n\r\n"

    def to_gntp2(self, application_name: str = "OSD Notification") -> bytes:
        lines = [
            GNTP_PROTOCOL_LINE,
            f"Application-Name: {application_name}",
            "Notification-Name: System Alert",
            f"Notification-Title: {self.title}",
            f"Notification-Text: {self.text}",
        ]

        debug(self_icon=self.icon)

        icon_data = None
        unique_id = None

        if self.icon:
            icon_path = Path(self.icon).expanduser().resolve()

            if icon_path.is_file():
                icon_data = icon_path.read_bytes()

                # GNTP best practice: use MD5 hash for the resource ID to avoid illegal characters
                unique_id = hashlib.md5(icon_data).hexdigest()
                debug(unique_id = unique_id)
                
                # The header uses the x-growl-resource:// URI prefix
                lines.append(f"Notification-Icon: x-growl-resource://{unique_id}")
                debug(lines = lines)

        lines.append(
            f"Notification-Sticky: {'true' if self.sticky else 'false'}"
        )

        debug(lines=lines)

        header = "\r\n".join(lines) + "\r\n\r\n"
        debug(header=header)

        # debug(icon_data=icon_data)
        if icon_data is None:
            debug(header=header)
            return header.encode("utf-8")

        # GNTP resource block.
        # The Identifier here must EXACTLY match the ID, WITHOUT the URI prefix.
        resource_header = (
            f"Identifier: {unique_id}\r\n"
            f"Length: {len(icon_data)}\r\n"
            "\r\n"
        )

        # Assemble final payload: Main Header + Resource Header + Binary + Final \r\n\r\n
        payload = (
            header.encode("utf-8")
            + resource_header.encode("utf-8")
            + icon_data
            + b"\r\n\r\n"  # Mandatory GNTP message terminator
        )

        # debug(header=payload.decode(errors="ignore"))
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, object], source: str = "unknown") -> "NotificationPayload":
        if not isinstance(data, dict):
            raise PayloadValidationError(f"Payload must be a JSON object, got {type(data).__name__}")

        icon_data = None
        icon_b64 = data.get("icon_base64")
        if icon_b64:
            try:
                icon_data = base64.b64decode(str(icon_b64), validate=True)
            except (ValueError, TypeError) as exc:
                raise PayloadValidationError(f"Invalid icon_base64: {exc}") from exc

        return cls(
            title=str(data.get("title", "Notification")),
            text=str(data.get("text", "")),
            icon=data.get("icon") if data.get("icon") is not None else None,  # type: ignore[arg-type]
            sticky=bool(data.get("sticky", False)),
            timeout=data.get("timeout"),  # type: ignore[arg-type]
            source=source,
            icon_data=icon_data,
        )

    @classmethod
    def from_json(cls, raw: str, source: str = "unknown") -> "NotificationPayload":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PayloadValidationError(f"Invalid JSON payload: {exc}") from exc
        return cls.from_dict(data, source=source)

    @classmethod
    def from_gntp_headers(cls, headers: Dict[str, str], source: str = "gntp",
                           icon_data: Optional[bytes] = None) -> "NotificationPayload":
        """`icon_data` is the already-extracted bytes of an inline
        `x-growl-resource://` binary section, when the caller (the GNTP TCP
        handler) found and read one matching the Notification-Icon header's
        resource id — pass it straight through so it doesn't need to be
        re-resolved as a filesystem path."""
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
            icon_data=icon_data,
        )

    # ------------------------------------------------------------------ #
    # GNTP wire message (spec-compliant): headers + optional inline
    # binary resource section for a local-file icon
    # ------------------------------------------------------------------ #

    def build_gntp_message(self, application_name: str = "OSD Notification") -> bytes:
        """Build the full GNTP/1.0 NOTIFY request as bytes, ready to send
        over the TCP socket.

        Per the GNTP spec, `Notification-Icon` may only be an `http(s)://`
        URL or an `x-growl-resource://<id>` reference to a binary section
        transmitted after the headers — never a bare local path. This:
        - passes an `http(s)://` icon straight through as the header value
          (spec-correct, no embedding needed — the receiver fetches it)
        - embeds `icon_data` (if set) as a proper binary resource section
        - otherwise, if `icon` points at a readable local file, reads and
          embeds *that* as the binary resource too (so it survives even if
          client and server are on different machines — the whole point of
          the resource mechanism, and something a bare path could never do)
        - falls back to passing `icon` through verbatim only when none of
          the above apply (kept for backward compatibility with the old
          private convention; not spec-compliant, documented as such)
        """
        icon_bytes: Optional[bytes] = self.icon_data
        icon_header_value: Optional[str] = None
        resource_id: Optional[str] = None

        if self.icon and self.icon.lower().startswith(("http://", "https://")):
            icon_header_value = self.icon
            icon_bytes = None  # spec: fetched by the receiver from the URL, not embedded
        elif icon_bytes is not None:
            resource_id = f"osd-icon-{uuid.uuid4().hex}"
            icon_header_value = f"{GNTP_RESOURCE_SCHEME}{resource_id}"
        elif self.icon:
            try:
                candidate = Path(self.icon).expanduser()
                if candidate.is_file() and candidate.stat().st_size <= MAX_ICON_BYTES:
                    icon_bytes = candidate.read_bytes()
                    resource_id = f"osd-icon-{uuid.uuid4().hex}"
                    icon_header_value = f"{GNTP_RESOURCE_SCHEME}{resource_id}"
            except OSError:
                icon_bytes = None
            if icon_header_value is None:
                # Non-spec fallback: pass the raw string through so a
                # server that still understands the old convention (or is
                # this same codebase) can try to resolve it locally.
                icon_header_value = self.icon
                icon_bytes = None

        lines = [
            GNTP_PROTOCOL_LINE,
            f"Application-Name: {application_name}",
            "Notification-Name: System Alert",
            f"Notification-Title: {self.title}",
            f"Notification-Text: {self.text}",
        ]
        if icon_header_value:
            lines.append(f"Notification-Icon: {icon_header_value}")
        lines.append(f"Notification-Sticky: {'true' if self.sticky else 'false'}")
        if self.timeout is not None:
            lines.append(f"Notification-Timeout: {self.timeout}")

        message = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

        if icon_bytes is not None and resource_id is not None:
            message += build_gntp_binary_section(resource_id, icon_bytes)

        return message


def try_parse_control_command(raw: str) -> Optional[str]:
    """If `raw` is a JSON object with a `command` key, return the lowercased
    command string (even if it isn't one we recognize — the caller should
    still treat it as a control message, not fall through to notification
    parsing, and log/ignore the unknown command). Returns None only when
    `raw` isn't a JSON object with a `command` key at all, i.e. it's an
    ordinary notification payload."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "command" not in data:
        return None
    return str(data["command"]).strip().lower()


def is_known_control_command(command: str) -> bool:
    return command in _KNOWN_CONTROL_COMMANDS


def build_gntp_binary_section(identifier: str, data: bytes) -> bytes:
    """Encode one GNTP inline binary resource section: an
    `Identifier`/`Length` header pair, a blank line, the raw bytes, then a
    trailing blank line — the format the spec uses for data following a
    message's normal headers, referenced from a header value via
    `x-growl-resource://<identifier>`."""
    header = f"Identifier: {identifier}\r\nLength: {len(data)}\r\n\r\n".encode("ascii")
    return header + data + b"\r\n\r\n"


def parse_gntp_binary_sections(raw: bytes) -> Dict[str, bytes]:
    """Parse one or more binary resource sections (see
    `build_gntp_binary_section`) out of the raw bytes following a GNTP
    message's headers. Tolerant of trailing garbage/truncation — stops and
    returns whatever it could parse rather than raising, matching the
    tolerant style of `parse_gntp_headers`."""
    sections: Dict[str, bytes] = {}
    pos = 0
    id_marker = b"Identifier:"
    length_marker = b"Length:"

    while pos < len(raw):
        idx = raw.find(id_marker, pos)
        if idx == -1:
            break
        line_end = raw.find(b"\r\n", idx)
        if line_end == -1:
            break
        identifier = raw[idx + len(id_marker):line_end].strip().decode("ascii", errors="ignore")
        if not identifier:
            break

        len_idx = raw.find(length_marker, line_end)
        if len_idx == -1:
            break
        len_line_end = raw.find(b"\r\n", len_idx)
        if len_line_end == -1:
            break
        try:
            length = int(raw[len_idx + len(length_marker):len_line_end].strip())
        except ValueError:
            break
        if length < 0 or length > MAX_ICON_BYTES:
            break

        data_start = raw.find(b"\r\n\r\n", len_line_end)
        if data_start == -1:
            break
        data_start += 4
        data_end = data_start + length
        if data_end > len(raw):
            break  # truncated

        sections[identifier] = raw[data_start:data_end]
        pos = data_end

    return sections


def extract_gntp_resource_id(icon_header_value: str) -> Optional[str]:
    """If `icon_header_value` is an `x-growl-resource://<id>` reference,
    return the id; otherwise None (it's a URL, a local path, or empty)."""
    if icon_header_value.startswith(GNTP_RESOURCE_SCHEME):
        return icon_header_value[len(GNTP_RESOURCE_SCHEME):].strip() or None
    return None


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


class IconRejectReason:
    """Machine-readable reasons `resolve_icon_path` can fail for, so callers
    (the CLI's `--check-icon` diagnostic in particular) can report exactly
    why an icon didn't resolve instead of a silent fallback."""
    EMPTY = "empty"
    BAD_PATH = "bad_path"
    BAD_EXTENSION = "bad_extension"
    NOT_A_FILE = "not_a_file"
    OUTSIDE_ALLOWED_DIRS = "outside_allowed_dirs"


def strip_wrapping_quotes(value: str) -> str:
    """Strip a single layer of matching leading/trailing quotes — Windows
    users very commonly wrap paths in quotes in an ini file
    (`icon_path = "C:\\icons\\foo.png"`), which otherwise becomes part of
    the literal (bogus) path string."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value


def resolve_icon_path(icon: Optional[str], allowed_dirs: Optional[List[Path]]) -> Optional[Path]:
    """Resolve an inbound icon reference to a real, safe filesystem path.

    ``allowed_dirs=None`` disables the directory allow-list entirely
    (trusts any existing image file) — extension and existence are still
    checked either way. Passing a list enforces that the resolved path
    falls under one of those directories, compared case-insensitively
    (`Path.relative_to` is case-sensitive even on Windows, where the
    filesystem itself is not — comparing raw would silently reject valid
    icons whose resolved path differs only in case, e.g. the drive letter).

    Returns ``None`` on any failure. Use `resolve_icon_path_verbose` if you
    need to know *why* it failed.
    """
    path, _reason = resolve_icon_path_verbose(icon, allowed_dirs)
    return path


def resolve_icon_path_verbose(
    icon: Optional[str], allowed_dirs: Optional[List[Path]]
) -> Tuple[Optional[Path], Optional[str]]:
    """Same as `resolve_icon_path`, but also returns an `IconRejectReason`
    (or None on success) explaining why resolution failed."""
    if not icon:
        return None, IconRejectReason.EMPTY

    candidate = strip_wrapping_quotes(icon)
    if candidate.startswith("file://"):
        candidate = candidate[len("file://"):]

    try:
        path = Path(candidate).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None, IconRejectReason.BAD_PATH

    if path.suffix.lower() not in _ALLOWED_ICON_EXTENSIONS:
        return None, IconRejectReason.BAD_EXTENSION
    if not path.is_file():
        return None, IconRejectReason.NOT_A_FILE

    if allowed_dirs is None:
        return path, None

    normalized_path = os.path.normcase(str(path))
    for allowed in allowed_dirs:
        normalized_allowed = os.path.normcase(str(allowed))
        if normalized_path == normalized_allowed or normalized_path.startswith(
            normalized_allowed + os.sep
        ):
            return path, None

    return None, IconRejectReason.OUTSIDE_ALLOWED_DIRS
