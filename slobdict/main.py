#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
from .app import SlobDictApplication


def handle_uncaught_exceptions(exc_type, exc_value, exc_traceback):
    logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


def main() -> int:
    """Main entry point."""
    sys.excepthook = handle_uncaught_exceptions
    app = SlobDictApplication()
    return int(app.run(sys.argv))

if __name__ == '__main__':
    sys.exit(main())
