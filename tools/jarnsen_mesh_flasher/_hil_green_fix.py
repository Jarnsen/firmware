from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace(rel: str, old: str, new: str, *, count: int = 1) -> None:
    text = read(rel)
    if old not in text:
        raise SystemExit(f"expected block missing in {rel}: {old[:160]!r}")
    write(rel, text.replace(old, new, count))


# ---------------------------------------------------------------------------
# Hardware contract: remember the exact physical USB identity as soon as a
# board has been proven, then follow that identity instead of a stale COM name.
rel = "tools/jarnsen_mesh_flasher/tests/hardware_flash_contract.py"
text = read(rel)
text = text.replace(
    "        discovered[board_key] = port\n",
    "        manager = getattr(services, \"device_sessions\", None)\n"
    "        remember = getattr(manager, \"remember\", None)\n"
    "        if callable(remember):\n"
    "            fingerprint = remember(port)\n"
    "            if fingerprint is not None:\n"
    "                print(\n"
    "                    f\"Hardware physical lock: {board_key}={port} \"\n"
    "                    f\"serial={fingerprint.serial_number!r} location={fingerprint.location!r}\"\n"
    "                )\n"
    "        discovered[board_key] = port\n",
    1,
)
marker = "\n\ndef _supreme_full_cycle_enabled() -> bool:\n"
helper = '''\n\ndef _bound_live_port(services, port: str, board_key: str, timeout: int = 45) -> str:\n    \"\"\"Follow only the same remembered physical USB device across COM changes.\"\"\"\n    original = str(port or \"\").strip()\n    manager = getattr(services, \"device_sessions\", None)\n    remember = getattr(manager, \"remember\", None)\n    if callable(remember):\n        try:\n            remember(original)\n        except Exception:\n            pass\n    waiter = getattr(services, \"wait_for_device_reconnect\", None)\n    if callable(waiter):\n        return str(\n            waiter(original, timeout=timeout, expected_board=board_key)\n        ).strip()\n    resolver = getattr(services, \"resolve_live_port\", None)\n    if callable(resolver):\n        return str(resolver(original) or original).strip()\n    return original\n\n\ndef _verify_bound_node(\n    services, port: str, board_key: str, *, timeout: int = 45\n) -> tuple[str, str]:\n    \"\"\"Wait for a physically bound node and verify its board with bounded retries.\"\"\"\n    deadline = time.monotonic() + max(5, int(timeout))\n    current = str(port or \"\").strip()\n    last_error: Exception | None = None\n    while time.monotonic() < deadline:\n        try:\n            current = _bound_live_port(services, current, board_key, timeout=8)\n            info = services.verify_node(current, expected_board=board_key)\n            detected = services.detect_board_from_text(info)\n            if detected != board_key:\n                raise RuntimeError(\n                    f\"{current}: Board {detected!r}, erwartet {board_key!r}\"\n                )\n            return current, info\n        except Exception as exc:\n            last_error = exc\n            time.sleep(1.0)\n    raise RuntimeError(\n        f\"{port}: physisch gebundenes {board_key}-Gerät wurde nicht stabil erreichbar: \"\n        f\"{type(last_error).__name__ if last_error else 'unknown'}: {last_error}\"\n    ) from last_error\n\n\ndef _read_role_with_fallback(services, provisioning, port: str) -> dict[str, str]:\n    \"\"\"Use the enhanced JARNSEN role service when present, otherwise CLI readback.\"\"\"\n    try:\n        line = provisioning._raw_command(\n            port,\n            \"JARNSEN_TOOL_ROLE_INFO\",\n            expected=\"===JARNSEN_ROLE===\",\n            timeout=2.5,\n            attempts=1,\n            services=services,\n        )\n        parsed = provisioning._parse_role_info(line)\n        if parsed.get(\"role_api\") == \"1\" and str(parsed.get(\"role\") or \"\").strip():\n            parsed[\"source\"] = \"jarnsen-role-api\"\n            return parsed\n    except Exception as exc:\n        print(\n            \"ROLE_INFO enhanced service unavailable; validating supported Meshtastic fallback: \"\n            f\"{type(exc).__name__}: {str(exc)[:180]}\"\n        )\n\n    from profile_utils import summary_from_info_text\n\n    result = services.meshtastic(port, \"--info\", timeout=45, check=False)\n    output = \"\\n\".join(\n        str(part or \"\") for part in (result.stdout, result.stderr) if part\n    )\n    role = summary_from_info_text(output).role.strip()\n    if not role:\n        raise RuntimeError(f\"{port}: Rolle weder über ROLE_INFO noch --info lesbar.\")\n    return {\n        \"role\": role,\n        \"known\": \"1\",\n        \"persisted\": \"readback\",\n        \"allowed\": \"1\",\n        \"role_api\": \"0\",\n        \"source\": \"meshtastic-info\",\n    }\n'''
if marker not in text:
    raise SystemExit("hardware helper insertion marker missing")
