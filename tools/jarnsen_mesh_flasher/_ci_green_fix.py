from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


for path in (
    ".github/workflows/_temp-supreme-tracker-hil.yml",
    ".github/workflows/jarnsen-mesh-flasher-windows.yml",
):
    text = read(path)
    text = text.replace(
        "actions/checkout@v7",
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    )
    text = text.replace(
        "actions/upload-artifact@v7",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    )
    write(path, text)

hil_reference = '''from __future__ import annotations

import os
from typing import Any

DEFAULT_REFERENCE_VERSION = "2.0.0-alpha.29"
DEFAULT_REFERENCE_BUILD = 181


def _reference_version() -> str:
    return (
        os.environ.get("JARNSEN_HIL_REFERENCE_VERSION", DEFAULT_REFERENCE_VERSION)
        .strip()
        .removeprefix("v")
    )


def _reference_build() -> int:
    raw = os.environ.get("JARNSEN_HIL_REFERENCE_BUILD", str(DEFAULT_REFERENCE_BUILD)).strip()
    try:
        build = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Ungültiger HIL-Referenz-Build: {raw!r}") from exc
    if build <= 0:
        raise RuntimeError(f"Ungültiger HIL-Referenz-Build: {build}")
    return build


def resolve_reference_bundle(services: Any, board_key: str):
    """Resolve the exact firmware release approved for destructive HIL."""
    if board_key not in services.BOARD_PROFILES:
        raise services.FlasherError(f"Nicht unterstütztes HIL-Board: {board_key}")

    version = _reference_version()
    build = _reference_build()
    tag = f"v{version}"
    client = services.GitHubFirmwareClient()
    try:
        release = client._get_json(
            f"{client.api}/repos/{services.REPOSITORY}/releases/tags/{tag}"
        )
    except Exception as exc:
        raise services.FlasherError(
            f"HIL-Referenzrelease {tag} (Build {build}) konnte nicht geladen werden: {exc}"
        ) from exc
    if not isinstance(release, dict):
        raise services.FlasherError(
            f"HIL-Referenzrelease {tag} liefert keine gültigen Release-Metadaten."
        )

    import unified_release_resolver as resolver

    bundle = resolver._release_bundle(client, services, release, board_key)
    actual_version = str(getattr(bundle, "version", "") or "").strip().removeprefix("v")
    actual_build = int(getattr(bundle, "run_number", 0) or 0)
    if actual_version != version or actual_build != build:
        raise services.FlasherError(
            "HIL-Referenz stimmt nicht mit dem aufgelösten Paket überein: "
            f"erwartet={version}/Build {build}, ist={actual_version}/Build {actual_build}."
        )
    return bundle
'''
write("tools/jarnsen_mesh_flasher/hil_reference.py", hil_reference)

path = "tools/jarnsen_mesh_flasher/tests/destructive_multi_board_hil.py"
text = read(path)
if "from hil_reference import resolve_reference_bundle" not in text:
    text = text.replace(
        "    from unified_service_v2 import flash_firmware_only_bundle\n",
        "    from hil_reference import resolve_reference_bundle\n"
        "    from unified_service_v2 import flash_firmware_only_bundle\n",
        1,
    )
text = text.replace(
    "            bundle = services.GitHubFirmwareClient().resolve_latest(board_key)\n",
    "            bundle = resolve_reference_bundle(services, board_key)\n",
    1,
)
write(path, text)

path = "tools/jarnsen_mesh_flasher/tests/identified_multi_board_hil.py"
text = read(path)
if "from hil_reference import resolve_reference_bundle" not in text:
    text = text.replace(
        "    from unified_service_v2 import flash_firmware_only_bundle\n",
        "    from hil_reference import resolve_reference_bundle\n"
        "    from unified_service_v2 import flash_firmware_only_bundle\n",
        1,
    )
text = text.replace("        client = services.GitHubFirmwareClient()\n", "", 1)
text = text.replace(
    "            bundle = client.resolve_latest(board_key)\n",
    "            bundle = resolve_reference_bundle(services, board_key)\n",
    1,
)
write(path, text)

path = "tools/jarnsen_mesh_flasher/tests/hardware_flash_contract.py"
text = read(path)
marker = "if str(APP_DIR) not in sys.path:\n    sys.path.insert(0, str(APP_DIR))\n"
if "from hil_reference import resolve_reference_bundle" not in text:
    text = text.replace(
        marker,
        marker + "\nfrom hil_reference import resolve_reference_bundle  # noqa: E402\n",
        1,
    )
text = text.replace(
    "self.services.GitHubFirmwareClient().resolve_latest(board_key)",
    "resolve_reference_bundle(self.services, board_key)",
)
write(path, text)

