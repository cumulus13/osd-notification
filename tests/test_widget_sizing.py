#!/usr/bin/env python3
"""
File: test_widget_sizing.py
Description: Verifies OSDNotification._adjust_window_size_for_text grows
             the window height to fit wrapped multi-line text (and does
             NOT inflate height for text that fits on a single line),
             using the offscreen Qt platform plugin so it runs headless.
License: MIT
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from osd_notification.config import OSDConfigManager  # noqa: E402
from osd_notification.widget import OSDNotification  # noqa: E402

SHORT_TEXT = "Build OK"
LONG_TEXT = (
    "This is a very long description subtitle that will automatically "
    "wrap across multiple lines instead of being clipped off the bottom "
    "edge of the notification window."
)
UNBROKEN_TEXT = "X" * 70 + "C" * 80 + "."  # no spaces at all — nothing to word-wrap on


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def widget(qapp, tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(os.path, "expandvars", lambda s: str(tmp_path) if "USERPROFILE" in s else s)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    config = OSDConfigManager(app_name="osd-notification-widget-test")
    return OSDNotification(config)


def test_empty_subtitle_uses_base_size(widget):
    widget._adjust_window_size_for_text("")
    base_width, base_height = widget.config.get_base_size()
    assert widget.size().width() == base_width
    assert widget.size().height() == base_height


def test_short_single_line_text_does_not_grow_height(widget):
    base_width, base_height = widget.config.get_base_size()
    widget._adjust_window_size_for_text(SHORT_TEXT)
    assert widget.size().height() == base_height


def test_long_text_wraps_and_grows_height(widget):
    base_width, base_height = widget.config.get_base_size()
    widget._adjust_window_size_for_text(LONG_TEXT)
    assert widget.size().height() > base_height
    assert widget.size().width() == widget.config.get_max_width()


def test_extremely_long_text_is_capped_at_max_height(widget):
    huge_text = LONG_TEXT * 8
    widget._adjust_window_size_for_text(huge_text)
    assert widget.size().height() == widget.config.get_max_height()


def test_growing_then_shrinking_text_resets_height(widget):
    widget._adjust_window_size_for_text(LONG_TEXT * 8)
    grown_height = widget.size().height()

    widget._adjust_window_size_for_text(SHORT_TEXT)
    _, base_height = widget.config.get_base_size()

    assert widget.size().height() == base_height
    assert widget.size().height() < grown_height


def test_unbroken_run_gets_soft_break_points(widget):
    from PyQt5.QtGui import QFontMetrics

    displayed = widget._adjust_window_size_for_text(UNBROKEN_TEXT)
    assert "\u200b" in displayed  # zero-width space inserted as a break point

    # No single run between break points should be wider than the space
    # actually available to the wrapped label.
    import re
    fm = QFontMetrics(widget.details_label.font())
    inner_width = widget.size().width() - widget._chrome_width()
    runs = re.split(r"[\s\u200b]+", displayed)
    longest_run_width = max((fm.horizontalAdvance(r) for r in runs if r), default=0)
    assert longest_run_width <= inner_width


def test_unbroken_run_still_grows_window_height(widget):
    _, base_height = widget.config.get_base_size()
    widget._adjust_window_size_for_text(UNBROKEN_TEXT)
    assert widget.size().height() > base_height


def test_short_text_gets_no_soft_breaks(widget):
    displayed = widget._adjust_window_size_for_text(SHORT_TEXT)
    assert displayed == SHORT_TEXT
    assert "\u200b" not in displayed


def test_insert_soft_breaks_short_run_unchanged():
    from osd_notification.widget import insert_soft_breaks
    assert insert_soft_breaks("hello world", max_run=30) == "hello world"


def test_insert_soft_breaks_empty_string():
    from osd_notification.widget import insert_soft_breaks
    assert insert_soft_breaks("", max_run=30) == ""


def test_insert_soft_breaks_long_run_gets_breaks():
    from osd_notification.widget import insert_soft_breaks
    result = insert_soft_breaks("X" * 100, max_run=30)
    assert "\u200b" in result
    # Removing the zero-width spaces must reconstruct the original text.
    assert result.replace("\u200b", "") == "X" * 100
    # No segment between breaks should exceed max_run characters.
    for segment in result.split("\u200b"):
        assert len(segment) <= 30


def test_insert_soft_breaks_resets_on_whitespace():
    from osd_notification.widget import insert_soft_breaks
    text = ("A" * 25) + " " + ("B" * 25)
    result = insert_soft_breaks(text, max_run=30)
    # Neither run alone reaches max_run, so no break should be inserted.
    assert "\u200b" not in result


def test_insert_soft_breaks_zero_max_run_is_noop():
    from osd_notification.widget import insert_soft_breaks
    assert insert_soft_breaks("X" * 50, max_run=0) == "X" * 50
