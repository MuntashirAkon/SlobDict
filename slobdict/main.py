#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later

import sys
from .app import SlobDictApplication

def main() -> int:
    """Main entry point."""
    app = SlobDictApplication()
    return int(app.run(sys.argv))

if __name__ == '__main__':
    sys.exit(main())
