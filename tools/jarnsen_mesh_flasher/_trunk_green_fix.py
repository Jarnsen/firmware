from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tools" / "jarnsen_mesh_flasher"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace(rel: str, old: str, new: str, *, required: bool = True) -> None:
    text = read(rel)
    if old not in text:
        if required:
            raise SystemExit(f"expected block missing in {rel}: {old[:120]!r}")
        return
    write(rel, text.replace(old, new, 1))


# Bind retry-loop state into the monitor closure so a thread can never observe
# variables from a later retry iteration.
replace(
    "tools/jarnsen_mesh_flasher/backup_stability.py",
    "            def monitor() -> None:\n",
    "            def monitor(\n"
    "                stop=stop,\n"
    "                state=state,\n"
    "                attempt_started=attempt_started,\n"
    "                attempt_index=attempt_index,\n"
    "                baud=baud,\n"
    "            ) -> None:\n",
)

# Bind UI callback data created inside the profile-selection loop.
path = "tools/jarnsen_mesh_flasher/series_profile_guard.py"
text = read(path)
text = text.replace(
    "                lambda: messagebox.showerror(\n"
    "                    \"Falsches Profil für Board\",\n",
    "                lambda source=source, wrong_label=wrong_label: messagebox.showerror(\n"
    "                    \"Falsches Profil für Board\",\n",
    1,
)
text = text.replace(
    "                lambda: messagebox.askyesno(\n"
    "                    \"Profil noch keinem Board zugeordnet\",\n",
    "                lambda source=source: messagebox.askyesno(\n"
    "                    \"Profil noch keinem Board zugeordnet\",\n",
    1,
)
text = text.replace(
    "        _ui_call(root, lambda: _update_profile_ui(root, source))\n",
    "        _ui_call(root, lambda source=source: _update_profile_ui(root, source))\n",
    1,
)
text = text.replace(
    '            setattr(root, "_series_profile_guard_cancelled", True)\n',
    "            root._series_profile_guard_cancelled = True\n",
    1,
)
text = text.replace(
    '        setattr(root, "_series_profile_guard_cancelled", False)\n',
    "        root._series_profile_guard_cancelled = False\n",
    1,
)
write(path, text)

replace(
    "tools/jarnsen_mesh_flasher/tests/identified_multi_board_hil.py",
    "            def log(message: str) -> None:\n",
    "            def log(\n"
    "                message: str, label: str = label, original_port: str = original_port\n"
    "            ) -> None:\n",
)

# Resolve fixed OS utilities to absolute executable paths before spawning them.
path = "tools/jarnsen_mesh_flasher/dashboard_cleanup.py"
text = read(path)
if "import shutil\n" not in text:
    text = text.replace("import re\n", "import re\nimport shutil\n", 1)
text = text.replace(
    '            subprocess.Popen(["open", str(path)])\n',
    '            opener = shutil.which("open")\n'
    '            if opener:\n'
    '                subprocess.Popen([opener, str(path)])\n',
    1,
)
text = text.replace(
    '            subprocess.Popen(["xdg-open", str(path)])\n',
    '            opener = shutil.which("xdg-open")\n'
    '            if opener:\n'
    '                subprocess.Popen([opener, str(path)])\n',
    1,
)
write(path, text)

for rel in (
    "tools/jarnsen_mesh_flasher/native_dashboard_base.py",
    "tools/jarnsen_mesh_flasher/reference_dashboard.py",
):
    text = read(rel)
    if "import shutil\n" not in text:
        text = text.replace("import os\n", "import os\nimport shutil\n", 1)
    text = text.replace(
        '                subprocess.Popen(["xdg-open", str(folder)])\n',
        '                opener = shutil.which("xdg-open")\n'
        '                if opener:\n'
        '                    subprocess.Popen([opener, str(folder)])\n',
        1,
    )
    write(rel, text)

