# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import functional_profiles  # noqa: E402
import profile_role_choice_fix  # noqa: E402
import write_choice_guard  # noqa: E402


class _Var:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.profiles = root / "profiles"
        self.profiles.mkdir(parents=True, exist_ok=True)

    @property
    def active_profile(self) -> Path:
        return self.profiles / ".active-profile.yaml"


class ProfileRoleChoiceFixTests(unittest.TestCase):
    def _fixture(self, root: Path):
        paths = _Paths(root)
        profile = {
            "config": {
                "device": {"role": "TAK"},
                "power": {"is_power_saving": True},
                "bluetooth": {"enabled": False},
            }
        }
        paths.active_profile.write_text(
            yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        services = SimpleNamespace(PATHS=paths, FlasherError=RuntimeError)
        app = SimpleNamespace(
            long_name_var=_Var("Hardrock OPS 26"),
            short_name_var=_Var("HOPS"),
            _selected_device=lambda: SimpleNamespace(port="COM25"),
            _set_status=lambda _text: None,
            _append_log=lambda _text: None,
        )
        current = SimpleNamespace(
            role="CLIENT",
            long_name="Hardrock OPS 26",
            short_name="HOPS",
        )
        return services, app, current

    def test_functional_profile_role_mismatch_offers_old_role_and_preserves_choice(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services, app, current = self._fixture(Path(folder))
            old_read = write_choice_guard._read_current_summary
            old_choice = write_choice_guard._two_choice
            old_active = functional_profiles.active_profile
            try:
                write_choice_guard._ROLE_OVERRIDE_BY_PORT.clear()
                write_choice_guard._read_current_summary = (
                    lambda _services, _device: current
                )
                calls: list[tuple[str, str]] = []

                def choose(_parent, **kwargs):
                    calls.append((kwargs["left_text"], kwargs["right_text"]))
                    return "left"

                write_choice_guard._two_choice = choose
                functional_profiles.active_profile = (
                    lambda _services: functional_profiles.functional_profile("tak")
                )

                result = profile_role_choice_fix._prepare_choices(
                    app, services, action_name="Profil schreiben"
                )
            finally:
                write_choice_guard._read_current_summary = old_read
                write_choice_guard._two_choice = old_choice
                functional_profiles.active_profile = old_active

            self.assertIsNotNone(result)
            self.assertEqual(result.role, "CLIENT")
            self.assertEqual(calls, [("CLIENT", "TAK")])
            self.assertEqual(
                write_choice_guard._ROLE_OVERRIDE_BY_PORT.get("COM25"), "CLIENT"
            )

    def test_functional_profile_role_mismatch_can_select_profile_role(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            services, app, current = self._fixture(Path(folder))
            old_read = write_choice_guard._read_current_summary
            old_choice = write_choice_guard._two_choice
            old_active = functional_profiles.active_profile
            try:
                write_choice_guard._ROLE_OVERRIDE_BY_PORT.clear()
                write_choice_guard._read_current_summary = (
                    lambda _services, _device: current
                )
                write_choice_guard._two_choice = lambda _parent, **_kwargs: "right"
                functional_profiles.active_profile = (
                    lambda _services: functional_profiles.functional_profile("tak")
                )

                result = profile_role_choice_fix._prepare_choices(
                    app, services, action_name="Profil schreiben"
                )
            finally:
                write_choice_guard._read_current_summary = old_read
                write_choice_guard._two_choice = old_choice
                functional_profiles.active_profile = old_active

            self.assertIsNotNone(result)
            self.assertEqual(result.role, "TAK")
            self.assertEqual(
                write_choice_guard._ROLE_OVERRIDE_BY_PORT.get("COM25"), "TAK"
            )

    def test_role_override_and_delta_are_written_outside_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            services, _app, _current = self._fixture(root)
            source = services.PATHS.active_profile

            override = profile_role_choice_fix._profile_with_role(
                services, source, "COM25", "CLIENT"
            )
            delta = profile_role_choice_fix._write_delta_profile(
                root / "restore-work",
                "COM25",
                {"config": {"device": {"role": "CLIENT"}}},
            )
            try:
                self.assertFalse(override.resolve().is_relative_to(root.resolve()))
                self.assertFalse(delta.resolve().is_relative_to(root.resolve()))
                payload = yaml.safe_load(override.read_text(encoding="utf-8"))
                self.assertEqual(payload["config"]["device"]["role"], "CLIENT")
                self.assertTrue(payload["config"]["power"]["is_power_saving"])
            finally:
                override.unlink(missing_ok=True)
                delta.unlink(missing_ok=True)

    def test_install_patches_late_bound_runtime_hooks(self) -> None:
        services = SimpleNamespace()
        old_prepare = write_choice_guard._prepare_choices
        old_profile_with_role = write_choice_guard._profile_with_role
        old_installed = profile_role_choice_fix._INSTALLED
        try:
            profile_role_choice_fix._INSTALLED = False
            profile_role_choice_fix.install(services)
            self.assertIs(
                write_choice_guard._prepare_choices,
                profile_role_choice_fix._prepare_choices,
            )
            self.assertIs(
                write_choice_guard._profile_with_role,
                profile_role_choice_fix._profile_with_role,
            )
            self.assertTrue(services._jarnsen_profile_role_choice_fix)
        finally:
            write_choice_guard._prepare_choices = old_prepare
            write_choice_guard._profile_with_role = old_profile_with_role
            profile_role_choice_fix._INSTALLED = old_installed


if __name__ == "__main__":
    unittest.main(verbosity=2)
