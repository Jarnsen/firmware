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

    def test_missing_scalar_uses_effective_proto_default_after_node_read(self) -> None:
        spec = fields.FieldSpec(
            ("config", "lora", "ignore_mqtt"),
            "bool",
            present=False,
        )
        data = {"config": {"lora": {}}}

        shown, inherited = current_values._current_value_for_spec(spec, data)

        self.assertTrue(inherited)
        self.assertEqual(shown, "Aus")

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

    def test_fixed_choice_combobox_becomes_full_option_menu(self) -> None:
        class FakeCtk:
            @staticmethod
            def CTkComboBox(_master, *args, **kwargs):
                return "combo", args, kwargs

            @staticmethod
            def CTkOptionMenu(_master, *args, **kwargs):
                return "option", args, kwargs

        proxy = current_values._FunctionalCtkProxy(FakeCtk())
        values = [
            fields.KEEP_VALUE,
            "LONG_FAST",
            "LONG_SLOW",
            "VERY_LONG_SLOW",
            "MEDIUM_SLOW",
            "MEDIUM_FAST",
            "SHORT_SLOW",
            "SHORT_FAST",
            "LONG_MODERATE",
            "SHORT_TURBO",
            "LONG_TURBO",
        ]

        kind, _args, kwargs = proxy.CTkComboBox(object(), values=values)

        self.assertEqual(kind, "option")
        self.assertNotIn(fields.KEEP_VALUE, kwargs["values"])
        self.assertIn("MEDIUM_FAST", kwargs["values"])

    def test_feedback_closes_only_after_editor_toplevel_reaches_idle(self) -> None:
        events: list[str] = []

        class FakeWindow:
            def __init__(self):
                self.idle_callback = None

            def after_idle(self, callback):
                self.idle_callback = callback

        window = FakeWindow()

        class FakeCtk:
            @staticmethod
            def CTkToplevel(_master, *args, **kwargs):
                return window

        proxy = current_values._FunctionalCtkProxy(
            FakeCtk(),
            on_toplevel_open=lambda: events.append("closed"),
        )

        returned = proxy.CTkToplevel(object())

        self.assertIs(returned, window)
        self.assertEqual(events, [])
        self.assertIsNotNone(window.idle_callback)
        window.idle_callback()
        self.assertEqual(events, ["closed"])

        proxy.CTkToplevel(object())
        self.assertEqual(events, ["closed"])

    def test_centered_feedback_uses_main_window_geometry(self) -> None:
        class FakeRoot:
            @staticmethod
            def update_idletasks():
                return None

            @staticmethod
            def winfo_width():
                return 1200

            @staticmethod
            def winfo_height():
                return 800

            @staticmethod
            def winfo_rootx():
                return 100

            @staticmethod
            def winfo_rooty():
                return 50

        class FakeDialog:
            def __init__(self):
                self.value = None

            @staticmethod
            def update_idletasks():
                return None

            def geometry(self, value):
                self.value = value

        dialog = FakeDialog()
        current_values._center_over_root(dialog, FakeRoot(), 520, 175)

        self.assertEqual(dialog.value, "520x175+440+362")

    def test_free_form_suggestion_remains_editable_combo(self) -> None:
        class FakeCtk:
            @staticmethod
            def CTkComboBox(_master, *args, **kwargs):
                return "combo", args, kwargs

            @staticmethod
            def CTkOptionMenu(_master, *args, **kwargs):
                return "option", args, kwargs

        proxy = current_values._FunctionalCtkProxy(FakeCtk())
        kind, _args, kwargs = proxy.CTkComboBox(
            object(),
            values=[fields.KEEP_VALUE, "0.0", "915.625", "917.375"],
        )

        self.assertEqual(kind, "combo")
        self.assertNotIn(fields.KEEP_VALUE, kwargs["values"])

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

    def test_profile_specials_wires_current_node_editor_layer(self) -> None:
        source = (APP_DIR / "profile_specials_fix.py").read_text(encoding="utf-8")
        self.assertIn("install_profile_editor_current_values()", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