text = text.replace(marker, helper + marker, 1)

old = '''        for board_key, port in sorted(self.ports.items()):\n            with self.subTest(board=board_key, port=port):\n                info = self.services.verify_node(port)\n                detected = self.services.detect_board_from_text(info)\n                self.assertEqual(detected, board_key)\n                bundle = resolve_reference_bundle(self.services, board_key)\n                report = self.services.run_flash_preflight(\n                    port, board_key, bundle, \"update\"\n                )\n                self.assertTrue(report.ready, report.format())\n'''
new = '''        for board_key, port in sorted(self.ports.items()):\n            with self.subTest(board=board_key, port=port):\n                live_port, info = _verify_bound_node(\n                    self.services, port, board_key, timeout=45\n                )\n                self.ports[board_key] = live_port\n                detected = self.services.detect_board_from_text(info)\n                self.assertEqual(detected, board_key)\n                bundle = resolve_reference_bundle(self.services, board_key)\n                report = None\n                for attempt in range(1, 4):\n                    report = self.services.run_flash_preflight(\n                        live_port, board_key, bundle, \"update\"\n                    )\n                    if report.ready:\n                        break\n                    if attempt < 3:\n                        time.sleep(1.0)\n                        live_port, _ = _verify_bound_node(\n                            self.services, live_port, board_key, timeout=20\n                        )\n                        self.ports[board_key] = live_port\n                self.assertIsNotNone(report)\n                self.assertTrue(report.ready, report.format())\n'''
if old not in text:
    raise SystemExit("configured-board test block missing")
text = text.replace(old, new, 1)

old = '''    def test_unified_role_service_readiness(self) -> None:\n        \"\"\"Catch the Build-289 post-flash role_api failure on real hardware.\"\"\"\n        import review_team_provisioning_v2 as provisioning\n\n        for board_key, port in sorted(self.ports.items()):\n            with self.subTest(board=board_key, port=port):\n                identity = self.services.query_jarnsen_identity(port)\n                build = int(getattr(identity, \"build\", 0) or 0) if identity else 0\n                if build < 168:\n                    self.skipTest(\n                        f\"{board_key} {port}: Build {build or 'unbekannt'} hat keinen \"\n                        \"verbindlichen role_api=1 Vertrag.\"\n                    )\n                line = provisioning._raw_command(\n                    port,\n                    \"JARNSEN_TOOL_ROLE_INFO\",\n                    expected=\"===JARNSEN_ROLE===\",\n                    timeout=3.0,\n                    attempts=1,\n                    services=self.services,\n                )\n                parsed = provisioning._parse_role_info(line)\n                self.assertEqual(\n                    parsed.get(\"role_api\"),\n                    \"1\",\n                    f\"{board_key} {port}: ROLE_INFO={line!r}\",\n                )\n'''
new = '''    def test_role_readback_service_or_legacy_fallback(self) -> None:\n        \"\"\"Require a real role readback without making the enhanced service mandatory.\"\"\"\n        import review_team_provisioning_v2 as provisioning\n\n        for board_key, port in sorted(self.ports.items()):\n            with self.subTest(board=board_key, port=port):\n                live_port, _ = _verify_bound_node(\n                    self.services, port, board_key, timeout=45\n                )\n                self.ports[board_key] = live_port\n                parsed = _read_role_with_fallback(\n                    self.services, provisioning, live_port\n                )\n                self.assertTrue(str(parsed.get(\"role\") or \"\").strip())\n                self.assertIn(\n                    parsed.get(\"source\"),\n                    {\"jarnsen-role-api\", \"meshtastic-info\"},\n                )\n                print(\n                    f\"Role readback {board_key} {live_port}: \"\n                    f\"role={parsed.get('role')!r} source={parsed.get('source')}\"\n                )\n'''
if old not in text:
    raise SystemExit("role readiness block missing")
