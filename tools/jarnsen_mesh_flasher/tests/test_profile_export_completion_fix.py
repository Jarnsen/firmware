# ruff: noqa: E402
from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import profile_export_completion_fix as export_fix


class ProfileExportCompletionFixTests(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(export_fix)

    @staticmethod
    def _services(script: str):
        delegated: list[tuple[str, list[str], int, bool]] = []

        def base_run_helper(tool, args, *, timeout=60, check=True):
            delegated.append(
                (str(tool), [str(x) for x in args], int(timeout), bool(check))
            )
            return "delegated"

        services = SimpleNamespace(
            run_helper=base_run_helper,
            helper_command=lambda: [sys.executable, "-u", "-c", script],
            _startupinfo=lambda: None,
            FlasherError=RuntimeError,
        )
        export_fix.install(services)
        return services, delegated

    def test_valid_export_artifact_finishes_even_when_cli_stays_alive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "current.yaml"
            script = (
                "import sys,time,pathlib;"
                "i=sys.argv.index('--export-config');"
                "p=pathlib.Path(sys.argv[i+1]);"
                "p.parent.mkdir(parents=True,exist_ok=True);"
                "p.write_text('config:\\n  device:\\n    role: CLIENT\\n',encoding='utf-8');"
                "print('Exported configuration to '+str(p),flush=True);"
                "time.sleep(8)"
            )
            services, delegated = self._services(script)
            started = time.monotonic()
            result = services.run_helper(
                "meshtastic",
                ["--port", "COM25", "--export-config", str(target)],
                timeout=5,
                check=False,
            )
            elapsed = time.monotonic() - started

            self.assertEqual(result.returncode, 0)
            self.assertTrue(target.exists())
            self.assertLess(elapsed, 3.0)
            self.assertEqual(delegated, [])

    def test_stale_export_file_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "current.yaml"
            target.write_text("config:\n  stale: true\n", encoding="utf-8")
            services, _delegated = self._services("import time; time.sleep(3)")

            with self.assertRaises(subprocess.TimeoutExpired):
                services.run_helper(
                    "meshtastic",
                    ["--port", "COM25", "--export-config", str(target)],
                    timeout=1,
                    check=False,
                )
            self.assertFalse(target.exists())

    def test_non_export_commands_keep_existing_runtime_stack(self) -> None:
        services, delegated = self._services("pass")
        result = services.run_helper("esptool", ["--help"], timeout=7, check=False)
        self.assertEqual(result, "delegated")
        self.assertEqual(delegated, [("esptool", ["--help"], 7, False)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
