# ruff: noqa: E402
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import functional_profile_fields as fields  # noqa: E402
import profile_editor_current_values as current_values  # noqa: E402


class CurrentNodeValueTests(unittest.TestCase):
    def test_absent_field_uses_current_node_value(self) -> None:
        spec = fields.FieldSpec(
            ("config", "lora", "modem_preset"),
            "enum",
            present=False,
            choices=("MEDIUM_FAST", "LONG_SLOW"),
        )
        data = {"config": {"lora": {"modemPreset": "MEDIUM_FAST"}}}

        shown, inherited = current_values._current_value_for_spec(spec, data)

        self.assertTrue(inherited)
        self.assertEqual(shown, "MEDIUM_FAST")

    def test_saved_profile_value_always_wins_over_node(self) -> None:
        spec = fields.FieldSpec(
            ("config", "lora", "modem_preset"),
            "enum",
            current="LONG_SLOW",
            present=True,
            choices=("MEDIUM_FAST", "LONG_SLOW"),
        )
        data = {"config": {"lora": {"modem_preset": "MEDIUM_FAST"}}}

        shown, inherited = current_values._current_value_for_spec(spec, data)

        self.assertFalse(inherited)
        self.assertIsNone(shown)

    def test_unchanged_displayed_node_value_stays_inherited_on_save(self) -> None:
        fake_editor = types.ModuleType("functional_profile_editor")
        spec = fields.FieldSpec(
            ("config", "lora", "modem_preset"),
            "enum",
            present=False,
            choices=("MEDIUM_FAST", "LONG_SLOW"),
        )
        captured: dict[str, object] = {}

        fake_editor.shown_value = fields.shown_value
        fake_editor.apply_profile_values = fields.apply_profile_values

        def original_open(root, services, source, functional, *, ctk):
            shown = fake_editor.shown_value(spec)
            captured["shown"] = shown
            captured["data"] = fake_editor.apply_profile_values(
                {},
                [spec],
                {spec.path: shown},
                functional,
            )
            return Path(source)

        fake_editor.open_functional_profile_editor = original_open
        previous = sys.modules.get("functional_profile_editor")
        sys.modules["functional_profile_editor"] = fake_editor
        try:
            current_values.install()
            with tempfile.TemporaryDirectory() as folder:
                root = SimpleNamespace(
                    _selected_device=lambda: SimpleNamespace(port="COM9"),
                    _append_log=lambda _message: None,
                )

                def meshtastic(_port, _command, target, **_kwargs):
                    Path(target).write_text(
                        yaml.safe_dump(
                            {"config": {"lora": {"modem_preset": "MEDIUM_FAST"}}}
                        ),
                        encoding="utf-8",
                    )

                services = SimpleNamespace(
                    PATHS=SimpleNamespace(root=Path(folder)),
                    meshtastic=meshtastic,
                )
                functional = SimpleNamespace(meshtastic_role="TAK")
                fake_editor.open_functional_profile_editor(
                    root,
                    services,
                    Path("TAK.yaml"),
                    functional,
                    ctk=object(),
                )
        finally:
            if previous is None:
                sys.modules.pop("functional_profile_editor", None)
            else:
                sys.modules["functional_profile_editor"] = previous

        self.assertEqual(captured["shown"], "MEDIUM_FAST")
        saved = captured["data"]
        self.assertEqual(saved["config"]["device"]["role"], "TAK")
        self.assertNotIn("lora", saved["config"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
