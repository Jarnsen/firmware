from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    # Choice resolution itself is GUI-independent. The Windows workflow uses
    # the real package; this stub keeps the pure regression runnable elsewhere.
    sys.modules["customtkinter"] = types.ModuleType("customtkinter")

import profile_editor_choices as choices


class ProfileEditorChoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_catalog = choices._ENUM_CACHE
        choices._ENUM_CACHE = []

    def tearDown(self) -> None:
        choices._ENUM_CACHE = self.original_catalog

    def test_core_fallbacks_are_complete(self) -> None:
        roles = choices.field_values_for_label("device.role", "ROUTER_LATE")
        self.assertIn("CLIENT_BASE", roles)
        self.assertIn("TAK_TRACKER", roles)
        self.assertIn("ROUTER_LATE", roles)

        regions = choices.field_values_for_label("lora.region", "EU_868")
        self.assertIn("US", regions)
        self.assertIn("EU_868", regions)
        self.assertIn("PH_915", regions)
        self.assertIn("EU_N_868", regions)

        self.assertEqual(
            choices.field_values_for_label("position.gps_mode", "ENABLED"),
            ["DISABLED", "ENABLED", "NOT_PRESENT"],
        )

    def test_bounded_numeric_field_becomes_dropdown(self) -> None:
        self.assertEqual(
            choices.field_values_for_label("lora.hop_limit", "3"),
            ["0", "1", "2", "3", "4", "5", "6", "7"],
        )

    def test_existing_unknown_value_is_preserved(self) -> None:
        values = choices.field_values_for_label("device.role", "LEGACY_CUSTOM_ROLE")
        self.assertEqual(values[0], "LEGACY_CUSTOM_ROLE")
        self.assertIn("CLIENT", values)

        hop_values = choices.field_values_for_label("lora.hop_limit", "12")
        self.assertEqual(hop_values[0], "12")
        self.assertIn("7", hop_values)

    def test_runtime_descriptor_wins_over_fallback(self) -> None:
        choices._ENUM_CACHE = [
            ("serialconfig", "mode", ("DEFAULT", "NMEA", "LOGTEXT")),
            ("otherconfig", "mode", ("FIRST", "SECOND")),
        ]
        self.assertEqual(
            choices.field_values_for_label("serial.mode", "NMEA"),
            ["DEFAULT", "NMEA", "LOGTEXT"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