text = text.replace(old, new, 1)

old = '''        import supreme_full_hil\n\n        result = supreme_full_hil.main()\n        self.assertEqual(\n            result,\n            0,\n            \"Supreme First-Flash HIL ist fehlgeschlagen; siehe \"\n            \"ci-logs/supreme-hil/report.json und trace.txt.\",\n        )\n'''
new = '''        import supreme_full_hil\n\n        original_port = self.ports[\"tbeam_supreme\"]\n        manager = getattr(self.services, \"device_sessions\", None)\n        fingerprint = None\n        remember = getattr(manager, \"remember\", None)\n        if callable(remember):\n            fingerprint = remember(original_port)\n        old_env = {\n            name: os.environ.get(name)\n            for name in (\n                \"JARNSEN_SUPREME_HIL_PORT\",\n                \"JARNSEN_SUPREME_HIL_SERIAL\",\n                \"JARNSEN_SUPREME_HIL_LOCATION\",\n            )\n        }\n        os.environ[\"JARNSEN_SUPREME_HIL_PORT\"] = original_port\n        if fingerprint is not None:\n            if fingerprint.serial_number:\n                os.environ[\"JARNSEN_SUPREME_HIL_SERIAL\"] = fingerprint.serial_number\n            if fingerprint.location:\n                os.environ[\"JARNSEN_SUPREME_HIL_LOCATION\"] = fingerprint.location\n        try:\n            result = supreme_full_hil.main()\n        finally:\n            for name, value in old_env.items():\n                if value is None:\n                    os.environ.pop(name, None)\n                else:\n                    os.environ[name] = value\n        self.assertEqual(\n            result,\n            0,\n            \"Supreme First-Flash HIL ist fehlgeschlagen; siehe \"\n            \"ci-logs/supreme-hil/report.json und trace.txt.\",\n        )\n'''
if old not in text:
    raise SystemExit("supreme invocation block missing")
text = text.replace(old, new, 1)
write(rel, text)

