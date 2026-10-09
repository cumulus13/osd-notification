#!/usr/bin/env python3

# File: debugger.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-28
# Description: 
# License: MIT

import os
import sys

APP_NAME = "OSD_NOTIFICATION"
LOG_LEVEL = os.getenv(f"{APP_NAME}_LOG_LEVEL", "INFO")

def is_debug():
    return str(os.getenv(f'{APP_NAME}_DEBUG', '0')).lower() in ('1', 'true', 'ok', 'yes', 'on')

try:
    from richcolorlog import setup_logging  # type: ignore
    logger = setup_logging(
        APP_NAME,
        level=LOG_LEVEL
    )

except:
    import logging

    EMERGENCY = 60
    ALERT = 55
    NOTICE = 25

    logging.addLevelName(EMERGENCY, "EMERGENCY")
    logging.addLevelName(ALERT, "ALERT")
    logging.addLevelName(NOTICE, "NOTICE")


    def emergency(self, msg, *args, **kwargs):
        if self.isEnabledFor(EMERGENCY):
            self._log(EMERGENCY, msg, args, **kwargs)


    def alert(self, msg, *args, **kwargs):
        if self.isEnabledFor(ALERT):
            self._log(ALERT, msg, args, **kwargs)


    def notice(self, msg, *args, **kwargs):
        if self.isEnabledFor(NOTICE):
            self._log(NOTICE, msg, args, **kwargs)


    logging.Logger.emergency = emergency  # type: ignore
    logging.Logger.alert = alert  # type: ignore
    logging.Logger.notice = notice  # type: ignore

    # Setup Production Logging
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format='%(asctime)s - [%(levelname)s] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger(APP_NAME)

if is_debug():
    print(f"{APP_NAME}_DEBUG is active !")
    from pydebugger.debug import debug as debugx

    def debug(*args, **kwargs):
        if str(os.getenv('DEBUG_SERVER', '0')).lower() in (
            '1', 'true', 'ok', 'yes', 'on'
        ):
            kwargs.pop('debug', None)
        else:
            kwargs.update({'debug': '1'})
        return debugx(*args, **kwargs)

    class DebugLogger:
        def debug(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def info(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def warning(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def warn(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def error(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def exception(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def critical(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def log(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def emergency(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def alert(self, *args, **kwargs):
            return debug(*args, **kwargs)

        def notice(self, *args, **kwargs):
            return debug(*args, **kwargs)

    logger = DebugLogger()
else:
    # ============================================================
    # NORMAL MODE
    # ============================================================

    def debug(*args, **kwargs):
        """
        Normal-mode replacement for pydebugger.debug().

        Everything goes through the normal logger.
        """

        # pydebugger.debug() uses keyword arguments such as:
        #
        #     debug(TEST="TEST", debug=1)
        #
        # In normal logging, `debug=1` is not a logging argument,
        # so remove it.

        kwargs.pop("debug", None)

        # If there are keyword arguments, logging needs a message.
        if kwargs:
            if args:
                message = " ".join(str(x) for x in args)
                message += " " + " ".join(
                    f"{key}: {value}"
                    for key, value in kwargs.items()
                )
            else:
                message = " ".join(
                    f"{key}: {value}"
                    for key, value in kwargs.items()
                )

            return logger.debug(message)

        return logger.debug(*args)