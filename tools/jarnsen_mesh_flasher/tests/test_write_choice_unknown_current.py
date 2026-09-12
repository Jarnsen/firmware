# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import functional_profiles
import profile_role_choice_fix as role_choice_fix
import write_choice_guard as guard
from profile_utils import ProfileSummary


class _Var:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class UnreadableCurrentRoleTests(unittest.TestCase):
    def tearDown(self) -> None:
        guard._ROLE_OVERRIDE_BY_PORT.clear()

    def _run(self, target_role: str, functional=None):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "active.yaml"
            profile.write_text(
                f"config:\n  device:\n    role: {target_role}\n",
                encoding="utf-8",
            )
            logs: list[str] = []
            app = SimpleNamespace(
                _selected_device=lambda: SimpleNamespace(port="COM25"),
                long_name_var=_Var("Test Node"),
                short_name_var=_Var("TN"),
                _set_status=lambda _text: None,
                _append_log=logs.append,
            )
            services = SimpleNamespace(PATHS=SimpleNamespace(active_profile=profile))

            with patch.object(
                guard,
                "summary_from_profile_file",
                return_value=ProfileSummary("Test Node", "TN", target_role),
            ), patch.object(
                guard,
                "_read_current_summary",
                return_value=ProfileSummary("Test Node", "TN", ""),
            ), patch.object(
                functional_profiles,
                "active_profile",
                return_value=functional,
            ), patch.object(
                guard,
                "_two_choice",
                side_effect=AssertionError(
                    "unknown current role must not open mismatch choice"
                ),
            ):
                choices = role_choice_fix._prepare_choices(
                    app,
                    services,
                    action_name="Profil schreiben",
                )
        return choices, logs

    def test_known_target_role_is_written_when_current_role_is_unreadable(self) -> None:
        choices, logs = self._run("TAK")
        self.assertIsNotNone(choices)
        self.assertEqual(choices.role, "TAK")
        self.assertEqual(guard._ROLE_OVERRIDE_BY_PORT.get("COM25"), "TAK")
        self.assertTrue(any("nicht lesbar" in line for line in logs))
        self.assertFalse(any("ABBRUCH" in line for line in logs))

    def test_functional_target_role_is_written_when_current_role_is_unreadable(
        self,
    ) -> None:
        functional = SimpleNamespace(label="TAK Tracker", meshtastic_role="TAK_TRACKER")
        choices, logs = self._run("CLIENT", functional=functional)
        self.assertIsNotNone(choices)
        self.assertEqual(choices.role, "TAK_TRACKER")
        self.assertEqual(guard._ROLE_OVERRIDE_BY_PORT.get("COM25"), "TAK_TRACKER")
        self.assertTrue(any("Profilrolle=TAK_TRACKER" in line for line in logs))
        self.assertTrue(any("nicht lesbar" in line for line in logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
