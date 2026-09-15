#!/usr/bin/env python3

# File: src/osd_notification/widget.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Frameless, animated OSD (On-Screen Display) notification
#              widget supporting sticky notifications, images, glyphs,
#              auto-resizing text wrapping, and screen-edge positioning.
# License: MIT


from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer
from PyQt5.QtGui import QFont, QFontMetrics, QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from .config import OSDConfigManager
from .dispatcher import NotificationDispatcher
from .logging_setup import get_logger
from .protocol import NotificationPayload, resolve_icon_path

logger = get_logger("OSDNotifier.Widget")

_ZERO_WIDTH_SPACE = "\u200b"


def insert_soft_breaks(text: str, max_run: int) -> str:
    """Insert zero-width space break opportunities into any run of
    non-whitespace characters longer than ``max_run``.

    Qt's word-wrap (``Qt.TextWordWrap``) only breaks at existing word
    boundaries (whitespace). A single "word" with no spaces at all — a long
    URL, a run of repeated characters, base64, etc. — is wider than the
    window and will NOT wrap; it simply overflows past the label's edge no
    matter how tall the window is made. A zero-width space is invisible but
    is still a valid break point for Qt's line-wrapping engine, so this
    gives long unbroken runs somewhere to break without changing how the
    text visibly reads.
    """
    if not text or max_run <= 0:
        return text

    out = []
    run_len = 0
    for ch in text:
        if ch.isspace():
            run_len = 0
            out.append(ch)
            continue
        if run_len >= max_run:
            out.append(_ZERO_WIDTH_SPACE)
            run_len = 0
        out.append(ch)
        run_len += 1
    return "".join(out)


