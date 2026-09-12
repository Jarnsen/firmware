# ruff: noqa: E402
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import artifact_guard
import services as base_services
import unified_release_resolver as resolver

PROFILES = {
    "tracker": (
        "Heltec Tracker V1.1",
        "heltec-wireless-tracker",
        "JARNSEN-MESH-Heltec-Tracker-V1.1",
        "esp32",
    ),
    "repeater": ("Heltec V3", "heltec-v3", "JARNSEN-MESH-Heltec-V3", "esp32"),
    "heltec_v4": ("Heltec V4", "heltec-v4", "JARNSEN-MESH-Heltec-V4", "esp32"),
    "wio": (
        "Seeed Wio Tracker L1",
        "seeed_wio_tracker_L1",
        "JARNSEN-MESH-Seeed-Wio-Tracker-L1",
        "uf2",
    ),
    "tbeam": ("LILYGO T-Beam", "tbeam", "JARNSEN-MESH-LILYGO-T-Beam", "esp32"),
    "tbeam_supreme": (
        "LILYGO T-Beam Supreme",
        "tbeam-s3-core",
        "JARNSEN-MESH-LILYGO-T-Beam-Supreme",
        "esp32",
    ),
}


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self):
        pass


class FakeClient:
    api = "https://api.github.test"

    def __init__(self, release: dict, payloads: dict[str, bytes]):
        self.release = release
        self.payloads = payloads

    def _get_json(self, url: str, **params):
        return [self.release]

    def _request(self, method: str, url: str, **kwargs):
        return FakeResponse(self.payloads[url])


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture(
    board_key: str,
    root: Path,
    *,
    wrong_env: str | None = None,
    bad_sum: bool = False,
    missing: str | None = None,
):
    label, env, stem, kind = PROFILES[board_key]
    version = "2.0.0-alpha.26"
    prefix = f"{stem}-v{version}-Build-167"
    variants = (
        ["uf2"] if kind == "uf2" else ["update", "factory", "meshtastic-webflasher"]
    )
    manifest = {
        "schema": 1,
        "product": "JARNSEN-MESH",
        "version": f"v{version}",
        "board": label,
        "platformio_environment": wrong_env or env,
        "build": 167,
        "source_sha": "ff63f242b953dd4feaf7c3d525627feb55a25bc5",
        "variants": variants,
    }
    files: dict[str, bytes] = {
        prefix + resolver._MANIFEST_SUFFIX: json.dumps(manifest).encode(),
    }
    if kind == "uf2":
        files[prefix + "-firmware.uf2"] = b"UF2\n" + b"u" * (70 * 1024)
    else:
        files[prefix + "-update.bin"] = b"\xe9" + b"u" * (140 * 1024)
        files[prefix + "-factory.bin"] = b"\xe9" + b"f" * (270 * 1024)
        files[prefix + "-meshtastic-webflasher.bin"] = b"\xe9" + b"w" * (270 * 1024)
    sums = []
    for name, data in files.items():
        if name.endswith((".bin", ".uf2")):
            digest = (
                "0" * 64 if bad_sum and name.endswith("-update.bin") else _sha(data)
            )
            sums.append(f"{digest}  {name}")
    files[prefix + resolver._SUMS_SUFFIX] = ("\n".join(sums) + "\n").encode()
    if missing:
        files.pop(prefix + missing)

    assets = []
    payloads = {}
    for number, (name, data) in enumerate(files.items(), start=1):
        url = f"asset://{number}"
        payloads[url] = data
        assets.append(
            {
                "id": number,
                "name": name,
                "url": url,
                "state": "uploaded",
                "size": len(data),
                "digest": f"sha256:{_sha(data)}",
            }
        )
    release = {
        "id": 385607983,
        "tag_name": "v2.0.0-alpha.26",
        "name": "JARNSEN MESH v2.0.0-alpha.26 · Build 167",
        "draft": False,
        "prerelease": True,
        "html_url": "https://github.test/releases/tag/v2.0.0-alpha.26",
        "assets": assets,
    }
    profiles = {
        key: {
            "label": values[0],
            "pio_env": values[1],
            "artifact_prefix": f"{values[2]}-v2.0.0",
            "artifact_kind": values[3],
            "flash_strategy": "uf2" if values[3] == "uf2" else "factory_only",
        }
        for key, values in PROFILES.items()
    }
    services = SimpleNamespace(
        REPOSITORY="Jarnsen/firmware",
        JARNSEN_BASE_VERSION="2.0.0",
        BOARD_PROFILES=profiles,
        PATHS=SimpleNamespace(firmware=root),
        FirmwareBundle=base_services.FirmwareBundle,
        FlasherError=base_services.FlasherError,
        _sha256=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        _read_checksum_manifest=base_services._read_checksum_manifest,
        esp32_update_targets=Mock(return_value=[("app0", 0x10000, 0x300000)]),
    )
    return services, FakeClient(release, payloads), release


