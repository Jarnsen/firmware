"""Framework7 v3.1 entry point.

Loads the proven v3 launcher, installs the Framework7-native profile/live/map bridge,
and then delegates startup to the original launcher.
"""
from __future__ import annotations

import JARNSEN_FRAMEWORK7_SERVICE_TOOL as base
from JARNSEN_FRAMEWORK7_FEATURES import install
from JARNSEN_FRAMEWORK7_FIXES import install_fixes

base.APP_VERSION = "3.1.0"
install(base.LegacyBridge, base.ApiHandler)
install_fixes(base.LegacyBridge)

if __name__ == "__main__":
    raise SystemExit(base.main())
