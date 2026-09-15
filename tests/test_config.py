#!/usr/bin/env python3

# File: tests/test_config.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Unit tests for osd_notification.config.OSDConfigManager.
# License: MIT


import os
from pathlib import Path

import pytest

from osd_notification.config import OSDConfigManager


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    # Isolate the config dir on every platform: the Windows branch reads
    # %USERPROFILE%, the POSIX branch reads Path.home() — patch both so a
    # test run never touches (or leaks state from) the real home directory.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(os.path, "expandvars", lambda s: str(tmp_path) if "USERPROFILE" in s else s)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    manager = OSDConfigManager(app_name="osd-notification-test")
    yield manager


def test_creates_defaults_on_first_run(cm: OSDConfigManager):
    assert cm.get_val("notification", "position", "") == "center_center"
    assert cm.get_bool("server", "enabled", True) is False
    assert cm.config_path.exists()


def test_get_opacity_clamped(cm: OSDConfigManager):
    cm.write_config("notification", "opacity", "5.0")
    assert cm.get_opacity() == 1.0

    cm.write_config("notification", "opacity", "-1.0")
    assert cm.get_opacity() == 0.05


def test_get_int_invalid_falls_back_to_default(cm: OSDConfigManager):
    cm.write_config("notification", "timeout", "not-a-number")
    assert cm.get_timeout_ms() == 3000


def test_get_color_invalid_falls_back_to_default(cm: OSDConfigManager):
    cm.write_config("appearance", "bg_color", "not-a-color")
    assert cm.get_color("appearance", "bg_color", "#1E1E2E") == "#1E1E2E"

    cm.write_config("appearance", "bg_color", "#FFAA00")
    assert cm.get_color("appearance", "bg_color", "#1E1E2E") == "#FFAA00"


def test_get_position_rejects_unknown_value(cm: OSDConfigManager):
    cm.write_config("notification", "position", "nowhere")
    assert cm.get_position() == "center_center"


def test_as_display_dict_masks_secrets(cm: OSDConfigManager):
    cm.add_section("oauth")
    cm.write_config("oauth", "token", "abcdef123456")
    display = cm.as_display_dict()
    assert display["oauth"]["token"] != "abcdef123456"
    assert display["oauth"]["token"].startswith("abcd")


def test_window_geometry_defaults(cm: OSDConfigManager):
    assert cm.get_base_size() == (240, 240)
    assert cm.get_min_width() == 240
    assert cm.get_max_width() == 380
    assert cm.get_text_padding() == 40
    assert cm.get_extra_height() == 40
    assert cm.get_icon_max_size() == (160, 140)


def test_window_geometry_reads_overrides(cm: OSDConfigManager):
    cm.write_config("window", "base_width", "300")
    cm.write_config("window", "max_width", "500")
    cm.write_config("window", "text_padding", "10")
    assert cm.get_base_size() == (300, 240)
    assert cm.get_max_width() == 500
    assert cm.get_text_padding() == 10


def test_max_width_never_below_min_width(cm: OSDConfigManager):
    cm.write_config("window", "min_width", "300")
    cm.write_config("window", "max_width", "100")
    assert cm.get_max_width() == 300


def test_tray_defaults(cm: OSDConfigManager):
    assert cm.get_bool("tray", "enabled", False) is True
    assert cm.get_val("tray", "tooltip", "") == "OSD Notification"
    assert cm.get_val("tray", "icon_path", "sentinel") == "sentinel"
    assert cm.get_bool("tray", "notify_on_server_toggle", False) is True


def test_reset_section_discards_stale_values(cm: OSDConfigManager):
    cm.write_config("window", "max_height", "100")
    cm.write_config("window", "max_width", "50")
    assert cm.get_max_height() == 240  # clamped up to base_height, but still wrong/tiny
    assert cm.get_max_width() == 240

    cm.reset_section("window")

    assert cm.get_max_height() == 600
    assert cm.get_max_width() == 380


def test_reset_section_unknown_raises(cm: OSDConfigManager):
    from osd_notification.exceptions import ConfigError
    with pytest.raises(ConfigError):
        cm.reset_section("does-not-exist")


def test_reset_all_resets_every_section(cm: OSDConfigManager):
    cm.write_config("notification", "timeout", "999")
    cm.write_config("window", "max_width", "50")
    cm.reset_all()
    assert cm.get_timeout_ms() == 3000
    assert cm.get_max_width() == 380


def test_position_defaults_to_center_center(cm: OSDConfigManager):
    assert cm.get_position() == "center_center"
    assert cm.is_auto_position() is False


def test_position_auto_is_accepted(cm: OSDConfigManager):
    cm.write_config("notification", "position", "auto")
    assert cm.get_position() == "auto"
    assert cm.is_auto_position() is True


def test_position_random_is_accepted(cm: OSDConfigManager):
    cm.write_config("notification", "position", "random")
    assert cm.get_position() == "random"
    assert cm.is_random_position() is True
    assert cm.is_auto_position() is False


def test_position_invalid_value_falls_back_to_default(cm: OSDConfigManager):
    cm.write_config("notification", "position", "nowhere")
    assert cm.get_position() == "center_center"


def test_auto_anchor_default_and_validation(cm: OSDConfigManager):
    assert cm.get_auto_anchor() == "bottom_right"

    cm.write_config("notification", "auto_anchor", "top_left")
    assert cm.get_auto_anchor() == "top_left"

    cm.write_config("notification", "auto_anchor", "auto")  # not a valid anchor
    assert cm.get_auto_anchor() == "bottom_right"

    cm.write_config("notification", "auto_anchor", "nonsense")
    assert cm.get_auto_anchor() == "bottom_right"


def test_cascade_step_default_and_clamping(cm: OSDConfigManager):
    assert cm.get_cascade_step() == 30

    cm.write_config("notification", "stack_gap", "-5")
    assert cm.get_cascade_step() == 0

    cm.write_config("notification", "stack_gap", "9999")
    assert cm.get_cascade_step() == 200
