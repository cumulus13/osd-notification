#!/usr/bin/env python3

# File: src/osd_notification/__main__.py
# Author: Hadi Cahyadi <cumulus13@gmail.com>
# Date: 2026-09-11
# Description: Enables `python -m osd_notification ...`.
# License: MIT


import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