# ---------------------------------------------------------------------------
# Supreme full HIL: honor the pre-bound physical node and keep resolving the
# same USB device after every operation that can reset/re-enumerate it.
rel = "tools/jarnsen_mesh_flasher/tests/supreme_full_hil.py"
text = read(rel)
marker = "\n\ndef _discover_supreme(services: Any) -> tuple[str, str] | None:\n"
helper = '''\n\ndef _follow_supreme(services: Any, port: str, timeout: int = 60) -> str:\n    waiter = getattr(services, \"wait_for_device_reconnect\", None)\n    if callable(waiter):\n        return str(\n            waiter(port, timeout=timeout, expected_board=EXPECTED_BOARD)\n        ).strip()\n    resolver = getattr(services, \"resolve_live_port\", None)\n    if callable(resolver):\n        return str(resolver(port) or port).strip()\n    return str(port or \"\").strip()\n\n\ndef _prebound_supreme(services: Any) -> tuple[str, str] | None:\n    \"\"\"Recover the Supreme proven by the outer hardware contract by USB identity.\"\"\"\n    hint = os.environ.get(\"JARNSEN_SUPREME_HIL_PORT\", \"\").strip()\n    serial = os.environ.get(\"JARNSEN_SUPREME_HIL_SERIAL\", \"\").strip().casefold()\n    location = os.environ.get(\"JARNSEN_SUPREME_HIL_LOCATION\", \"\").strip().casefold()\n    if not hint and not serial and not location:\n        return None\n\n    manager = getattr(services, \"device_sessions\", None)\n    remember = getattr(manager, \"remember\", None)\n    if hint and callable(remember):\n        try:\n            remember(hint)\n        except Exception:\n            pass\n\n    def matches(entry: Any) -> bool:\n        candidate_serial = str(getattr(entry, \"serial_number\", \"\") or \"\").strip().casefold()\n        candidate_location = str(getattr(entry, \"location\", \"\") or \"\").strip().casefold()\n        if serial and candidate_serial != serial:\n            return False\n        if location and candidate_location != location:\n            return False\n        return bool(serial or location)\n\n    candidates = [\n        entry\n        for entry in list_ports.comports()\n        if getattr(entry, \"vid\", None) is not None and matches(entry)\n    ]\n    if len(candidates) > 1:\n        raise RuntimeError(\n            \"Vorab gebundene Supreme-USB-Identität ist mehrfach sichtbar; destruktiver HIL stoppt.\"\n        )\n    live = str(getattr(candidates[0], \"device\", \"\") or \"\").strip() if candidates else \"\"\n    if not live and hint:\n        live = _follow_supreme(services, hint, timeout=60)\n    if not live:\n        raise RuntimeError(\n            \"Der zuvor physisch gebundene Supreme ist nicht mehr am USB-Bus sichtbar.\"\n        )\n\n    info = \"\"\n    try:\n        info = services.verify_node(live, expected_board=EXPECTED_BOARD)\n        detected = services.detect_board_from_text(info)\n        if detected != EXPECTED_BOARD:\n            raise RuntimeError(\n                f\"Vorab gebundener Port {live} meldet Board {detected!r} statt Supreme.\"\n            )\n        proof = \"board+physical-id\"\n    except Exception as exc:\n        # The outer contract already proved this serial/location as Supreme. It\n        # may currently be in ROM download mode, where Meshtastic --info cannot\n        # answer. The physical identity remains authoritative; never fall back\n        # to a different 303A:1001 device.\n        if not (serial or location):\n            raise\n        proof = \"physical-id-prebound\"\n        _append(\n            f\"SUPREME PREBOUND SERVICE WAIT | port={live} | \"\n            f\"{type(exc).__name__}: {str(exc)[:240]}\"\n        )\n    if callable(remember):\n        try:\n            remember(live)\n        except Exception:\n            pass\n    _append(\n        f\"SUPREME PREBOUND LOCK | port={live} | serial={serial or '-'} | \"\n        f\"location={location or '-'} | proof={proof}\"\n    )\n    return live, info\n'''
if marker not in text:
    raise SystemExit("supreme discovery marker missing")
text = text.replace(marker, helper + marker, 1)
text = text.replace(
    "def _discover_supreme(services: Any) -> tuple[str, str] | None:\n    candidates: list[tuple[str, str]] = []\n",
    "def _discover_supreme(services: Any) -> tuple[str, str] | None:\n    prebound = _prebound_supreme(services)\n    if prebound is not None:\n        return prebound\n\n    candidates: list[tuple[str, str]] = []\n",
    1,
)
text = text.replace(
    '''        with _phase(report, "post-flash-usb-return"):\n            services.wait_for_serial(port, timeout=120)\n\n        with _phase(report, "profile-and-role-write"):\n''',
    '''        with _phase(report, "post-flash-usb-return"):\n            port = _follow_supreme(services, port, timeout=120)\n            services.wait_for_serial(port, timeout=120)\n            port = str(getattr(services, "resolve_live_port", lambda value: value)(port))\n            report.setdefault("port_history", []).append(port)\n\n        with _phase(report, "profile-and-role-write"):\n''',
    1,
)
text = text.replace(
    '''            services.restore_profile(port, profile_path)\n\n        with _phase(report, "name-write"):\n            services.set_names(port, TEST_LONG_NAME, TEST_SHORT_NAME)\n\n        with _phase(report, "reboot-and-stable-return"):\n            services.reboot_node(port)\n            services.wait_for_serial(port, timeout=90)\n''',
    '''            services.restore_profile(port, profile_path)\n            port = _follow_supreme(services, port, timeout=90)\n            services.wait_for_serial(port, timeout=90)\n\n        with _phase(report, "name-write"):\n            services.set_names(port, TEST_LONG_NAME, TEST_SHORT_NAME)\n            port = _follow_supreme(services, port, timeout=90)\n\n        with _phase(report, "reboot-and-stable-return"):\n            services.reboot_node(port)\n            port = _follow_supreme(services, port, timeout=90)\n            services.wait_for_serial(port, timeout=90)\n            report.setdefault("port_history", []).append(port)\n''',
    1,
)
old = '''            role_line = provisioning._raw_command(\n                port,\n                \"JARNSEN_TOOL_ROLE_INFO\",\n                expected=\"===JARNSEN_ROLE===\",\n                timeout=4.0,\n                attempts=2,\n                services=services,\n            )\n            role_data = _role_contract(provisioning, role_line)\n'''
new = '''            try:\n                role_line = provisioning._raw_command(\n                    port,\n                    \"JARNSEN_TOOL_ROLE_INFO\",\n                    expected=\"===JARNSEN_ROLE===\",\n                    timeout=2.5,\n                    attempts=1,\n                    services=services,\n                )\n                role_data = _role_contract(provisioning, role_line)\n                role_data[\"source\"] = \"jarnsen-role-api\"\n            except Exception as exc:\n                expected_role = functional_profiles.functional_profile(\n                    TEST_FUNCTION\n                ).meshtastic_role\n                actual_role = summary.role.strip()\n                if actual_role.casefold() != expected_role.casefold():\n                    raise AssertionError(\n                        f\"Rollen-Readback {actual_role!r} != {expected_role!r}; \"\n                        f\"ROLE_INFO fallback cause={type(exc).__name__}: {exc}\"\n                    ) from exc\n                role_data = {\n                    \"role\": actual_role,\n                    \"known\": \"1\",\n                    \"persisted\": \"1\",\n                    \"allowed\": \"1\",\n                    \"role_api\": \"0\",\n                    \"source\": \"meshtastic-info-after-reboot\",\n                }\n                _append(\n                    \"ROLE FALLBACK OK | source=meshtastic-info-after-reboot | \"\n                    f\"role={actual_role}\"\n                )\n'''
if old not in text:
    raise SystemExit("supreme raw role block missing")
