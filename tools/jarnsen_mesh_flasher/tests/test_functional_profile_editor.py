# ruff: noqa: E402
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import functional_profile_fields as fields  # noqa: E402
from functional_profile_fields_runtime import install as install_field_catalog  # noqa: E402

install_field_catalog()

FUNCTIONAL = SimpleNamespace(label="TAK", meshtastic_role="TAK")


class FunctionalProfileEditorTests(unittest.TestCase):
    def test_role_only_profile_exposes_real_meshtastic_settings(self) -> None:
        data = {"config": {"device": {"role": "TAK"}}}
        specs = fields.build_field_specs(data, FUNCTIONAL)
        labels = {item.label: item for item in specs}

        self.assertGreater(len(specs), 20)
        self.assertIn("lora.region", labels)
        self.assertIn("power.is_power_saving", labels)
        self.assertIn("bluetooth.enabled", labels)
        self.assertIn("position.gps_mode", labels)
        self.assertIn("EU_868", labels["lora.region"].choices)
        self.assertEqual(labels["power.is_power_saving"].kind, "bool")
        self.assertFalse(labels["lora.region"].present)
        self.assertTrue(labels["device.role"].locked)

    def test_missing_settings_stay_absent_until_user_changes_them(self) -> None:
        data = {"config": {"device": {"role": "TAK"}}}
        specs = fields.build_field_specs(data, FUNCTIONAL)
        raw = {item.path: fields.shown_value(item) for item in specs}
        region = next(item for item in specs if item.label == "lora.region")
        raw[region.path] = "EU_868"

        result = fields.apply_profile_values(copy.deepcopy(data), specs, raw, FUNCTIONAL)

        self.assertEqual(result["config"]["device"]["role"], "TAK")
        self.assertEqual(result["config"]["lora"]["region"], "EU_868")
        self.assertNotIn("power", result["config"])
        self.assertNotIn("bluetooth", result["config"])

    def test_keep_value_removes_an_existing_override_but_never_role(self) -> None:
        data = {
            "config": {
                "device": {"role": "CLIENT"},
                "lora": {"region": "EU_868", "hop_limit": 5},
            }
        }
        specs = fields.build_field_specs(data, FUNCTIONAL)
        raw = {item.path: fields.shown_value(item) for item in specs}
        region = next(item for item in specs if item.label == "lora.region")
        raw[region.path] = fields.KEEP_VALUE

        result = fields.apply_profile_values(copy.deepcopy(data), specs, raw, FUNCTIONAL)

        self.assertEqual(result["config"]["device"]["role"], "TAK")
        self.assertNotIn("region", result["config"]["lora"])
        self.assertEqual(result["config"]["lora"]["hop_limit"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
