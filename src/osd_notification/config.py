#!/usr/bin/env python3

# File: src/osd_notification/config.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Typed, validated configuration manager for osd_notification,
#              backed by `configset.configset_ini`. Auto-creates a config file
#              with sane defaults on first run, coerces/validates every read,
#              and clamps values to safe operating ranges.
# License: MIT

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from configset import configset_ini

from .exceptions import ConfigError
from .logging_setup import get_logger

logger = get_logger("OSDNotifier.Config")

_SECRET_OPTIONS = {"token", "password", "client_id", "client_secret", "api_key", "secret"}

_VALID_POSITIONS = {
    "auto", "random", "center_center", "top_left", "top_right", "top_center",
    "bottom_left", "bottom_right", "bottom_center", "center_left", "center_right",
}
_VALID_ANCHORS = _VALID_POSITIONS - {"auto", "random"}


class OSDConfigManager(configset_ini.ConfigSetIni):
    """Handles auto-creating, loading, validating, and safely reading/writing
    the OSD notification INI configuration.

    All getters clamp/validate values so a corrupted or hand-edited config
    file can never crash the application; invalid values fall back to the
    documented default and a warning is logged.
    """

    DEFAULT_CONFIG: Dict[str, Dict[str, str]] = {
        "notification": {
            "position": "center_center",
            "opacity": "0.95",
            "timeout": "3000",
            "sticky": "False",
            "margin": "20",
            "auto_anchor": "bottom_right",
            "stack_gap": "30",
        },
        "appearance": {
            "font_family": "Consolas",
            "char_size": "64",
            "bg_color": "#1E1E2E",
            "text_color": "#CDD6F4",
            "border_color": "#89B4FA",
        },
        "server": {
            "enabled": "False",
            "gntp_port": "23053",
            "udp_port": "23054",
            "host": "127.0.0.1",
            "max_payload_bytes": "65535",
            "allowed_icon_dirs": "",
        },
        "window": {
            "base_width": "240",
            "base_height": "240",
            "min_width": "240",
            "max_width": "380",
            "max_height": "600",
            "text_padding": "40",
            "extra_height": "40",
            "icon_max_width": "160",
            "icon_max_height": "140",
            "soft_wrap_chars": "30",
        },
        "tray": {
            "enabled": "True",
            "icon_path": "",
            "tooltip": "OSD Notification",
            "notify_on_server_toggle": "True",
        },
    }

    def __init__(self, app_name: Optional[str] = None):
        if not app_name:
            stem = Path(sys.argv[0]).stem
            # Guard against ambiguous stems produced by `python -m ...` or a REPL.
            app_name = stem if stem and stem not in ("__main__", "-c", "") else "osd-notification"

        self.app_name = app_name
        self.config_path = self._get_config_path()

        try:
            super().__init__(str(self.config_path))
        except Exception as exc:  # pragma: no cover - defensive
            raise ConfigError(f"Failed to load config at {self.config_path}: {exc}") from exc

        self._ensure_defaults()

    # ------------------------------------------------------------------ #
    # Path / bootstrap helpers
    # ------------------------------------------------------------------ #

    def _get_config_path(self) -> Path:
        if sys.platform == "win32":
            base_dir = Path(os.path.expandvars("%USERPROFILE%")) / f".{self.app_name}"
        else:
            base_dir = Path.home() / f".{self.app_name}"

        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"Cannot create config directory {base_dir}: {exc}") from exc

        return base_dir / f"{self.app_name}.ini"

    def _ensure_defaults(self) -> None:
        """Write any missing section/option from DEFAULT_CONFIG without clobbering
        values the user has already set. `ConfigSetIni.set()`/`write_config()`
        persist to disk automatically."""
        for section, options in self.DEFAULT_CONFIG.items():
            if not self.has_section(section):
                self.add_section(section)
            for option, default_value in options.items():
                if not self.has_option(section, option):
                    try:
                        self.write_config(section, option, default_value)
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning(
                            "Could not persist default [%s] %s = %s: %s",
                            section, option, default_value, exc,
                        )

    def reset_section(self, section: str) -> None:
        """Overwrite every key in `section` back to its documented default,
        discarding stale/conflicting values left over from an older config
        schema (e.g. a `[window]` section written before `max_height`
        existed, or a leftover value smaller than the current minimum).
        Raises ConfigError for an unrecognized section name."""
        if section not in self.DEFAULT_CONFIG:
            raise ConfigError(
                f"Unknown config section '{section}'. "
                f"Valid sections: {', '.join(self.DEFAULT_CONFIG)}"
            )
        if not self.has_section(section):
            self.add_section(section)
        for option, default_value in self.DEFAULT_CONFIG[section].items():
            self.write_config(section, option, default_value)
        logger.info("Reset [%s] to defaults.", section)

    def reset_all(self) -> None:
        """Reset every known section to its documented defaults."""
        for section in self.DEFAULT_CONFIG:
            self.reset_section(section)

    # ------------------------------------------------------------------ #
    # Typed, validated getters
    # ------------------------------------------------------------------ #

    def get_val(self, section: str, option: str, default: str) -> str:
        val = self.get_config(section, option, default)
        return str(val) if val is not None and str(val).strip() != "" else default

    def get_bool(self, section: str, option: str, default: bool = False) -> bool:
        val = self.get_val(section, option, str(default)).strip().lower()
        return val in ("true", "1", "yes", "on")

    def get_int(self, section: str, option: str, default: int,
                min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
        try:
            value = int(float(self.get_val(section, option, str(default))))
        except (ValueError, TypeError):
            logger.warning("Invalid int for [%s] %s; using default %s", section, option, default)
            value = default
        if min_val is not None and value < min_val:
            value = min_val
        if max_val is not None and value > max_val:
            value = max_val
        return value

    def get_float(self, section: str, option: str, default: float,
                  min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
        try:
            value = float(self.get_val(section, option, str(default)))
        except (ValueError, TypeError):
            logger.warning("Invalid float for [%s] %s; using default %s", section, option, default)
            value = default
        if min_val is not None and value < min_val:
            value = min_val
        if max_val is not None and value > max_val:
            value = max_val
        return value

    def get_color(self, section: str, option: str, default: str) -> str:
        """Return a validated `#RRGGBB` hex color string, falling back to default."""
        val = self.get_val(section, option, default)
        if not self._is_hex_color(val):
            logger.warning("Invalid color '%s' for [%s] %s; using default %s", val, section, option, default)
            return default
        return val

    @staticmethod
    def _is_hex_color(value: str) -> bool:
        if not value.startswith("#") or len(value) not in (4, 7):
            return False
        try:
            int(value[1:], 16)
            return True
        except ValueError:
            return False

    def get_position(self, default: str = "center_center") -> str:
        val = self.get_val("notification", "position", default).strip().lower()
        return val if val in _VALID_POSITIONS else default

    def is_auto_position(self) -> bool:
        return self.get_position() == "auto"

    def is_random_position(self) -> bool:
        return self.get_position() == "random"

    def get_auto_anchor(self, default: str = "bottom_right") -> str:
        """The screen corner the cascade *starts* from when
        `position = auto` — new notifications then spread diagonally
        across the whole available screen from there (wrapping back to
        the start once they'd run off the opposite edge), the same way
        Windows cascades new windows (e.g. opening several `cmd.exe`
        windows with default placement) rather than stacking them in a
        single line."""
        val = self.get_val("notification", "auto_anchor", default).strip().lower()
        return val if val in _VALID_ANCHORS else default

    def get_cascade_step(self) -> int:
        """Diagonal pixel offset applied to each successive notification
        in `auto` mode (kept as the `stack_gap` key for config
        compatibility)."""
        return self.get_int("notification", "stack_gap", 30, min_val=0, max_val=200)

    def get_opacity(self) -> float:
        return self.get_float("notification", "opacity", 0.95, min_val=0.05, max_val=1.0)

    def get_timeout_ms(self) -> int:
        return self.get_int("notification", "timeout", 3000, min_val=0, max_val=60_000)

    def get_margin(self) -> int:
        return self.get_int("notification", "margin", 20, min_val=0, max_val=500)

    def get_allowed_icon_dirs(self) -> list[Path]:
        raw = self.get_val("server", "allowed_icon_dirs", "")
        dirs = [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]
        # Always allow the current working directory for local/manual use.
        dirs.append(Path.cwd().resolve())
        return dirs

    # ------------------------------------------------------------------ #
    # Window geometry (was hardcoded in widget.py; now config-driven)
    # ------------------------------------------------------------------ #

    def get_base_size(self) -> tuple[int, int]:
        width = self.get_int("window", "base_width", 240, min_val=80, max_val=1000)
        height = self.get_int("window", "base_height", 240, min_val=80, max_val=1000)
        return width, height

    def get_min_width(self) -> int:
        return self.get_int("window", "min_width", 240, min_val=80, max_val=1000)

    def get_max_width(self) -> int:
        max_width = self.get_int("window", "max_width", 380, min_val=80, max_val=2000)
        return max(max_width, self.get_min_width())

    def get_max_height(self) -> int:
        max_height = self.get_int("window", "max_height", 600, min_val=80, max_val=3000)
        base_height = self.get_int("window", "base_height", 240, min_val=80, max_val=1000)
        return max(max_height, base_height)

    def get_text_padding(self) -> int:
        return self.get_int("window", "text_padding", 40, min_val=0, max_val=200)

    def get_extra_height(self) -> int:
        return self.get_int("window", "extra_height", 40, min_val=0, max_val=500)

    def get_icon_max_size(self) -> tuple[int, int]:
        width = self.get_int("window", "icon_max_width", 160, min_val=16, max_val=1000)
        height = self.get_int("window", "icon_max_height", 140, min_val=16, max_val=1000)
        return width, height

    def get_soft_wrap_chars(self) -> int:
        """Max run length (in characters) of unbroken, whitespace-free text
        before a soft break point is inserted so it can still word-wrap.
        See `widget.insert_soft_breaks`."""
        return self.get_int("window", "soft_wrap_chars", 30, min_val=5, max_val=200)

    # ------------------------------------------------------------------ #
    # Redacted display (used by CLI `--show`)
    # ------------------------------------------------------------------ #

    def as_display_dict(self) -> Dict[str, Dict[str, str]]:
        """Return all sections/options with secret-looking values masked."""
        result: Dict[str, Dict[str, str]] = {}
        for section in self.sections():
            result[section] = {}
            for option in self.options(section):
                value = self.get_val(section, option, "")
                if option.lower() in _SECRET_OPTIONS and value:
                    masked = value[:4] + "*" * max(0, len(value) - 4) if len(value) > 4 else "*" * len(value)
                    result[section][option] = masked
                else:
                    result[section][option] = value
        return result