path = "tools/jarnsen_mesh_flasher/tests/supreme_full_hil.py"
text = read(path)
if "from hil_reference import resolve_reference_bundle" not in text:
    text = text.replace(
        "        import functional_profiles\n",
        "        import functional_profiles\n"
        "        from hil_reference import resolve_reference_bundle\n",
        1,
    )
text = text.replace(
    "            bundle = services.GitHubFirmwareClient().resolve_latest(EXPECTED_BOARD)\n",
    "            bundle = resolve_reference_bundle(services, EXPECTED_BOARD)\n",
    1,
)
write(path, text)

path = ".github/workflows/_temp-supreme-tracker-hil.yml"
text = read(path)
anchor = '      PYTHONIOENCODING: "utf-8"\n'
if "JARNSEN_HIL_REFERENCE_BUILD" not in text:
    text = text.replace(
        anchor,
        anchor
        + '      JARNSEN_HIL_REFERENCE_VERSION: "2.0.0-alpha.29"\n'
        + '      JARNSEN_HIL_REFERENCE_BUILD: "181"\n',
        1,
    )
write(path, text)

path = ".github/workflows/jarnsen-mesh-flasher-windows.yml"
text = read(path)
job_anchor = "    timeout-minutes: 30\n\n    steps:\n"
if "JARNSEN_HIL_REFERENCE_BUILD" not in text:
    text = text.replace(
        job_anchor,
        "    timeout-minutes: 30\n"
        "    env:\n"
        '      JARNSEN_HIL_REFERENCE_VERSION: "2.0.0-alpha.29"\n'
        '      JARNSEN_HIL_REFERENCE_BUILD: "181"\n\n'
        "    steps:\n",
        1,
    )
write(path, text)

compat_rules = (
    "python.lang.compatibility.python36.python36-compatibility-Popen1, "
    "python.lang.compatibility.python36.python36-compatibility-Popen2"
)
for path in (
    "tools/jarnsen_mesh_flasher/flash_runtime.py",
    "tools/jarnsen_mesh_flasher/profile_export_completion_fix.py",
    "tools/jarnsen_mesh_flasher/profile_restore.py",
    "tools/jarnsen_mesh_flasher/review_team_provisioning_v2.py",
):
    lines = read(path).splitlines()
    output: list[str] = []
    for line in lines:
        if re.match(r"^\s*proc\s*=\s*subprocess\.Popen\($", line):
            indent = line[: len(line) - len(line.lstrip())]
            if not (output and "nosemgrep:" in output[-1]):
                output.append(
                    indent
                    + "# nosemgrep: "
                    + compat_rules
                    + " -- runtime enforces Python >=3.10"
                )
        output.append(line)
    write(path, "\n".join(output) + "\n")

path = "tools/jarnsen_mesh_flasher/profile_editor_choices.py"
text = read(path)
text = text.replace("import importlib\nimport pkgutil\n", "")
start = text.index("def _protobuf_modules()")
end = text.index("\ndef _enum_catalog()", start)
new_function = '''def _protobuf_modules() -> tuple[Any, ...]:
    """Load only the explicitly reviewed Meshtastic protobuf modules."""
    modules: list[Any] = []
    try:
        from meshtastic.protobuf import config_pb2

        modules.append(config_pb2)
    except Exception:
        pass
    try:
        from meshtastic.protobuf import module_config_pb2

        modules.append(module_config_pb2)
    except Exception:
        pass
    try:
        from meshtastic.protobuf import channel_pb2

        modules.append(channel_pb2)
    except Exception:
        pass
    try:
        from meshtastic.protobuf import localonly_pb2

        modules.append(localonly_pb2)
    except Exception:
        pass
    try:
        from meshtastic.protobuf import deviceonly_pb2

        modules.append(deviceonly_pb2)
    except Exception:
        pass
    try:
        from meshtastic.protobuf import mesh_pb2

        modules.append(mesh_pb2)
    except Exception:
        pass
    try:
        from meshtastic.protobuf import admin_pb2

        modules.append(admin_pb2)
    except Exception:
        pass
    try:
        from meshtastic.protobuf import telemetry_pb2

        modules.append(telemetry_pb2)
    except Exception:
        pass
    return tuple(modules)
'''
text = text[:start] + new_function + text[end:]
text = text.replace(
    "    module_names = _protobuf_modules()\n"
    "    loaded_modules = 0\n"
    "    for module_name in module_names:\n"
    "        try:\n"
    '            module = importlib.import_module(f"meshtastic.protobuf.{module_name}")\n'
    '            descriptor = getattr(module, "DESCRIPTOR", None)\n',
    "    modules = _protobuf_modules()\n"
    "    loaded_modules = 0\n"
    "    for module in modules:\n"
    "        try:\n"
    '            descriptor = getattr(module, "DESCRIPTOR", None)\n',
    1,
)
if "importlib.import_module" in text:
    raise SystemExit("dynamic protobuf import remained after hardening")
write(path, text)
