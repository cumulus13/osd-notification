#!/usr/bin/env python3
"""
File: test_manager.py
Description: Offscreen tests for NotificationManager — auto-position
             cascading (mirrors Windows' default new-window placement,
             e.g. opening several cmd.exe windows), the reset-on-empty
             behavior, and dismiss_all().
License: MIT
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5")

from pathlib import Path  # noqa: E402

from PyQt5.QtWidgets import QApplication  # noqa: E402

from osd_notification.config import OSDConfigManager  # noqa: E402
from osd_notification.manager import NotificationManager  # noqa: E402
from osd_notification.protocol import NotificationPayload  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def config(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(os.path, "expandvars", lambda s: str(tmp_path) if "USERPROFILE" in s else s)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    cfg = OSDConfigManager(app_name="osd-notification-manager-test")
    cfg.write_config("notification", "position", "auto")
    cfg.write_config("notification", "sticky", "True")  # stay visible so we can inspect them
    return OSDConfigManager(app_name="osd-notification-manager-test")  # reload


@pytest.fixture()
def manager(config):
    return NotificationManager(config)


def _payload(title: str) -> NotificationPayload:
    return NotificationPayload(title=title, text=f"body of {title}")


def test_spawn_returns_visible_widget(manager):
    widget = manager.spawn(_payload("One"))
    assert widget.isVisible()
    assert manager.active_count == 1


def test_cascade_spreads_across_both_axes(manager):
    # Real cascading (like Windows placing new cmd.exe windows) moves
    # diagonally, not just stacked in a single column/row from one corner.
    widgets = [manager.spawn(_payload(f"N{i}")) for i in range(5)]
    positions = [(w.pos().x(), w.pos().y()) for w in widgets]

    assert len(set(positions)) == len(positions)  # no two land on the same spot
    xs = {x for x, _ in positions}
    ys = {y for _, y in positions}
    assert len(xs) > 1  # spreads across X
    assert len(ys) > 1  # spreads across Y


def test_cascade_wraps_around_instead_of_running_off_screen(manager):
    # Spawn enough that the diagonal run would exceed the screen — it must
    # wrap back to an earlier slot instead of placing windows off-screen.
    widgets = [manager.spawn(_payload(f"N{i}")) for i in range(30)]
    first_position = (widgets[0].pos().x(), widgets[0].pos().y())
    later_positions = [(w.pos().x(), w.pos().y()) for w in widgets[1:]]
    assert first_position in later_positions


def test_cascade_restarts_once_screen_is_cleared(manager):
    first = manager.spawn(_payload("SameText"))
    first_pos = (first.pos().x(), first.pos().y())

    manager.spawn(_payload("Two"))
    manager.spawn(_payload("Three"))

    manager.dismiss_all()
    assert manager.active_count == 0
    assert manager._cascade_index == 0

    # Same payload text (so the widget resolves to the same size) should
    # land in the exact same slot the cascade started at.
    fresh = manager.spawn(_payload("SameText"))
    assert (fresh.pos().x(), fresh.pos().y()) == first_pos


def test_dismiss_all_hides_every_active_widget(manager):
    w1 = manager.spawn(_payload("One"))
    w2 = manager.spawn(_payload("Two"))
    w3 = manager.spawn(_payload("Three"))
    assert manager.active_count == 3

    manager.dismiss_all()

    assert manager.active_count == 0
    assert not w1.isVisible()
    assert not w2.isVisible()
    assert not w3.isVisible()


def test_dismiss_all_on_empty_manager_is_a_noop(manager):
    manager.dismiss_all()  # must not raise
    assert manager.active_count == 0


def test_dismissing_one_does_not_move_the_others(manager):
    # Unlike a stack, cascaded windows are fixed at their assigned slot —
    # closing one doesn't reflow the rest (matches real OS window
    # cascading: closing one cmd.exe window doesn't move the others).
    w1 = manager.spawn(_payload("One"))
    w2 = manager.spawn(_payload("Two"))
    w3 = manager.spawn(_payload("Three"))

    w2_pos_before = (w2.pos().x(), w2.pos().y())
    w3_pos_before = (w3.pos().x(), w3.pos().y())

    w1.dismiss(animate=False)

    assert manager.active_count == 2
    assert (w2.pos().x(), w2.pos().y()) == w2_pos_before
    assert (w3.pos().x(), w3.pos().y()) == w3_pos_before


def test_fixed_position_mode_does_not_cascade(config):
    config.write_config("notification", "position", "bottom_right")
    config = OSDConfigManager(app_name="osd-notification-manager-test")
    manager = NotificationManager(config)

    w1 = manager.spawn(_payload("One"))
    w2 = manager.spawn(_payload("Two"))

    # Without auto positioning, nothing repositions notifications relative
    # to each other — both land at the exact same fixed corner.
    assert (w1.pos().x(), w1.pos().y()) == (w2.pos().x(), w2.pos().y())


def test_spawn_glyph_shows_local_demo(manager):
    widget = manager.spawn_glyph("\U0001f680", hex_str="1F680")
    assert widget.isVisible()
    assert manager.active_count == 1


def test_random_position_spreads_across_screen():
    from unittest import mock
    from PyQt5.QtCore import QRect
    from PyQt5.QtWidgets import QApplication as _QApp

    from osd_notification.config import OSDConfigManager

    cfg = OSDConfigManager(app_name="osd-notification-manager-random-test")
    cfg.write_config("notification", "position", "random")
    cfg.write_config("notification", "sticky", "True")
    cfg = OSDConfigManager(app_name="osd-notification-manager-random-test")

    manager = NotificationManager(cfg)

    with mock.patch.object(_QApp, "primaryScreen") as mock_screen:
        mock_screen.return_value.availableGeometry.return_value = QRect(0, 0, 1920, 1080)
        widgets = [manager.spawn(_payload(f"N{i}")) for i in range(8)]

    positions = [(w.pos().x(), w.pos().y()) for w in widgets]
    assert len(set(positions)) == len(positions)  # no two in the exact same spot

    xs = {x for x, _ in positions}
    ys = {y for _, y in positions}
    assert len(xs) > 1 and len(ys) > 1  # genuinely scattered, not one line/path

    # On a realistic screen size, the overlap-avoidance should find
    # non-overlapping spots for all of them.
    def overlap(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ow = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        oh = max(0, min(ay + ah, by + bh) - max(ay, by))
        return ow * oh

    rects = [(w.pos().x(), w.pos().y(), w.width(), w.height()) for w in widgets]
    overlapping_pairs = sum(
        1 for i in range(len(rects)) for j in range(i + 1, len(rects))
        if overlap(rects[i], rects[j]) > 0
    )
    assert overlapping_pairs == 0


def test_random_position_does_not_repeat_a_fixed_path():
    # Regression guard for the original complaint: successive random spawns
    # should not follow the same deterministic diagonal every time.
    from unittest import mock
    from PyQt5.QtCore import QRect
    from PyQt5.QtWidgets import QApplication as _QApp

    from osd_notification.config import OSDConfigManager

    cfg = OSDConfigManager(app_name="osd-notification-manager-random-test2")
    cfg.write_config("notification", "position", "random")
    cfg.write_config("notification", "sticky", "True")
    cfg = OSDConfigManager(app_name="osd-notification-manager-random-test2")

    manager = NotificationManager(cfg)

    with mock.patch.object(_QApp, "primaryScreen") as mock_screen:
        mock_screen.return_value.availableGeometry.return_value = QRect(0, 0, 1920, 1080)
        manager.dismiss_all()
        samples = set()
        for _ in range(15):
            widget = manager.spawn(_payload("Same"))
            samples.add((widget.pos().x(), widget.pos().y()))
            manager.dismiss_all()  # clear each time so overlap-avoidance can't force spread
    assert len(samples) > 1
