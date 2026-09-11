#!/usr/bin/env python3

# File: tests/test_protocol.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Unit tests for osd_notification.protocol.
# License: MIT


from pathlib import Path

import pytest

from osd_notification.exceptions import PayloadValidationError
from osd_notification.protocol import (
    NotificationPayload,
    parse_gntp_headers,
    resolve_icon_path,
)


def test_payload_defaults():
    p = NotificationPayload()
    assert p.title == "Notification"
    assert p.text == ""
    assert p.sticky is False
    assert p.timeout is None


def test_payload_strips_and_truncates():
    p = NotificationPayload(title="  Hello  ", text="  world  ")
    assert p.title == "Hello"
    assert p.text == "world"


def test_payload_empty_title_after_strip_raises():
    with pytest.raises(PayloadValidationError):
        NotificationPayload(title="   ")


def test_payload_title_length_capped():
    p = NotificationPayload(title="x" * 500)
    assert len(p.title) == 200


def test_payload_timeout_clamped():
    p = NotificationPayload(title="t", timeout=999999)
    assert p.timeout == 60000

    p2 = NotificationPayload(title="t", timeout=-5)
    assert p2.timeout == 0


def test_payload_invalid_timeout_raises():
    with pytest.raises(PayloadValidationError):
        NotificationPayload(title="t", timeout="not-a-number")


def test_json_round_trip():
    p = NotificationPayload(title="Build", text="ok", sticky=True, timeout=1000)
    restored = NotificationPayload.from_json(p.to_json())
    assert restored.title == p.title
    assert restored.text == p.text
    assert restored.sticky == p.sticky
    assert restored.timeout == p.timeout


def test_from_json_invalid_raises():
    with pytest.raises(PayloadValidationError):
        NotificationPayload.from_json("not json {{{")


def test_from_dict_rejects_non_dict():
    with pytest.raises(PayloadValidationError):
        NotificationPayload.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


def test_gntp_round_trip():
    p = NotificationPayload(title="Alert", text="something happened", sticky=True, icon="icon.png")
    wire = p.to_gntp()
    lines = wire.strip("\r\n").split("\r\n")
    headers = parse_gntp_headers(lines)
    restored = NotificationPayload.from_gntp_headers(headers)
    assert restored.title == "Alert"
    assert restored.text == "something happened"
    assert restored.sticky is True
    assert restored.icon == "icon.png"


def test_parse_gntp_headers_skips_malformed_lines():
    headers = parse_gntp_headers(["Notification-Title: X", "not a header", "Notification-Text: Y"])
    assert headers == {"notification-title": "X", "notification-text": "Y"}


def test_resolve_icon_path_allows_within_dir(tmp_path: Path):
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")
    resolved = resolve_icon_path(str(icon), allowed_dirs=[tmp_path])
    assert resolved == icon.resolve()


def test_resolve_icon_path_rejects_outside_allowed_dir(tmp_path: Path):
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    icon = outside_dir / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")

    other_dir = tmp_path / "allowed_only"
    other_dir.mkdir()

    assert resolve_icon_path(str(icon), allowed_dirs=[other_dir]) is None


def test_resolve_icon_path_rejects_bad_extension(tmp_path: Path):
    bad_file = tmp_path / "payload.exe"
    bad_file.write_bytes(b"MZ")
    assert resolve_icon_path(str(bad_file), allowed_dirs=[tmp_path]) is None


def test_resolve_icon_path_rejects_missing_file(tmp_path: Path):
    missing = tmp_path / "does_not_exist.png"
    assert resolve_icon_path(str(missing), allowed_dirs=[tmp_path]) is None


def test_resolve_icon_path_none_icon_returns_none(tmp_path: Path):
    assert resolve_icon_path(None, allowed_dirs=[tmp_path]) is None


def test_resolve_icon_path_strips_file_scheme(tmp_path: Path):
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")
    resolved = resolve_icon_path(f"file://{icon}", allowed_dirs=[tmp_path])
    assert resolved == icon.resolve()
