# ruff: noqa: E402
from __future__ import annotations

import copy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

try:
    import customtkinter  # noqa: F401
except ModuleNotFoundError:
    sys.modules["customtkinter"] = types.ModuleType("customtkinter")

import functional_profiles
import profile_editor_model as model
from profile_contract import ProfileContractManager


class ProfileEditorModelTests(unittest.TestCase):
    def test_german_metadata_and_secret_safe_preview(self) -> None:
        self.assertEqual(
            model.field_meta(("config", "lora", "hop_limit")).title, "Hop-Limit"
        )
        changes = model.profile_changes(
            {"config": {"network": {"wifi_psk": "alt"}, "lora": {"hop_limit": 7}}},
            {"config": {"network": {"wifi_psk": "neu"}, "lora": {"hop_limit": 20}}},
        )
        preview = model.format_change_preview(changes)
        self.assertIn("Hop-Limit: 7 → 20", preview)
        self.assertNotIn("alt", preview)
        self.assertNotIn("neu", preview)
        self.assertIn("••••••", preview)

    def test_compatibility_catches_board_and_radio_role_risks(self) -> None:
        data = {
            "config": {
                "device": {"role": "REPEATER", "rebroadcast_mode": "NONE"},
                "lora": {"region": "EU_868", "hop_limit": 20},
            }
        }
        errors, warnings = model.compatibility_notes(
            data,
            assigned_board="tracker",
            selected_board="repeater",
            board_profiles={
                "tracker": {"label": "Tracker"},
                "repeater": {"label": "Heltec V3"},
            },
            radio_settings={"selected": "jarnsen1"},
        )
        self.assertEqual(len(errors), 1)
        self.assertTrue(any("NONE" in item for item in warnings))
        self.assertTrue(any("automatisch US" in item for item in warnings))


class ProfileVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        catalog = types.ModuleType("profile_catalog")
        catalog.board_for_profile = lambda _path: None
        catalog.copy_profile_assignment = lambda *_args, **_kwargs: None
        catalog.profile_board_text = lambda _path: "nicht zugeordnet"
        catalog.register_profile = lambda *_args, **_kwargs: None
        sys.modules.setdefault("profile_catalog", catalog)

    def test_latest_archive_can_be_restored_without_losing_current(self) -> None:
        import importlib

        manager = importlib.import_module("profile_manager")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = root / "TRACKER__Test__TT.yaml"
            archive = root / "archive"
            current.write_text("value: 1\n", encoding="utf-8")
            manager.archive_existing(current, archive, stamp="20260910-100000")
            current.write_text("value: 2\n", encoding="utf-8")

            restored = manager.restore_latest_version(current, archive)
            self.assertEqual(restored.read_text(encoding="utf-8"), "value: 1\n")
            versions = manager.archived_versions(current, archive)
            self.assertTrue(
                any(
                    item.read_text(encoding="utf-8") == "value: 2\n"
                    for item in versions
                )
            )


class WrittenProfileVerificationTests(unittest.TestCase):
    def test_verification_uses_active_radio_overlay_and_normalized_keys(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / "active.yaml"
            profile.write_text(
                yaml.safe_dump(
                    {"config": {"lora": {"hop_limit": 7, "region": "EU_868"}}}
                ),
                encoding="utf-8",
            )
            actual = {"config": {"lora": {"hopLimit": 20, "region": "US"}}}

            def overlay(data, _settings):
                result = copy.deepcopy(data)
                result["config"]["lora"].update({"hop_limit": 20, "region": "US"})
                return result

            def meshtastic(_port, _command, target, **_kwargs):
                Path(target).write_text(yaml.safe_dump(actual), encoding="utf-8")

            services = SimpleNamespace(
                PATHS=SimpleNamespace(root=root, profiles=root, active_profile=profile),
                BOARD_PROFILES={},
                FlasherError=RuntimeError,
                load_radio_profile_settings=lambda: {"selected": "jarnsen1"},
                apply_radio_profile_overlay=overlay,
                meshtastic=meshtastic,
            )
            manager = ProfileContractManager(services)
            self.assertEqual(manager.verify_written("COM1", profile), [])

    def test_tracker_tak_verification_accepts_firmware_effective_values(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / "active.yaml"
            profile.write_text(
                yaml.safe_dump(
                    {
                        "config": {
                            "power": {"ls_secs": 3600, "wait_bluetooth_secs": 120},
                            "network": {"wifi_enabled": False},
                            "lora": {"region": "US", "tx_power": 0},
                        }
                    }
                ),
                encoding="utf-8",
            )
            # Build 168 reapplies the Tracker role policy after reboot. Proto3
            # export also omits false/default scalars and reports resolved TX.
            actual = {
                "config": {
                    "power": {"lsSecs": 300, "waitBluetoothSecs": 1},
                    "lora": {"region": "US", "txPower": 30},
                }
            }

            def meshtastic(_port, _command, target, **_kwargs):
                Path(target).write_text(yaml.safe_dump(actual), encoding="utf-8")

            services = SimpleNamespace(
                PATHS=SimpleNamespace(root=root, profiles=root, active_profile=profile),
                BOARD_PROFILES={},
                FlasherError=RuntimeError,
                meshtastic=meshtastic,
            )
            manager = ProfileContractManager(services)
            selected = SimpleNamespace(identifier="tak")
            with patch.object(
                functional_profiles, "active_profile", return_value=selected
            ):
                self.assertEqual(
                    manager.verify_written("COM9", profile, board_key="tracker"), []
                )

    def test_non_tracker_still_rejects_sleep_value_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / "active.yaml"
            profile.write_text(
                yaml.safe_dump({"config": {"power": {"ls_secs": 3600}}}),
                encoding="utf-8",
            )

            def meshtastic(_port, _command, target, **_kwargs):
                Path(target).write_text(
                    yaml.safe_dump({"config": {"power": {"lsSecs": 300}}}),
                    encoding="utf-8",
                )

            services = SimpleNamespace(
                PATHS=SimpleNamespace(root=root, profiles=root, active_profile=profile),
                BOARD_PROFILES={},
                FlasherError=RuntimeError,
                meshtastic=meshtastic,
            )
            manager = ProfileContractManager(services)
            with self.assertRaisesRegex(RuntimeError, "config.power.ls_secs"):
                manager.verify_written("COM1", profile, board_key="tbeam")


if __name__ == "__main__":
    unittest.main(verbosity=2)
