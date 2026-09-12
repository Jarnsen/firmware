from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import advanced_flasher as advanced
import functional_profiles as profiles


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.profiles = root / "profiles"
        self.profiles.mkdir(parents=True, exist_ok=True)

    @property
    def active_profile(self) -> Path:
        return self.profiles / ".active-profile.yaml"


def _services(root: Path) -> SimpleNamespace:
    paths = _Paths(root)
    written: list[dict] = []

    def import_profile_file(source: Path) -> Path:
        shutil.copy2(source, paths.active_profile)
        return Path(source)

    def restore_profile(_port: str, source: Path | None = None) -> None:
        selected = Path(source or paths.active_profile)
        written.append(yaml.safe_load(selected.read_text(encoding="utf-8")) or {})

    services = SimpleNamespace(
        PATHS=paths,
        BOARD_PROFILES={
            "tracker": {"label": "Heltec Tracker V1.1"},
            "repeater": {"label": "Heltec V3"},
            "heltec_v4": {"label": "Heltec V4"},
            "tbeam": {"label": "LILYGO T-Beam"},
            "tbeam_supreme": {"label": "LILYGO T-Beam Supreme"},
            "wio": {"label": "Seeed Wio Tracker L1"},
        },
        FlasherError=RuntimeError,
        import_profile_file=import_profile_file,
        restore_profile=restore_profile,
        _written=written,
    )
    return services


class FunctionalProfileTests(unittest.TestCase):
    def test_exactly_four_canonical_profiles_and_locked_role_contract(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services = _services(Path(folder))
            profiles.ensure_profiles(services)

            self.assertEqual(
                profiles.labels(),
                ["TAK", "TAK TRACKER", "TAK REPEATER", "DRONE REPEATER"],
            )
            files = sorted(
                item.name
                for item in profiles.functional_directory(services).glob("*.yaml")
            )
            self.assertEqual(
                files,
                [
                    "DRONE-REPEATER.yaml",
                    "TAK-REPEATER.yaml",
                    "TAK-TRACKER.yaml",
                    "TAK.yaml",
                ],
            )

            tak = yaml.safe_load(
                profiles.profile_path(services, "tak").read_text(encoding="utf-8")
            )
            tak["config"]["device"]["role"] = "CLIENT"
            tak["config"]["power"]["is_power_saving"] = False
            normalised = profiles.normalise_profile_data(tak, "tak")
            self.assertEqual(normalised["config"]["device"]["role"], "TAK")
            self.assertIs(normalised["config"]["power"]["is_power_saving"], True)
            self.assertEqual(normalised["config"]["power"]["wait_bluetooth_secs"], 120)
            self.assertTrue(
                profiles.is_locked_path("tak", ("config", "device", "role"))
            )
            self.assertFalse(
                profiles.is_locked_path("tak", ("config", "lora", "hop_limit"))
            )

            tracker = yaml.safe_load(
                profiles.profile_path(services, "tak_tracker").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(tracker["config"]["device"]["role"], "TAK_TRACKER")
            self.assertEqual(tracker["config"]["power"]["wait_bluetooth_secs"], 120)

    def test_master_merge_keeps_channels_and_lora_but_not_hardware(self) -> None:
        target = profiles.normalise_profile_data(
            {"config": {"lora": {"region": "EU_868"}}}, "tak_repeater"
        )
        incoming = {
            "channels": [{"settings": {"name": "Jarnsen"}}],
            "module_config": {"telemetry": {"device_telemetry_enabled": True}},
            "config": {
                "device": {"role": "CLIENT", "button_gpio": 42},
                "power": {"is_power_saving": False},
                "position": {"fixed_position": False},
                "lora": {"region": "US", "hop_limit": 20},
                "security": {
                    "private_key": "private-node-identity",
                    "public_key": "public-node-identity",
                    "admin_key": ["shared-admin"],
                },
            },
        }
        merged = profiles.merge_compatible_settings(target, incoming, "tak_repeater")

        self.assertEqual(merged["channels"][0]["settings"]["name"], "Jarnsen")
        self.assertEqual(merged["config"]["lora"]["hop_limit"], 20)
        self.assertEqual(merged["config"]["device"]["role"], "ROUTER_LATE")
        self.assertTrue(merged["config"]["power"]["is_power_saving"])
        self.assertTrue(merged["config"]["position"]["fixed_position"])
        self.assertNotIn("button_gpio", merged["config"]["device"])
        self.assertNotIn("module_config", merged)
        self.assertEqual(merged["config"]["security"]["admin_key"], ["shared-admin"])
        self.assertNotIn("private_key", merged["config"]["security"])
        self.assertNotIn("public_key", merged["config"]["security"])

    def test_write_time_enforcement_cannot_be_bypassed_by_mutating_active_yaml(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services = _services(Path(folder))
            profiles.install(services)
            canonical = profiles.profile_path(services, "tak_tracker")
            services.import_profile_file(canonical)

            data = yaml.safe_load(
                services.PATHS.active_profile.read_text(encoding="utf-8")
            )
            data["config"]["device"]["role"] = "CLIENT"
            data["config"]["bluetooth"]["enabled"] = True
            services.PATHS.active_profile.write_text(
                yaml.safe_dump(data), encoding="utf-8"
            )
            services.restore_profile("COM7")

            sent = services._written[-1]["config"]
            self.assertEqual(sent["device"]["role"], "TAK_TRACKER")
            self.assertFalse(sent["bluetooth"]["enabled"])

    def test_unified_core_compatibility_rules_are_visible_to_flasher(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services = _services(Path(folder))
            allowed, message = profiles.compatibility_for_board(
                "drone_repeater", "tbeam_supreme", services
            )
            self.assertFalse(allowed)
            self.assertIn("nur für Heltec Wireless Tracker V1.1", message)

            allowed, message = profiles.compatibility_for_board(
                "tak_tracker", "repeater", services
            )
            self.assertTrue(allowed)
            self.assertIn("externe GNSS", message)

            allowed, message = profiles.firmware_compatibility_for_board(
                "drone_repeater", "tracker", services
            )
            self.assertFalse(allowed)
            self.assertIn("dedizierte", message)

    def test_first_flash_preflight_requires_a_deliberate_function_choice(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services = _services(Path(folder))
            services.validate_firmware_bundle = lambda _bundle, _board: {
                "files": ["factory.bin"]
            }
            services.detect_board_from_text = lambda _text: "tracker"
            profiles.install(services)
            bundle = SimpleNamespace(
                board_key="tracker", version="2.0.0-alpha.26", run_number=167
            )

            report = advanced.run_preflight(
                services,
                "COM7",
                "tracker",
                bundle,
                "provision",
                probe_device=False,
            )

            self.assertFalse(report.ready)
            self.assertIn("Funktionsprofil auswählen", report.format())


if __name__ == "__main__":
    unittest.main(verbosity=2)
