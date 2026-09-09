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
            [str(value) for value in range(1, 21)],
        )

    def test_existing_unknown_value_is_preserved(self) -> None:
        values = choices.field_values_for_label("device.role", "LEGACY_CUSTOM_ROLE")
        self.assertEqual(values[0], "LEGACY_CUSTOM_ROLE")
        self.assertIn("CLIENT", values)

        hop_values = choices.field_values_for_label("lora.hop_limit", "20")
        self.assertEqual(hop_values[-1], "20")
        self.assertIn("7", hop_values)

    def test_suggested_values_remain_editable(self) -> None:
        frequencies = choices.field_values_for_label("lora.override_frequency", "916.500")
        self.assertEqual(frequencies[0], "916.500")
        self.assertIn("915.625", frequencies)
        self.assertIn("917.375", frequencies)
        self.assertTrue(choices.field_allows_custom_value("lora.override_frequency"))
        self.assertTrue(choices.field_allows_custom_value("lora.tx_power"))
        self.assertFalse(choices.field_allows_custom_value("lora.hop_limit"))

    def test_editor_uses_combo_for_presets_and_menu_for_fixed_values(self) -> None:
        class Variable:
            def __init__(self, value: str):
                self.value = value

            def get(self) -> str:
                return self.value

        class FakeCtk:
            @staticmethod
            def CTkFont(**kwargs):
                return kwargs

        class RealWidgets:
            @staticmethod
            def CTkComboBox(_master, **kwargs):
                return "combo", kwargs

            @staticmethod
            def CTkOptionMenu(_master, **kwargs):
                return "menu", kwargs

            @staticmethod
            def CTkEntry(_master, **kwargs):
                return "entry", kwargs

        original_ctk = choices.ctk
        choices.ctk = FakeCtk()
        try:
            combo = choices._EditorCtkProxy(
                RealWidgets(), {"field": "lora.override_frequency", "count": 0}
            ).CTkEntry(None, textvariable=Variable("916.500"))
            menu = choices._EditorCtkProxy(
                RealWidgets(), {"field": "lora.hop_limit", "count": 0}
            ).CTkEntry(None, textvariable=Variable("20"))
        finally:
            choices.ctk = original_ctk

        self.assertEqual(combo[0], "combo")
        self.assertEqual(menu[0], "menu")
        self.assertIn("915.625", combo[1]["values"])
        self.assertEqual(menu[1]["values"][-1], "20")

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
