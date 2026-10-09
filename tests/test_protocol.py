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
    p = NotificationPayload(title="Alert", text="something happened", sticky=True,
                             icon="icon.png", timeout=4500)
    wire = p.to_gntp()
    lines = wire.strip("\r\n").split("\r\n")
    headers = parse_gntp_headers(lines)
    restored = NotificationPayload.from_gntp_headers(headers)
    assert restored.title == "Alert"
    assert restored.text == "something happened"
    assert restored.sticky is True
    assert restored.icon == "icon.png"
    assert restored.timeout == 4500


def test_gntp_round_trip_omits_timeout_header_when_unset():
    p = NotificationPayload(title="Alert", text="body")
    wire = p.to_gntp()
    assert "Notification-Timeout" not in wire
    lines = wire.strip("\r\n").split("\r\n")
    restored = NotificationPayload.from_gntp_headers(parse_gntp_headers(lines))
    assert restored.timeout is None


def test_gntp_round_trip_zero_timeout_is_preserved():
    # 0 is a meaningful value (no auto-dismiss timer) and must not be
    # dropped the way `if self.timeout:` would (0 is falsy).
    p = NotificationPayload(title="Alert", text="body", timeout=0)
    wire = p.to_gntp()
    assert "Notification-Timeout: 0" in wire
    lines = wire.strip("\r\n").split("\r\n")
    restored = NotificationPayload.from_gntp_headers(parse_gntp_headers(lines))
    assert restored.timeout == 0


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


def test_try_parse_control_command_recognizes_dismiss_all():
    from osd_notification.protocol import try_parse_control_command, CONTROL_DISMISS_ALL
    import json

    msg = json.dumps({"command": "dismiss_all"})
    assert try_parse_control_command(msg) == CONTROL_DISMISS_ALL


def test_try_parse_control_command_is_case_insensitive():
    from osd_notification.protocol import try_parse_control_command, CONTROL_DISMISS_ALL
    import json

    msg = json.dumps({"command": "DISMISS_ALL"})
    assert try_parse_control_command(msg) == CONTROL_DISMISS_ALL


def test_try_parse_control_command_returns_none_for_notification_payload():
    from osd_notification.protocol import try_parse_control_command
    import json

    msg = json.dumps({"title": "Hello", "text": "World"})
    assert try_parse_control_command(msg) is None


def test_try_parse_control_command_returns_none_for_invalid_json():
    from osd_notification.protocol import try_parse_control_command
    assert try_parse_control_command("not json {{{") is None


def test_try_parse_control_command_returns_unknown_command_string():
    from osd_notification.protocol import try_parse_control_command, is_known_control_command
    import json

    msg = json.dumps({"command": "reboot"})
    command = try_parse_control_command(msg)
    assert command == "reboot"
    assert is_known_control_command(command) is False


def test_is_known_control_command():
    from osd_notification.protocol import is_known_control_command, CONTROL_DISMISS_ALL
    assert is_known_control_command(CONTROL_DISMISS_ALL) is True
    assert is_known_control_command("bogus") is False


def test_strip_wrapping_quotes():
    from osd_notification.protocol import strip_wrapping_quotes
    assert strip_wrapping_quotes('"C:\\icons\\foo.png"') == "C:\\icons\\foo.png"
    assert strip_wrapping_quotes("'C:\\icons\\foo.png'") == "C:\\icons\\foo.png"
    assert strip_wrapping_quotes("C:\\icons\\foo.png") == "C:\\icons\\foo.png"
    assert strip_wrapping_quotes('  "  padded.png  "  ') == "padded.png"
    assert strip_wrapping_quotes('"mismatched\'') == "\"mismatched'"


def test_resolve_icon_path_strips_quotes(tmp_path: Path):
    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")
    quoted = f'"{icon}"'
    resolved = resolve_icon_path(quoted, allowed_dirs=[tmp_path])
    assert resolved == icon.resolve()


def test_resolve_icon_path_case_insensitive_dir_match(tmp_path: Path, monkeypatch):
    # Force os.path.normcase to behave like Windows (case-insensitive,
    # backslash-normalized) regardless of the host platform running the
    # test, so this regression is checked even on a case-sensitive CI box.
    import osd_notification.protocol as protocol_module
    monkeypatch.setattr(protocol_module.os.path, "normcase", lambda p: str(p).lower())

    icon = tmp_path / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")
    mismatched_case_dir = Path(str(tmp_path).upper())
    resolved = resolve_icon_path(str(icon), allowed_dirs=[mismatched_case_dir])
    assert resolved == icon.resolve()


def test_resolve_icon_path_sandbox_disabled_allows_outside_dirs(tmp_path: Path):
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    icon = outside_dir / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")

    other_allowed_only = tmp_path / "allowed_only"
    other_allowed_only.mkdir()

    # Still rejected with a real allow-list that doesn't include it...
    assert resolve_icon_path(str(icon), allowed_dirs=[other_allowed_only]) is None
    # ...but allowed_dirs=None (sandbox disabled) accepts any existing image.
    assert resolve_icon_path(str(icon), allowed_dirs=None) == icon.resolve()


