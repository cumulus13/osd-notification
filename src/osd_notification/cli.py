#!/usr/bin/env python3

# File: src/osd_notification/cli.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Command-line entry point for osd-notification. Provides
#              config inspection/editing, local demo/test mode, server mode,
#              and a `send` subcommand for firing a one-off notification at
#              a running server without importing the library.
# License: MIT


from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .client import NotificationClient
from .config import OSDConfigManager
from .exceptions import ClientError, ConfigError, OSDNotificationError, ServerError
from .logging_setup import get_logger

logger = get_logger("OSDNotifier.CLI")

try:
    from rich import print as _print  # type: ignore
except ImportError:
    _print = print

try:
    from rchf import CustomRichHelpFormatter as _HelpFormatter  # type: ignore
except Exception:
    _HelpFormatter = argparse.RawTextHelpFormatter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="osd-notification", formatter_class=_HelpFormatter)
    parser.add_argument("-c", "--config", nargs="*", default=None,
                         help="\u2139\ufe0f Show config path, or get/set a section/key/value")
    parser.add_argument("-s", "--show", action="store_true", help="\U0001f440 Show all current config")
    parser.add_argument("-t", "--test", action="store_true",
                         help="\U0001f9ea Show a local notification with no server involved. "
                              "Combine with --title/--text/--icon/--sticky to preview "
                              "specific content (e.g. to check text-wrapping).")
    parser.add_argument("--server", action="store_true", help="\U0001f310 Start GNTP & UDP notification servers")
    parser.add_argument("--tray", action="store_true", help="\U0001f5a5\ufe0f Show a system tray icon with quick actions")
    parser.add_argument("--reset-config", metavar="SECTION", nargs="?", const="all",
                         help="\U0001f504 Reset a config section (e.g. 'window') to its defaults, "
                              "discarding stale values. Omit SECTION to reset everything.")

    send_group = parser.add_argument_group("send (fire a notification at a running server)")
    send_group.add_argument("--send", action="store_true", help="\U0001f4e4 Send a notification via the client")
    send_group.add_argument("--title", default="Notification", help="Notification title (with --send)")
    send_group.add_argument("--text", default="", help="Notification body text (with --send)")
    send_group.add_argument("--icon", default=None, help="Path to an icon image (with --send)")
    send_group.add_argument("--sticky", action="store_true", help="Keep the notification visible until clicked")
    send_group.add_argument("--timeout-ms", type=int, default=None, help="Auto-dismiss timeout in milliseconds")
    send_group.add_argument("--transport", choices=("udp", "gntp"), default="udp",
                             help="Delivery transport for --send (default: udp)")
    send_group.add_argument("--dismiss-all", action="store_true",
                             help="\U0001f6d1 Tell the running server to immediately close "
                                  "every currently visible notification")

    return parser


def _handle_config_flag(cm: OSDConfigManager, args: argparse.Namespace) -> int:
    if not args.config:
        _print(f"\U0001f4c4 [bold #FFFF00]CONFIG FILE:[/] [bold #00FFFF]{cm.config_path}[/]")
        if args.show:
            for section, options in cm.as_display_dict().items():
                _print(f"[bold #FFFF00]\\[{section}][/]")
                for option, value in options.items():
                    _print(f"  [bold #00FFFF]{option}[/] = [bold #AAAAFF]{value}[/]")
        return 0

    if len(args.config) >= 3:
        section, key, *rest = args.config
        value = rest[0] if rest else ""
        try:
            if not cm.has_section(section):
                cm.add_section(section)
            cm.write_config(section, key, value)
        except Exception as exc:
            raise ConfigError(f"Failed to set [{section}] {key} = {value}: {exc}") from exc
        _print(f"\u2705 [bold #00FFFF]Set[/] [bold #FFFF00]\\[{section}] {key} = {value}[/]")
        return 0

    if len(args.config) == 2:
        section, key = args.config
        _print(f"[bold #AAAAFF]\\[{section}][/]")
        _print(f"   [bold #FFAA00]{key}[/] = [bold #00FF00]{cm.get_val(section, key, '')}[/]")
        return 0

    if len(args.config) == 1:
        section = args.config[0]
        if section in cm.sections():
            _print(f"[bold #AAAAFF]\\[{section}][/]")
            for key in cm.options(section):
                _print(f"   [bold #FFAA00]{key}[/] = [bold #00FF00]{cm.get_val(section, key, '')}[/]")
        else:
            _print(f"\u274c [white on red]No section named[/] [white on blue]'{section}'[/]")
            return 1
        return 0

    return 0