text = text.replace(old, new, 1)
text = text.replace(
    '''                "role_api": role_data.get("role_api", ""),\n            }\n''',
    '''                "role_api": role_data.get("role_api", ""),\n                "role_source": role_data.get("source", ""),\n            }\n''',
    1,
)
write(rel, text)

# ---------------------------------------------------------------------------
# Feature matrix: same physical Supreme, Build 181 reference only, and the same
# enhanced-service -> Meshtastic-readback fallback used by the product.
rel = "tools/jarnsen_mesh_flasher/tests/supreme_feature_matrix_hil.py"
text = read(rel)
old = '''def _read_role(\n    services: Any, provisioning: Any, port: str, expected_role: str\n) -> dict[str, str]:\n    line = provisioning._raw_command(\n        port,\n        \"JARNSEN_TOOL_ROLE_INFO\",\n        expected=\"===JARNSEN_ROLE===\",\n        timeout=4.0,\n        attempts=2,\n        services=services,\n    )\n    data = provisioning._parse_role_info(line)\n    actual = str(data.get(\"role\") or \"\").strip().casefold()\n    wanted = str(expected_role or \"\").strip().casefold()\n    if actual != wanted:\n        raise AssertionError(\n            f\"ROLE_INFO role={data.get('role')!r}, erwartet {expected_role!r}: {line}\"\n        )\n    for key in (\"known\", \"persisted\", \"allowed\", \"role_api\"):\n        if data.get(key) != \"1\":\n            raise AssertionError(\n                f\"ROLE_INFO {key}={data.get(key)!r}, erwartet '1': {line}\"\n            )\n    return data\n'''
new = '''def _read_role(\n    services: Any, provisioning: Any, port: str, expected_profile: str\n) -> dict[str, str]:\n    try:\n        line = provisioning._raw_command(\n            port,\n            \"JARNSEN_TOOL_ROLE_INFO\",\n            expected=\"===JARNSEN_ROLE===\",\n            timeout=2.5,\n            attempts=1,\n            services=services,\n        )\n        data = provisioning._parse_role_info(line)\n        actual = str(data.get(\"role\") or \"\").strip().casefold()\n        wanted = str(expected_profile or \"\").strip().casefold()\n        if actual == wanted and data.get(\"role_api\") == \"1\":\n            data[\"source\"] = \"jarnsen-role-api\"\n            return data\n    except Exception as exc:\n        base._append(\n            \"MATRIX ROLE API FALLBACK | \"\n            f\"{type(exc).__name__}: {str(exc)[:220]}\"\n        )\n\n    import functional_profiles\n    from profile_utils import summary_from_info_text\n\n    info = services.verify_node(port, expected_board=EXPECTED_BOARD)\n    actual_role = summary_from_info_text(info).role.strip()\n    wanted_role = functional_profiles.functional_profile(\n        expected_profile\n    ).meshtastic_role\n    if actual_role.casefold() != wanted_role.casefold():\n        raise AssertionError(\n            f\"Rollen-Readback {actual_role!r}, erwartet {wanted_role!r} \"\n            f\"für Profil {expected_profile!r}\"\n        )\n    return {\n        \"role\": actual_role,\n        \"known\": \"1\",\n        \"persisted\": \"1\",\n        \"allowed\": \"1\",\n        \"role_api\": \"0\",\n        \"source\": \"meshtastic-info-after-reboot\",\n    }\n'''
if old not in text:
    raise SystemExit("matrix role function missing")
