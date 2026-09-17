# ruff: noqa: E402
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import editable_profile_contract as contract  # noqa: E402
import functional_profiles as profiles  # noqa: E402
import profile_progress_ui as progress_ui  # noqa: E402
import profile_runtime_efficiency as efficiency  # noqa: E402


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.profiles = root / "profiles"
        self.profiles.mkdir(parents=True, exist_ok=True)

    @property
    def active_profile(self) -> Path:
        return self.profiles / ".active-profile.yaml"


def _services(root: Path) -> SimpleNamespace:
    return SimpleNamespace(PATHS=_Paths(root))


class EditableProfileContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._profile_functions = {
            "normalise_profile_data": profiles.normalise_profile_data,
            "is_locked_path": profiles.is_locked_path,
            "locked_field_message": profiles.locked_field_message,
            "ensure_profiles": profiles.ensure_profiles,
        }
        self._legacy_attr = getattr(
            profiles, "_jarnsen_legacy_normalise_profile_data", None
        )
        self._profile_flag = getattr(
            profiles, "_jarnsen_editable_profile_contract", None
        )
        self._merge_fast = efficiency._merge_fast_final_payload
        self._role_sync_flag = getattr(efficiency, "_jarnsen_editable_role_sync", None)

        if hasattr(profiles, "_jarnsen_editable_profile_contract"):
            delattr(profiles, "_jarnsen_editable_profile_contract")
        if hasattr(efficiency, "_jarnsen_editable_role_sync"):
            delattr(efficiency, "_jarnsen_editable_role_sync")

    def tearDown(self) -> None:
        for name, value in self._profile_functions.items():
            setattr(profiles, name, value)
        efficiency._merge_fast_final_payload = self._merge_fast

        if self._legacy_attr is None:
            if hasattr(profiles, "_jarnsen_legacy_normalise_profile_data"):
                delattr(profiles, "_jarnsen_legacy_normalise_profile_data")
        else:
            profiles._jarnsen_legacy_normalise_profile_data = self._legacy_attr

        if self._profile_flag is None:
            if hasattr(profiles, "_jarnsen_editable_profile_contract"):
                delattr(profiles, "_jarnsen_editable_profile_contract")
        else:
            profiles._jarnsen_editable_profile_contract = self._profile_flag

        if self._role_sync_flag is None:
            if hasattr(efficiency, "_jarnsen_editable_role_sync"):
                delattr(efficiency, "_jarnsen_editable_role_sync")
        else:
            efficiency._jarnsen_editable_role_sync = self._role_sync_flag

    def test_new_function_profile_uses_firmware_defaults_except_role(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services = _services(Path(folder))
            contract._install_functional_profile_policy(services)
            profiles.ensure_profiles(services)

            tak = yaml.safe_load(
                profiles.profile_path(services, "tak").read_text(encoding="utf-8")
            )

            self.assertEqual(tak["config"]["device"]["role"], "TAK")
            self.assertNotIn("power", tak["config"])
            self.assertNotIn("bluetooth", tak["config"])
            self.assertNotIn("lora", tak["config"])

            edited = {
                "config": {
                    "device": {"role": "CLIENT"},
                    "power": {"ls_secs": 777, "is_power_saving": False},
                    "bluetooth": {"enabled": True},
                    "lora": {"hop_limit": 5},
                }
            }
            normalized = profiles.normalise_profile_data(edited, "tak")

            self.assertEqual(normalized["config"]["device"]["role"], "TAK")
            self.assertEqual(normalized["config"]["power"]["ls_secs"], 777)
            self.assertFalse(normalized["config"]["power"]["is_power_saving"])
            self.assertTrue(normalized["config"]["bluetooth"]["enabled"])
            self.assertEqual(normalized["config"]["lora"]["hop_limit"], 5)
            self.assertTrue(
                profiles.is_locked_path("tak", ("config", "device", "role"))
            )
            self.assertFalse(
                profiles.is_locked_path("tak", ("config", "power", "ls_secs"))
            )

    def test_existing_user_values_survive_ensure(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services = _services(Path(folder))
            canonical = profiles.profile_path(services, "tak_tracker")
            canonical.parent.mkdir(parents=True, exist_ok=True)
            original = {
                "config": {
                    "device": {"role": "TAK_TRACKER"},
                    "power": {"ls_secs": 2222, "wait_bluetooth_secs": 17},
                    "bluetooth": {"enabled": True},
                    "position": {"gps_update_interval": 23},
                    "lora": {"hop_limit": 6},
                }
            }
            canonical.write_text(
                yaml.safe_dump(original, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            contract._install_functional_profile_policy(services)
            profiles.ensure_profiles(services)
            after = yaml.safe_load(canonical.read_text(encoding="utf-8"))

            self.assertEqual(after, original)

    def test_legacy_generated_fixed_core_is_migrated_to_role_only_seed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services = _services(Path(folder))
            canonical = profiles.profile_path(services, "tak")
            canonical.parent.mkdir(parents=True, exist_ok=True)
            legacy = self._profile_functions["normalise_profile_data"](
                {"config": {}}, "tak"
            )
            canonical.write_text(
                yaml.safe_dump(legacy, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            contract._install_functional_profile_policy(services)
            profiles.ensure_profiles(services)
            migrated = yaml.safe_load(canonical.read_text(encoding="utf-8"))

            self.assertEqual(migrated, {"config": {"device": {"role": "TAK"}}})

    def test_role_api_does_not_remove_meshtastic_device_role(self) -> None:
        contract._install_role_sync()

        safe = {"config": {"lora": {"hop_limit": 7}}}
        final = {
            "config": {
                "device": {"role": "TAK"},
                "power": {"is_power_saving": True},
            }
        }
        merged = efficiency._merge_fast_final_payload(
            copy.deepcopy(safe),
            copy.deepcopy(final),
            role_api_authoritative=True,
        )

        self.assertEqual(merged["config"]["device"]["role"], "TAK")
        self.assertTrue(merged["config"]["power"]["is_power_saving"])
        self.assertEqual(merged["config"]["lora"]["hop_limit"], 7)


class ProfileProgressContractTests(unittest.TestCase):
    def test_profile_write_progress_is_monotonic_across_all_phases(self) -> None:
        tracker = progress_ui._ProfileProgressTracker()
        events = (
            (0.00, "Grundeinstellungen", "0/24 · Verbindung aufbauen"),
            (0.03, "Grundeinstellungen", "Mit Node verbunden"),
            (0.00, "Grundeinstellungen", "Mit Node verbunden · 2s"),
            (0.50, "Grundeinstellungen", "12/24 · lora.region = EU_868"),
            (0.93, "Grundeinstellungen", "Änderungen an Node übertragen"),
            (1.00, "Grundeinstellungen", "fertig · 18.0s"),
            (
                0.91,
                "Grundeinstellungen",
                "Canned Messages außerhalb Transaktion schreiben",
            ),
            (1.00, "Grundeinstellungen", "Transaktion + Sonderwerte fertig"),
            (0.00, "Rolle/Power aktivieren", "0/2 · Verbindung aufbauen"),
            (0.03, "Rolle/Power aktivieren", "Mit Node verbunden"),
            (0.98, "Rolle/Power aktivieren", "Konfigurations-Transaktion bestätigen"),
            (1.00, "Rolle/Power aktivieren", "fertig · 4.0s"),
        )

        values = [
            tracker.map(fraction, stage, detail) for fraction, stage, detail in events
        ]

        self.assertEqual(values, sorted(values))
        self.assertGreater(values[2], 0.0)
        self.assertAlmostEqual(values[-1], 1.0)

    def test_explicit_profile_start_resets_tracker_for_next_write(self) -> None:
        tracker = progress_ui._ProfileProgressTracker()
        tracker.map(1.0, "Rolle/Power aktivieren", "fertig")

        restarted = tracker.map(
            0.0,
            "Grundeinstellungen",
            "0/12 · Verbindung aufbauen",
        )

        self.assertEqual(restarted, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
