#!/usr/bin/env python3
"""
File: manager.py
Description: Owns the pool of currently-visible OSDNotification windows.
             Each notification is now its own widget instance (rather than
             one window being reused/overwritten), so multiple notifications
             can be on screen at once. `notification.position` supports
             three placement modes:
               - a fixed value (e.g. `bottom_right`): always the same spot
               - `auto`: cascades diagonally across the screen from a
                 starting corner (`auto_anchor`), wrapping back to the
                 start once it'd run off the opposite edge — the same
                 placement Windows uses for new windows (e.g. opening
                 several `cmd.exe` windows with default placement)
               - `random`: places each notification at a random spot
                 anywhere on the screen, actively avoiding overlap with
                 whatever else is currently visible, rather than following
                 any repeating path
             `dismiss_all()` closes every currently visible one
             immediately, for the `--dismiss-all` CLI command and control
             message.
License: MIT
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from PyQt5.QtCore import QObject
from PyQt5.QtWidgets import QApplication

from .config import OSDConfigManager
from .dispatcher import NotificationDispatcher
from .logging_setup import get_logger
from .protocol import NotificationPayload
from .widget import OSDNotification

logger = get_logger("OSDNotifier.Manager")


class NotificationManager(QObject):
    """Creates, positions, tracks, and tears down OSDNotification windows.

    `dispatcher.show_notification` is the thread-safe entry point network
    servers deliver payloads through (same pattern as the old per-widget
    dispatcher, just owned centrally now so multiple windows can coexist).
    """

    def __init__(self, config: Optional[OSDConfigManager] = None):
        super().__init__()
        self.config = config or OSDConfigManager()
        self._active: List[OSDNotification] = []
        self._cascade_index = 0

        self.dispatcher = NotificationDispatcher()
        self.dispatcher.show_notification.connect(self.spawn)

    # ------------------------------------------------------------------ #
    # Spawning
    # ------------------------------------------------------------------ #

    def _new_widget(self) -> OSDNotification:
        widget = OSDNotification(self.config)
        widget.dismissed.connect(self._on_widget_dismissed)
        return widget

    def spawn(self, payload: NotificationPayload) -> OSDNotification:
        """Show a notification built from a validated payload (the path
        used for every network/CLI-delivered notification)."""
        widget = self._new_widget()
        widget.handle_remote_notification(payload)
        self._register(widget)
        return widget

    def spawn_glyph(self, char_val: str, hex_str: str = "",
                     sticky: Optional[bool] = None, timeout: Optional[int] = None) -> OSDNotification:
        """Show a plain glyph/character notification (used by the bare
        `--test` demo, which has no title/text of its own)."""
        widget = self._new_widget()
        widget.show_character(char_val, hex_str=hex_str, sticky=sticky, timeout=timeout)
        self._register(widget)
        return widget

    def _register(self, widget: OSDNotification) -> None:
        if self.config.is_auto_position():
            x, y = self._compute_cascade_position(widget, self._cascade_index)
            widget.move(x, y)
            self._cascade_index += 1
        elif self.config.is_random_position():
            x, y = self._compute_random_position(widget)
            widget.move(x, y)
        self._active.append(widget)

    # ------------------------------------------------------------------ #
    # Cascade placement (mirrors Windows' default new-window placement)
    # ------------------------------------------------------------------ #

    def _compute_cascade_position(self, widget: OSDNotification, index: int) -> Tuple[int, int]:
        """The `index`-th cascade slot: starts at `auto_anchor`'s corner and
        steps diagonally *away* from it by `cascade_step` pixels per slot,
        wrapping back to the start once the diagonal run would put the
        window past the opposite edge of the screen."""
        anchor = self.config.get_auto_anchor()
        margin = self.config.get_margin()
        step = self.config.get_cascade_step()

        screen = QApplication.primaryScreen().availableGeometry()
        w, h = widget.width(), widget.height()

        if "left" in anchor:
            start_x, dir_x = screen.x() + margin, 1
        elif "right" in anchor:
            start_x, dir_x = screen.x() + screen.width() - w - margin, -1
        else:
            start_x, dir_x = screen.x() + (screen.width() - w) // 2, 1

        if "top" in anchor:
            start_y, dir_y = screen.y() + margin, 1
        elif "bottom" in anchor:
            start_y, dir_y = screen.y() + screen.height() - h - margin, -1
        else:
            start_y, dir_y = screen.y() + (screen.height() - h) // 2, 1

        if step <= 0:
            return start_x, start_y

        usable_w = max(1, screen.width() - w - 2 * margin)
        usable_h = max(1, screen.height() - h - 2 * margin)
        max_steps = max(1, min(usable_w // step, usable_h // step))

        slot = index % max_steps
        x = start_x + dir_x * step * slot
        y = start_y + dir_y * step * slot
        return int(x), int(y)

    # ------------------------------------------------------------------ #
    # Random placement — truly anywhere on screen, not a repeating path
    # ------------------------------------------------------------------ #

    _RANDOM_PLACEMENT_ATTEMPTS = 20

    def _compute_random_position(self, widget: OSDNotification) -> Tuple[int, int]:
        """Pick a random spot anywhere on the available screen (respecting
        `margin`), trying several candidates and keeping whichever overlaps
        least with notifications already on screen — so repeated
        notifications spread out across the whole monitor instead of
        following any fixed path or repeating pattern."""
        margin = self.config.get_margin()
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = widget.width(), widget.height()

        min_x = screen.x() + margin
        max_x = screen.x() + screen.width() - w - margin
        min_y = screen.y() + margin
        max_y = screen.y() + screen.height() - h - margin

        # Widget wider/taller than the usable screen area: only one spot fits.
        if max_x < min_x:
            max_x = min_x
        if max_y < min_y:
            max_y = min_y

        best_pos: Optional[Tuple[int, int]] = None
        best_overlap: Optional[int] = None

        for _ in range(self._RANDOM_PLACEMENT_ATTEMPTS):
            x = random.randint(min_x, max_x)
            y = random.randint(min_y, max_y)
            overlap = self._overlap_area(x, y, w, h)
            if overlap == 0:
                return x, y
            if best_overlap is None or overlap < best_overlap:
                best_pos, best_overlap = (x, y), overlap

        return best_pos if best_pos is not None else (min_x, min_y)

    def _overlap_area(self, x: int, y: int, w: int, h: int) -> int:
        """Total overlapping pixel area between a candidate rect and every
        currently-active notification's actual geometry."""
        total = 0
        for existing in self._active:
            ex, ey = existing.x(), existing.y()
            ew, eh = existing.width(), existing.height()
            overlap_w = max(0, min(x + w, ex + ew) - max(x, ex))
            overlap_h = max(0, min(y + h, ey + eh) - max(y, ey))
            total += overlap_w * overlap_h
        return total

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def _on_widget_dismissed(self, widget: OSDNotification) -> None:
        if widget in self._active:
            self._active.remove(widget)
        widget.deleteLater()
        if not self._active:
            # Screen is clear again — restart the cascade from the anchor
            # corner instead of continuing to creep across the screen.
            self._cascade_index = 0

    def dismiss_all(self) -> None:
        """Immediately close every currently visible notification (no fade
        animation) — used by the `--dismiss-all` CLI command and the tray."""
        if not self._active:
            return
        logger.info("Dismissing %d active notification(s).", len(self._active))
        # Snapshot: dismiss() triggers _on_widget_dismissed, which mutates
        # self._active — iterate over a copy to avoid skipping entries.
        for widget in list(self._active):
            widget.dismiss(animate=False)

    @property
    def active_count(self) -> int:
        return len(self._active)