def test_resolve_icon_path_verbose_reports_reasons(tmp_path: Path):
    from osd_notification.protocol import IconRejectReason, resolve_icon_path_verbose

    assert resolve_icon_path_verbose(None, [tmp_path])[1] == IconRejectReason.EMPTY
    assert resolve_icon_path_verbose("", [tmp_path])[1] == IconRejectReason.EMPTY

    bad_ext = tmp_path / "not_an_image.exe"
    bad_ext.write_bytes(b"MZ")
    assert resolve_icon_path_verbose(str(bad_ext), [tmp_path])[1] == IconRejectReason.BAD_EXTENSION

    missing = tmp_path / "missing.png"
    assert resolve_icon_path_verbose(str(missing), [tmp_path])[1] == IconRejectReason.NOT_A_FILE

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    icon = outside_dir / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    reason = resolve_icon_path_verbose(str(icon), [other_dir])[1]
    assert reason == IconRejectReason.OUTSIDE_ALLOWED_DIRS

    ok_path, ok_reason = resolve_icon_path_verbose(str(icon), [outside_dir])
    assert ok_path == icon.resolve()
    assert ok_reason is None


def test_build_gntp_binary_section_round_trips():
    from osd_notification.protocol import build_gntp_binary_section, parse_gntp_binary_sections

    data = b"\x00\x01\r\n\r\nbinary\xff" * 3  # contains CRLFCRLF inside the data
    section = build_gntp_binary_section("abc123", data)
    assert section.startswith(b"Identifier: abc123\r\nLength: %d\r\n\r\n" % len(data))
    assert section.endswith(b"\r\n\r\n")
    assert parse_gntp_binary_sections(section) == {"abc123": data}


def test_parse_gntp_binary_sections_multiple_and_truncated():
    from osd_notification.protocol import build_gntp_binary_section, parse_gntp_binary_sections

    raw = build_gntp_binary_section("a", b"AAA") + build_gntp_binary_section("b", b"BBBB")
    assert parse_gntp_binary_sections(raw) == {"a": b"AAA", "b": b"BBBB"}
    assert parse_gntp_binary_sections(raw[:-8]) == {"a": b"AAA"}  # truncated second block dropped
    assert parse_gntp_binary_sections(b"garbage") == {}


def test_build_gntp_message_embeds_local_icon_as_resource(tmp_path: Path):
    from osd_notification.protocol import parse_gntp_binary_sections, extract_gntp_resource_id

    icon = tmp_path / "i.png"
    icon.write_bytes(b"PNGDATA\r\n\r\nmore")
    msg = NotificationPayload(title="T", text="b", icon=str(icon)).build_gntp_message()

    head, _, tail = msg.partition(b"\r\n\r\n")
    headers = parse_gntp_headers(head.decode().split("\r\n")[1:])
    resource_id = extract_gntp_resource_id(headers["notification-icon"])
    assert resource_id
    assert parse_gntp_binary_sections(tail)[resource_id] == b"PNGDATA\r\n\r\nmore"


def test_build_gntp_message_url_icon_is_plain_header_without_binary():
    msg = NotificationPayload(title="T", text="b", icon="https://example.com/i.png").build_gntp_message()
    assert b"Notification-Icon: https://example.com/i.png" in msg
    assert b"Identifier:" not in msg
    assert msg.endswith(b"\r\n\r\n")


def test_build_gntp_message_without_icon_has_no_icon_header():
    msg = NotificationPayload(title="T", text="b").build_gntp_message()
    assert b"Notification-Icon" not in msg
    assert b"Identifier:" not in msg


def test_build_gntp_message_uses_icon_data_over_path():
    msg = NotificationPayload(title="T", text="b", icon="whatever.png", icon_data=b"RAW").build_gntp_message()
    assert b"x-growl-resource://" in msg
    assert msg.endswith(b"RAW\r\n\r\n")


def test_udp_json_embeds_icon_base64_round_trip():
    p = NotificationPayload(title="T", text="b", icon_data=b"\x89PNG\x00\xff")
    d = p.to_dict()
    assert "icon_base64" in d
    restored = NotificationPayload.from_json(p.to_json())
    assert restored.icon_data == b"\x89PNG\x00\xff"


def test_icon_base64_invalid_raises():
    with pytest.raises(PayloadValidationError):
        NotificationPayload.from_dict({"title": "T", "icon_base64": "!!!not base64!!!"})


def test_icon_data_too_large_raises():
    from osd_notification.protocol import MAX_ICON_BYTES
    with pytest.raises(PayloadValidationError):
        NotificationPayload(title="T", icon_data=b"x" * (MAX_ICON_BYTES + 1))


def test_extract_gntp_resource_id():
    from osd_notification.protocol import extract_gntp_resource_id
    assert extract_gntp_resource_id("x-growl-resource://abc") == "abc"
    assert extract_gntp_resource_id("http://x/y.png") is None
    assert extract_gntp_resource_id("C:\\icons\\a.png") is None
