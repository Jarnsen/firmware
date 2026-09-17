from __future__ import annotations

import unittest
from pathlib import Path


class ElapsedProgressContractTests(unittest.TestCase):
    def test_reference_dashboard_keeps_live_elapsed_progress(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "reference_dashboard.py"
        ).read_text(encoding="utf-8")
        for marker in (
            'return f"{percent}% ({clock})"',
            "_jarnsen_flash_started_at = time.monotonic()",
            "app.after(1000, refresh_elapsed)",
            "progress_pct.set(progress_text(float(app.progress.get())))",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