class UnifiedReleaseTests(unittest.TestCase):
    def test_build_167_resolves_all_six_boards_from_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            for board_key in PROFILES:
                with self.subTest(board=board_key):
                    root = Path(directory) / board_key
                    services, client, release = fixture(board_key, root)
                    bundle = resolver._release_bundle(
                        client, services, release, board_key
                    )
                    self.assertEqual(bundle.version, "2.0.0-alpha.26")
                    self.assertEqual(bundle.run_number, 167)
                    self.assertEqual(bundle.board_key, board_key)
                    self.assertEqual(
                        bundle.source_sha, "ff63f242b953dd4feaf7c3d525627feb55a25bc5"
                    )
                    self.assertEqual(bundle.source_kind, "github-release")

    def test_normal_update_never_selects_factory_or_webflasher(self):
        with tempfile.TemporaryDirectory() as directory:
            services, client, release = fixture("repeater", Path(directory))
            bundle = resolver._release_bundle(client, services, release, "repeater")
            self.assertTrue(bundle.update.name.endswith("-update.bin"))
            self.assertTrue(bundle.factory.name.endswith("-factory.bin"))
            self.assertTrue(
                bundle.webflasher.name.endswith("-meshtastic-webflasher.bin")
            )
            self.assertNotEqual(bundle.update, bundle.factory)
            self.assertNotEqual(bundle.update, bundle.webflasher)

    def test_manifest_board_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            services, client, release = fixture(
                "repeater", Path(directory), wrong_env="heltec-wireless-tracker"
            )
            with self.assertRaisesRegex(
                base_services.FlasherError, "angeschlossen ist heltec-v3"
            ):
                resolver._release_bundle(client, services, release, "repeater")

    def test_checksum_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            services, client, release = fixture(
                "repeater", Path(directory), bad_sum=True
            )
            with self.assertRaisesRegex(
                base_services.FlasherError, "SHA-256-Prüfung fehlgeschlagen"
            ):
                resolver._release_bundle(client, services, release, "repeater")

    def test_missing_declared_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            services, client, release = fixture(
                "repeater", Path(directory), missing="-meshtastic-webflasher.bin"
            )
            with self.assertRaisesRegex(
                base_services.FlasherError, "nicht eindeutig vorhanden"
            ):
                resolver._release_bundle(client, services, release, "repeater")

    def test_release_selection_is_semantic_not_publish_order(self):
        releases = [
            {"id": 4, "tag_name": "v2.0.0-alpha.28", "name": "Build 170"},
            {"id": 2, "tag_name": "v2.0.0-beta.1", "name": "Build 180"},
            {"id": 3, "tag_name": "v2.0.0-rc.1", "name": "Build 190"},
            {"id": 1, "tag_name": "v2.0.0", "name": "Build 200"},
        ]
        ordered = sorted(
            releases,
            key=lambda item: resolver._release_key(item, "2.0.0"),
            reverse=True,
        )
        self.assertEqual(
            [item["tag_name"] for item in ordered],
            ["v2.0.0", "v2.0.0-rc.1", "v2.0.0-beta.1", "v2.0.0-alpha.28"],
        )

    def test_legacy_resolver_remains_fallback(self):
        sentinel = object()

        class Client:
            api = "https://api.github.test"

            def resolve_latest(self, board_key):
                return sentinel

        services = SimpleNamespace(
            GitHubFirmwareClient=Client,
            BOARD_PROFILES={"repeater": {"label": "Heltec V3"}},
            FlasherError=base_services.FlasherError,
        )
        with patch.object(
            resolver,
            "_resolve_from_releases",
            side_effect=resolver._LegacyReleaseRequired("no manifest"),
        ):
            resolver.install(services)
            self.assertIs(Client().resolve_latest("repeater"), sentinel)

    def test_factory_image_may_start_at_classic_esp32_bootloader_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "board-factory.bin"
            image.write_bytes(b"\xff" * 0x1000 + b"\xe9" + b"x" * 32)
            services = SimpleNamespace(FlasherError=base_services.FlasherError)
            artifact_guard._validate_magic(services, "esp32", [image])

    def test_update_image_must_start_with_app_header(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "board-update.bin"
            image.write_bytes(b"\xff" * 0x1000 + b"\xe9" + b"x" * 32)
            services = SimpleNamespace(FlasherError=base_services.FlasherError)
            with self.assertRaisesRegex(
                base_services.FlasherError, "Header ist ungültig"
            ):
                artifact_guard._validate_magic(services, "esp32", [image])


if __name__ == "__main__":
    unittest.main()
