from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    text = read(rel)
    if text.count(old) != 1:
        raise SystemExit(
            f"expected exactly one match in {rel}, found {text.count(old)}: {old[:160]!r}"
        )
    write(rel, text.replace(old, new, 1))


# Keep the current physical Supreme COM identity flowing back to the outer
# feature matrix. Internal reconnect success is not enough if the next phase
# keeps using a stale port name.
rel = "tools/jarnsen_mesh_flasher/tests/supreme_feature_matrix_hil.py"
text = read(rel)
start = text.index("def _apply_profile(")
end = text.index("\n\n\nclass _HeadlessValue", start)
region = text[start:end]
region = region.replace(
    ") -> dict[str, Any]:\n",
    ") -> tuple[str, dict[str, Any]]:\n",
    1,
)
old_return = '''    return _verify_state(\n        services,\n        provisioning,\n        port,\n        expected_profile=profile_id,\n        expected_long=long_name,\n        expected_short=short_name,\n        expected_version=expected_version,\n        expected_build=expected_build,\n    )\n'''
new_return = '''    state = _verify_state(\n        services,\n        provisioning,\n        port,\n        expected_profile=profile_id,\n        expected_long=long_name,\n        expected_short=short_name,\n        expected_version=expected_version,\n        expected_build=expected_build,\n    )\n    return port, state\n'''
if region.count(old_return) != 1:
    raise SystemExit("_apply_profile return block missing")
region = region.replace(old_return, new_return, 1)
text = text[:start] + region + text[end:]
old_role_call = '''                role_results[profile_id] = _apply_profile(\n                    services,\n                    functional_profiles,\n                    provisioning,\n                    port,\n                    profile_id,\n                    long_name,\n                    short_name,\n                    expected_version=wanted_version,\n                    expected_build=wanted_build,\n                )\n'''
new_role_call = '''                port, role_results[profile_id] = _apply_profile(\n                    services,\n                    functional_profiles,\n                    provisioning,\n                    port,\n                    profile_id,\n                    long_name,\n                    short_name,\n                    expected_version=wanted_version,\n                    expected_build=wanted_build,\n                )\n'''
if text.count(old_role_call) != 1:
    raise SystemExit("role transition call block missing")
text = text.replace(old_role_call, new_role_call, 1)
old_usb_tail = '''            services.reboot_node(live_port)\n            services.wait_for_serial(live_port, timeout=90)\n'''
new_usb_tail = '''            services.reboot_node(live_port)\n            port = base._follow_supreme(services, live_port, timeout=90)\n            services.wait_for_serial(port, timeout=90)\n'''
if text.count(old_usb_tail) != 1:
    raise SystemExit("USB log reconnect tail missing")
text = text.replace(old_usb_tail, new_usb_tail, 1)
old_repair = '''            fake = _HeadlessFlasher(base._append)\n            repaired_bundle, backup, _identity = FlasherApp._perform_flash(\n                fake,\n                port,\n                EXPECTED_BOARD,\n                CANONICAL_LONG,\n                CANONICAL_SHORT,\n                flash_mode="repair",\n            )\n            report["feature_matrix"]["repair"] = {\n'''
new_repair = '''            fake = _HeadlessFlasher(base._append)\n            client_type = services.GitHubFirmwareClient\n            base_resolve_latest = client_type.resolve_latest\n\n            def resolve_hil_reference(_client, board_key: str):\n                if board_key == EXPECTED_BOARD:\n                    return bundle\n                return base_resolve_latest(_client, board_key)\n\n            client_type.resolve_latest = resolve_hil_reference\n            try:\n                repaired_bundle, backup, _identity = FlasherApp._perform_flash(\n                    fake,\n                    port,\n                    EXPECTED_BOARD,\n                    CANONICAL_LONG,\n                    CANONICAL_SHORT,\n                    flash_mode="repair",\n                )\n            finally:\n                client_type.resolve_latest = base_resolve_latest\n            port = base._follow_supreme(services, port, timeout=120)\n            services.wait_for_serial(port, timeout=120)\n            report["feature_matrix"]["repair"] = {\n'''
if text.count(old_repair) != 1:
    raise SystemExit("production repair block missing")
text = text.replace(old_repair, new_repair, 1)
write(rel, text)

# Make diagnostics truthful now that physical HIL is deliberately pinned to the
# approved release rather than whatever happens to be newest on GitHub.
replace_once(
    "tools/jarnsen_mesh_flasher/tests/supreme_full_hil.py",
    'with _phase(report, "resolve-latest-supreme-firmware"):',
    'with _phase(report, "resolve-reference-supreme-firmware"): ',
)

# Prepare an exact non-workflow copy. GitHub's Actions token cannot update an
# actual workflow file, so Trunk formats this mirror; the connected GitHub write
# will copy the verified result back to .github/workflows afterwards.
workflow = read(".github/workflows/jarnsen-mesh-flasher-windows.yml")
marker = '''          & $py tools\\jarnsen_mesh_flasher\\tests\\test_profile_write_reboot_regression.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n'''
extra = marker + '''          & $py tools\\jarnsen_mesh_flasher\\tests\\test_postflash_hardening.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n          & $py tools\\jarnsen_mesh_flasher\\tests\\test_write_choice_unknown_current.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n          & $py tools\\jarnsen_mesh_flasher\\tests\\test_elapsed_progress_contract.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n          & $py tools\\jarnsen_mesh_flasher\\tests\\test_hardware_identity_hardening.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n          & $py tools\\jarnsen_mesh_flasher\\tests\\test_destructive_hil_prebind.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n          & $py tools\\jarnsen_mesh_flasher\\tests\\test_build289_regressions.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n'''
if workflow.count(marker) != 1:
    raise SystemExit("Windows regression insertion marker missing")
workflow = workflow.replace(marker, extra, 1)
write("ci-format/jarnsen-mesh-flasher-windows.yml", workflow)