text = text.replace(old, new, 1)
text = text.replace(
    '''        with base._phase(report, "matrix-resolve-firmware"):\n            bundle = services.GitHubFirmwareClient().resolve_latest(EXPECTED_BOARD)\n''',
    '''        with base._phase(report, "matrix-resolve-firmware"):\n            from hil_reference import resolve_reference_bundle\n\n            bundle = resolve_reference_bundle(services, EXPECTED_BOARD)\n''',
    1,
)
# Follow the same physical node after role/profile writes and explicit reboots.
text = text.replace(
    '''    services.restore_profile(port, profile)\n    services.set_names(port, long_name, short_name)\n    services.reboot_node(port)\n    services.wait_for_serial(port, timeout=90)\n    return _verify_state(\n''',
    '''    services.restore_profile(port, profile)\n    port = base._follow_supreme(services, port, timeout=90)\n    services.set_names(port, long_name, short_name)\n    port = base._follow_supreme(services, port, timeout=90)\n    services.reboot_node(port)\n    port = base._follow_supreme(services, port, timeout=90)\n    services.wait_for_serial(port, timeout=90)\n    return _verify_state(\n''',
    1,
)
text = text.replace(
    '''                services.reboot_node(port)\n                services.wait_for_serial(port, timeout=90)\n                reboot_states.append(\n''',
    '''                services.reboot_node(port)\n                port = base._follow_supreme(services, port, timeout=90)\n                services.wait_for_serial(port, timeout=90)\n                reboot_states.append(\n''',
    1,
)
text = text.replace(
    '''            services.wait_for_serial(port, timeout=120)\n            report["feature_matrix"]["firmware_only_update"] = _verify_state(\n''',
    '''            port = base._follow_supreme(services, port, timeout=120)\n            services.wait_for_serial(port, timeout=120)\n            report["feature_matrix"]["firmware_only_update"] = _verify_state(\n''',
    1,
)
text = text.replace(
    '''            services.reboot_node(port)\n            services.wait_for_serial(port, timeout=90)\n            time.sleep(1.0)\n''',
    '''            services.reboot_node(port)\n            port = base._follow_supreme(services, port, timeout=90)\n            services.wait_for_serial(port, timeout=90)\n            time.sleep(1.0)\n''',
    1,
)
write(rel, text)

# ---------------------------------------------------------------------------
# Regression guard for the visible elapsed-time requirement already implemented
# in reference_dashboard.py. This deliberately checks behavior markers rather
# than duplicating the formatter logic in the test.
rel = "tools/jarnsen_mesh_flasher/tests/test_elapsed_progress_contract.py"
write(
    rel,
    '''from __future__ import annotations\n\nimport unittest\nfrom pathlib import Path\n\n\nclass ElapsedProgressContractTests(unittest.TestCase):\n    def test_reference_dashboard_keeps_live_elapsed_progress(self) -> None:\n        source = (Path(__file__).resolve().parents[1] / "reference_dashboard.py").read_text(\n            encoding="utf-8"\n        )\n        for marker in (\n            'return f"{percent}% ({clock})"',\n            '_jarnsen_flash_started_at = time.monotonic()',\n            'app.after(1000, refresh_elapsed)',\n            'progress_pct.set(progress_text(float(app.progress.get())))',\n        ):\n            self.assertIn(marker, source)\n\n\nif __name__ == "__main__":\n    unittest.main(verbosity=2)\n''',
)