class OSDNotification(QWidget):
    """Frameless OSD window supporting sticky notifications, images,
    auto-sizing, and network-triggered updates via ``NotificationDispatcher``."""

    def __init__(self, config: Optional[OSDConfigManager] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config = config or OSDConfigManager()
        self.anim: Optional[QPropertyAnimation] = None
        self.dismiss_timer: Optional[QTimer] = None

        self.dispatcher = NotificationDispatcher()
        self.dispatcher.show_notification.connect(self.handle_remote_notification)

        self._init_ui()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _init_ui(self) -> None:
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)  # type: ignore[attr-defined]
        self.setAttribute(Qt.WA_TranslucentBackground)  # type: ignore[attr-defined]

        self.setWindowOpacity(self.config.get_opacity())
        self.setFixedSize(*self.config.get_base_size())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.frame = QFrame(self)
        bg_color = self.config.get_color("appearance", "bg_color", "#1E1E2E")
        border_color = self.config.get_color("appearance", "border_color", "#89B4FA")

        self.frame.setStyleSheet(
            f"QFrame {{ background-color: {bg_color}; "
            f"border: 2px solid {border_color}; border-radius: 15px; }}"
        )
        self.frame_layout = QVBoxLayout(self.frame)
        self.frame_layout.setContentsMargins(15, 15, 15, 15)

        self.visual_label = QLabel(self.frame)
        self.visual_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]

        font_family = self.config.get_val("appearance", "font_family", "Consolas")
        font_size = self.config.get_int("appearance", "char_size", 64, min_val=8, max_val=200)
        self.visual_label.setFont(QFont(font_family, font_size))

        self.details_label = QLabel(self.frame)
        self.details_label.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]
        self.details_label.setWordWrap(True)
        self.details_label.setFont(QFont(font_family, 12, QFont.Bold))

        text_color = self.config.get_color("appearance", "text_color", "#CDD6F4")
        self.visual_label.setStyleSheet(f"color: {text_color}; border: none; background: transparent;")
        self.details_label.setStyleSheet(f"color: {text_color}; border: none; background: transparent;")

        self.frame_layout.addWidget(self.visual_label, stretch=0)
        self.frame_layout.addWidget(self.details_label, stretch=1)
        layout.addWidget(self.frame)

    def _chrome_width(self) -> int:
        """Total horizontal padding consumed by the outer layout and inner
        frame margins — subtracted from the window width to get the actual
        space available for wrapped text."""
        outer = self.layout().contentsMargins()
        inner = self.frame_layout.contentsMargins()
        return outer.left() + outer.right() + inner.left() + inner.right()

    def _adjust_window_size_for_text(self, subtitle: str) -> str:
        """Dynamically resize window width *and* height to fit the subtitle,
        with wrapping measured against the actual available label width —
        not just a flat size bump — so long text always gets enough
        vertical space instead of being clipped.

        Also inserts soft break points (see ``insert_soft_breaks``) into any
        unbroken run of non-whitespace longer than
        ``window.soft_wrap_chars``, since Qt's word-wrap can't break a
        single "word" on its own and would otherwise let it overflow past
        the window edge regardless of height.

        Returns the (possibly soft-broken) text that was measured — callers
        MUST use this exact string for ``details_label.setText(...)`` so
        what's measured and what's rendered always match.

        All dimensions come from the ``[window]`` config section and are
        re-read on every call, so edits to the INI file take effect on the
        next notification without a restart.
        """
        base_width, base_height = self.config.get_base_size()

        if not subtitle:
            self.setFixedSize(base_width, base_height)
            return subtitle

        subtitle = insert_soft_breaks(subtitle, self.config.get_soft_wrap_chars())

        min_width = self.config.get_min_width()
        max_width = self.config.get_max_width()
        max_height = self.config.get_max_height()
        text_padding = self.config.get_text_padding()

        font_metrics = QFontMetrics(self.details_label.font())
        raw_text_width = font_metrics.horizontalAdvance(subtitle)
        dynamic_width = max(min_width, min(raw_text_width + text_padding, max_width))

        # Determine the actual space available to the wrapped label at this
        # window width, then check whether the text needs more than one
        # line there — comparing rendered heights directly is unreliable
        # since Qt's word-wrap bounding rect includes extra leading even
        # for single-line text.
        chrome_width = self._chrome_width()
        inner_width = max(10, dynamic_width - chrome_width)

        if raw_text_width <= inner_width:
            # Fits on a single line: no extra height needed.
            dynamic_height = base_height
        else:
            wrapped_rect = font_metrics.boundingRect(
                QRect(0, 0, inner_width, 0),
                int(Qt.TextWordWrap) | int(Qt.AlignHCenter),
                subtitle,
            )
            single_line_height = font_metrics.lineSpacing()
            extra_text_height = max(0, wrapped_rect.height() - single_line_height)
            padding = self.config.get_extra_height()
            dynamic_height = min(base_height + extra_text_height + padding, max_height)

        self.setFixedSize(dynamic_width, dynamic_height)
        return subtitle

    # ------------------------------------------------------------------ #
    # Public display API
    # ------------------------------------------------------------------ #

    def show_character(self, char_val: str, hex_str: str = "",
                        sticky: Optional[bool] = None, timeout: Optional[int] = None) -> None:
        subtitle = f"U+{hex_str.upper()}" if hex_str else ""
        subtitle = self._adjust_window_size_for_text(subtitle)

        self.visual_label.clear()
        self.visual_label.setText(char_val)
        self.details_label.setText(subtitle)
        self._trigger_display(sticky=sticky, timeout=timeout)

    def show_image(self, image_source: Union[str, Path, QPixmap, QIcon], subtitle: str = "",
                    max_size: Optional[Tuple[int, int]] = None,
                    sticky: Optional[bool] = None, timeout: Optional[int] = None) -> None:
        max_size = max_size or self.config.get_icon_max_size()
        subtitle = self._adjust_window_size_for_text(subtitle)
        self.visual_label.clear()

        pixmap = QPixmap()
        if isinstance(image_source, (str, Path)):
            pixmap.load(str(image_source))
        elif isinstance(image_source, QPixmap):
            pixmap = image_source
        elif isinstance(image_source, QIcon):
            pixmap = image_source.pixmap(max_size[0], max_size[1])

        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                max_size[0], max_size[1],
                Qt.KeepAspectRatio,  # type: ignore[attr-defined]
                Qt.SmoothTransformation,  # type: ignore[attr-defined]
            )
            self.visual_label.setPixmap(scaled_pixmap)
        else:
            logger.warning("Failed to load icon image: %s", image_source)
            self.visual_label.setText("\u26a0\ufe0f")

        self.details_label.setText(subtitle)
        self._trigger_display(sticky=sticky, timeout=timeout)

    def handle_remote_notification(self, payload: NotificationPayload) -> None:
        """Render a validated ``NotificationPayload`` received from a network server."""
        allowed_dirs = self.config.get_allowed_icon_dirs()
        icon_path = resolve_icon_path(payload.icon, allowed_dirs)

        if icon_path is not None:
            self.show_image(icon_path, subtitle=payload.text or payload.title,
                             sticky=payload.sticky, timeout=payload.timeout)
            return

        if payload.icon:
            logger.info("Ignoring unresolved/unsafe icon reference: %r", payload.icon)

        display_char = payload.title if len(payload.title) <= 2 else "\U0001f514"
        subtitle = payload.text if len(payload.title) <= 2 else f"{payload.title}\n{payload.text}"
        subtitle = self._adjust_window_size_for_text(subtitle)
        self.visual_label.clear()
        self.visual_label.setText(display_char)
        self.details_label.setText(subtitle)
        self._trigger_display(sticky=payload.sticky, timeout=payload.timeout)

    # ------------------------------------------------------------------ #
    # Display lifecycle
    # ------------------------------------------------------------------ #

    def _is_sticky(self, sticky_param: Optional[bool]) -> bool:
        if sticky_param is not None:
            return sticky_param
        return self.config.get_bool("notification", "sticky", False)

    def _get_timeout(self, timeout_param: Optional[int]) -> int:
        if timeout_param is not None:
            return timeout_param
        return self.config.get_timeout_ms()

    def _trigger_display(self, sticky: Optional[bool] = None, timeout: Optional[int] = None) -> None:
        if self.dismiss_timer:
            self.dismiss_timer.stop()

        self._position_window()
        self.show()
        self._fade_in()

        if not self._is_sticky(sticky):
            duration = self._get_timeout(timeout)
            if duration > 0:
                self.dismiss_timer = QTimer.singleShot(duration, self._fade_out)

    def _position_window(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()  # type: ignore[union-attr]
        pos_setting = self.config.get_position()
        margin = self.config.get_margin()

        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2

        if "left" in pos_setting:
            x = margin
        elif "right" in pos_setting:
            x = screen.width() - self.width() - margin

        if "top" in pos_setting or "up" in pos_setting:
            y = margin
        elif "bottom" in pos_setting or "down" in pos_setting:
            y = screen.height() - self.height() - margin

        self.move(x, y)

    def _fade_in(self) -> None:
        target_opacity = self.config.get_opacity()
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(250)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(target_opacity)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.start()

    def _fade_out(self) -> None:
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(350)
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.0)
        self.anim.setEasingCurve(QEasingCurve.InCubic)
        self.anim.finished.connect(self.hide)
        self.anim.start()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._fade_out()
        super().mousePressEvent(event)