def _handle_reset_config(cm: OSDConfigManager, section: str) -> int:
    try:
        if section == "all":
            cm.reset_all()
            _print(f"\u2705 [bold #00FF00]Reset all sections to defaults[/] in {cm.config_path}")
        else:
            cm.reset_section(section)
            _print(f"\u2705 [bold #00FF00]Reset[/] [bold #FFFF00]\\[{section}][/] "
                   f"[bold #00FF00]to defaults[/] in {cm.config_path}")
    except ConfigError as exc:
        _print(f"\u274c [white on red]{exc}[/]")
        return 1
    return 0


def _handle_send(cm: OSDConfigManager, args: argparse.Namespace) -> int:
    client = NotificationClient(
        host=cm.get_val("server", "host", "127.0.0.1"),
        gntp_port=cm.get_int("server", "gntp_port", 23063),
        udp_port=cm.get_int("server", "udp_port", 23064),
    )
    try:
        client.send(title=args.title, text=args.text, icon=args.icon,
                     sticky=args.sticky, timeout=args.timeout_ms, transport=args.transport)
    except ClientError as exc:
        _print(f"\u274c [white on red]Failed to send notification:[/] {exc}")
        return 1
    _print(f"\u2705 [bold #00FF00]Notification sent via {args.transport}.[/]")
    return 0


def _handle_dismiss_all(cm: OSDConfigManager) -> int:
    client = NotificationClient(
        host=cm.get_val("server", "host", "127.0.0.1"),
        udp_port=cm.get_int("server", "udp_port", 23064),
    )
    try:
        client.dismiss_all()
    except ClientError as exc:
        _print(f"\u274c [white on red]Failed to dismiss notifications:[/] {exc}")
        return 1
    _print("\u2705 [bold #00FF00]Dismissed all notifications.[/]")
    return 0
    return 0


def _handle_server_or_test(cm: OSDConfigManager, args: argparse.Namespace) -> int:
    # Imported lazily: requires PyQt5, which is unnecessary for config/send-only usage.
    from .app import OSDApplication
    from .protocol import NotificationPayload

    app = OSDApplication(cm)
    try:
        if args.server or cm.get_bool("server", "enabled", False):
            app.start_servers()
        if args.tray:
            app.start_tray()
        if args.test:
            if args.text or args.title != "Notification" or args.icon or args.sticky:
                # A specific title/text/icon was given: preview it locally,
                # no network/server involved — the same code path a real
                # GNTP/UDP notification takes, so this isolates whether an
                # issue is in the widget itself vs. a stale server process.
                payload = NotificationPayload(title=args.title, text=args.text, icon=args.icon,
                                               sticky=args.sticky, timeout=args.timeout_ms)
                app.run_demo(payload)
            else:
                app.run_demo()
        quit_after_demo = args.test and not args.server and not args.tray
        return app.run(quit_after_demo=quit_after_demo)
    except ServerError as exc:
        _print(f"\u274c [white on red]Server error:[/] {exc}")
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()

    if not argv:
        parser.print_help()
        return 0

    args = parser.parse_args(argv)

    try:
        cm = OSDConfigManager()
    except ConfigError as exc:
        _print(f"\u274c [white on red]Configuration error:[/] {exc}")
        return 1

    try:
        if args.reset_config is not None:
            return _handle_reset_config(cm, args.reset_config)

        if args.config is not None or args.show or ("-c" in argv or "--config" in argv):
            return _handle_config_flag(cm, args)

        if args.send:
            return _handle_send(cm, args)

        if args.dismiss_all:
            return _handle_dismiss_all(cm)

        if args.test or args.server or args.tray or cm.get_bool("server", "enabled", False):
            return _handle_server_or_test(cm, args)

        parser.print_help()
        return 0
    except OSDNotificationError as exc:
        _print(f"\u274c [white on red]Error:[/] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
