from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import functional_profiles
import native_actions
import serial_probe
import write_choice_guard


class _Services:
    BOARD_PROFILES = {
        "tracker": {"label": "Heltec Wireless Tracker V1.1"},
        "repeater": {"label": "Heltec V3"},
        "heltec_v4": {"label": "Heltec V4"},
    }


class V3FlasherHardeningTests(unittest.TestCase):
    def test_v3_allows_only_tak_and_tak_repeater(self):
        allowed = {}
        for identifier in ("tak", "tak_tracker", "tak_repeater", "drone_repeater"):
            allowed[identifier] = functional_profiles.compatibility_for_board(
                identifier, "repeater", _Services
            )[0]
        self.assertEqual(
            allowed,
            {
                "tak": True,
                "tak_tracker": False,
                "tak_repeater": True,
                "drone_repeater": False,
            },
        )

    def test_cp210x_gets_bounded_application_start_grace(self):
        v3_bridge = SimpleNamespace(vid=0x10C4, pid=0xEA60)
        native_usb = SimpleNamespace(vid=0x303A, pid=0x1001)
        self.assertEqual(serial_probe._startup_grace_seconds(v3_bridge), 7.0)
        self.assertEqual(serial_probe._startup_grace_seconds(native_usb), 0.0)

    def test_connected_node_settings_parser(self):
        info = """
Owner: REPEATER_1 (R1)
Metadata: { "role": "ROUTER_LATE" }
Preferences: {
  "lora": {
    "region": "EU_868",
    "modemPreset": "LONG_FAST",
    "hopLimit": 7,
    "txPower": 22
  }
}
"""
        settings = native_actions._basic_settings_from_info(info)
        self.assertEqual(settings["region"], "EU_868")
        self.assertEqual(settings["modem"], "LONG_FAST")
        self.assertEqual(settings["hops"], "7")
        self.assertEqual(settings["tx"], "22")
        self.assertEqual(
            native_actions._functional_identifier_from_node(
                "tak_repeater", "ROUTER_LATE", "repeater"
            ),
            "tak_repeater",
        )

    def test_functional_role_always_arms_meshtastic_role_finalizer(self):
        write_choice_guard._ROLE_OVERRIDE_BY_PORT.clear()
        changed = write_choice_guard._remember_selected_role_override(
            "COM13", "TAK_TRACKER", "TAK", force=True
        )
        self.assertTrue(changed)
        self.assertEqual(write_choice_guard._ROLE_OVERRIDE_BY_PORT["COM13"], "TAK")

        write_choice_guard._ROLE_OVERRIDE_BY_PORT.clear()
        changed = write_choice_guard._remember_selected_role_override(
            "COM13", "TAK", "TAK", force=False
        )
        self.assertFalse(changed)
        self.assertNotIn("COM13", write_choice_guard._ROLE_OVERRIDE_BY_PORT)


if __name__ == "__main__":
    unittest.main()
