#!/usr/bin/env python3

# File: tests/test_config.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Unit tests for osd_notification.config.OSDConfigManager.
# License: MIT


import os

import pytest

from osd_notification.config import OSDConfigManager


@pytest.fixture()
def cm(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(os.path, "expandvars", lambda s: str(tmp_path) if "USERPROFILE" in s else s)
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