path = "tools/jarnsen_mesh_flasher/profile_manager.py"
text = read(path)
text = text.replace(
    '            subprocess.Popen(["open", str(folder)])\n',
    '            opener = shutil.which("open")\n'
    '            if opener:\n'
    '                subprocess.Popen([opener, str(folder)])\n',
    1,
)
text = text.replace(
    '            subprocess.Popen(["xdg-open", str(folder)])\n',
    '            opener = shutil.which("xdg-open")\n'
    '            if opener:\n'
    '                subprocess.Popen([opener, str(folder)])\n',
    1,
)
write(path, text)

path = "tools/jarnsen_mesh_flasher/services.py"
text = read(path)
text = text.replace(
    '            if shutil.which("gh"):\n'
    '                proc = subprocess.run(\n'
    '                    ["gh", "auth", "token"],\n',
    '            gh_executable = shutil.which("gh")\n'
    '            if gh_executable:\n'
    '                proc = subprocess.run(\n'
    '                    [gh_executable, "auth", "token"],\n',
    1,
)
write(path, text)

path = "tools/jarnsen_mesh_flasher/tests/exe_gui_regression.py"
text = read(path)
if "import shutil\n" not in text:
    text = text.replace("import os\n", "import os\nimport shutil\n", 1)
text = text.replace(
    '                subprocess.run(\n'
    '                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],\n',
    '                taskkill = shutil.which("taskkill")\n'
    '                if not taskkill:\n'
    '                    raise RuntimeError("taskkill executable not found")\n'
    '                subprocess.run(\n'
    '                    [taskkill, "/PID", str(process.pid), "/T", "/F"],\n',
    1,
)
write(path, text)

# Make intentional test bootstrap imports explicit to Flake8 as well as Ruff.
for test_path in sorted((APP / "tests").glob("test_*.py")):
    lines = test_path.read_text(encoding="utf-8").splitlines()
    saw_path_bootstrap = False
    changed = False
    for index, line in enumerate(lines):
        if "sys.path.insert" in line:
            saw_path_bootstrap = True
            continue
        if not saw_path_bootstrap:
            continue
        if not (line.startswith("import ") or line.startswith("from ")):
            continue
        if "# noqa:" in line:
            if "E402" not in line:
                lines[index] = line + ", E402"
                changed = True
        else:
            lines[index] = line + "  # noqa: E402"
            changed = True
    if changed:
        test_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

# D401: use imperative first lines without suppressing docstring validation.
doc_replacements = {
    "tools/jarnsen_mesh_flasher/device_core.py": {
        "Optional high-level guard only.": "Guard the optional high-level operation only.",
    },
    "tools/jarnsen_mesh_flasher/profile_dropdowns.py": {
        "The editor creates the field label immediately before its input widget.":
            "Handle the field label created immediately before its input widget.",
    },
    "tools/jarnsen_mesh_flasher/profile_manager.py": {
        "Normal profile name:": "Build a normal profile name:",
        "Replacement for the old master button so the visible path is the named profile, never .active-profile.":
            "Replace the old master button so the visible path is the named profile, never .active-profile.",
    },
    "tools/jarnsen_mesh_flasher/review_team_provisioning_guard.py": {
        "Final correctness and boot-readiness guard for Provisioning V2.":
            "Enforce final correctness and boot readiness for Provisioning V2.",
    },
    "tools/jarnsen_mesh_flasher/ui_1080_fit.py": {
        "Final 1920x1080 fit pass for the approved reference dashboard.":
            "Apply the final 1920x1080 fit pass for the approved reference dashboard.",
    },
    "tools/jarnsen_mesh_flasher/ui_action_polish.py": {
        "Final dashboard pass: uniform actions, readable spacing and strong firmware state.":
            "Apply the final dashboard pass with uniform actions, readable spacing and strong firmware state.",
    },
    "tools/jarnsen_mesh_flasher/ui_overlap_guard.py": {
        "Final geometry guard after all injected dashboard controls exist.":
            "Guard final geometry after all injected dashboard controls exist.",
    },
}
for rel, replacements in doc_replacements.items():
    text = read(rel)
    for old, new in replacements.items():
        text = text.replace(old, new)
    write(rel, text)
