from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import requests
from serial.tools import list_ports


REPOSITORY = "Jarnsen/firmware"

BOARD_PROFILES = {
    "tracker": {
        "label": "Heltec Wireless Tracker V1.1",
        "pio_env": "heltec-wireless-tracker",
        "branch": "heltec-tracker-v11-vehicle-motion-wake",
        "match": (
            "HELTEC_WIRELESS_TRACKER",
            "HELTEC WIRELESS TRACKER",
            "WIRELESS_TRACKER",
            "heltec-wireless-tracker",
        ),
    },
    "repeater": {
        "label": "Heltec V3",
        "pio_env": "heltec-v3",
        "branch": "heltec-v3-repeater-light-sleep",
        "match": ("HELTEC_V3", "HELTEC V3", "heltec-v3"),
    },
}


class FlasherError(RuntimeError):
    pass


@dataclass
class DeviceInfo:
    port: str
    description: str
    board_key: str | None = None
    model_text: str = ""

    @property
    def label(self) -> str:
        if self.board_key:
            return f"{self.port} · {BOARD_PROFILES[self.board_key]['label']}"
        return f"{self.port} · {self.description or 'Serielles Gerät'}"


@dataclass
class FirmwareBundle:
    board_key: str
    run_id: int
    run_number: int
    artifact_id: int
    artifact_name: str
    root: Path
    factory: Path
    metadata: Path
    ota: Path
    littlefs: Path

    @property
    def display_name(self) -> str:
        return f"{self.artifact_name} · Run #{self.run_number}"


class AppPaths:
    def __init__(self) -> None:
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".jarnsen"))
        self.root = base / "JarnsenMeshFlasher"
        self.profiles = self.root / "profiles"
        self.backups = self.root / "backups"
        self.firmware = self.root / "firmware-cache"
        self.logs = self.root / "logs"
        for directory in (self.root, self.profiles, self.backups, self.firmware, self.logs):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def active_profile(self) -> Path:
        return self.profiles / "active-profile.yaml"


PATHS = AppPaths()


def _startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return info


def helper_command() -> list[str]:
    if getattr(sys, "frozen", False):
        helper = Path(sys.executable).with_name("_JarnsenMeshHelper.exe")
        if not helper.exists():
            raise FlasherError(f"Helper fehlt: {helper}")
        return [str(helper)]

    helper = Path(__file__).with_name("helper.py")
    return [sys.executable, str(helper)]


def run_helper(
    tool: str,
    args: Iterable[str],
    *,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = helper_command() + [tool, *[str(a) for a in args]]
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout,
        startupinfo=_startupinfo(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if check and proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "").strip()
        raise FlasherError(details or f"{tool} fehlgeschlagen (Exit {proc.returncode})")
    return proc


def meshtastic(port: str, *args: str, timeout: int = 45, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_helper("meshtastic", ["--port", port, *args], timeout=timeout, check=check)


def esptool(port: str, *args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_helper("esptool", ["--port", port, *args], timeout=timeout, check=check)


def detect_board_from_text(text: str) -> str | None:
    upper = text.upper()
    for key, profile in BOARD_PROFILES.items():
        for token in profile["match"]:
            if str(token).upper() in upper:
                return key
    return None


def scan_devices(probe_timeout: int = 8) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for item in list_ports.comports():
        description = item.description or ""
        info_text = ""
        board_key = None
        try:
            result = meshtastic(item.device, "--info", timeout=probe_timeout, check=False)
            info_text = "\n".join(filter(None, (result.stdout, result.stderr)))
            board_key = detect_board_from_text(info_text)
        except Exception:
            pass
        devices.append(DeviceInfo(item.device, description, board_key, info_text))
    return devices


def export_profile(port: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = PATHS.profiles / f"master-{timestamp}.yaml"
    meshtastic(port, "--export-config", str(destination), timeout=90)
    if not destination.exists() or destination.stat().st_size < 20:
        raise FlasherError("Meshtastic hat kein verwertbares Profil erzeugt.")
    shutil.copy2(destination, PATHS.active_profile)
    return destination


def import_profile_file(source: Path) -> Path:
    if not source.exists():
        raise FlasherError("Profil-Datei nicht gefunden.")
    if source.suffix.lower() not in (".yaml", ".yml", ".cfg"):
        raise FlasherError("Unterstützt werden .yaml, .yml und .cfg Profile.")
    shutil.copy2(source, PATHS.active_profile)
    return PATHS.active_profile


def restore_profile(port: str, profile: Path | None = None) -> None:
    profile = profile or PATHS.active_profile
    if not profile.exists():
        raise FlasherError("Kein aktives Grundeinstellungs-Profil vorhanden.")
    meshtastic(port, "--configure", str(profile), timeout=180)


def set_names(port: str, long_name: str, short_name: str) -> None:
    long_name = long_name.strip()
    short_name = short_name.strip()
    if not long_name:
        raise FlasherError("Long Name fehlt.")
    if not (1 <= len(short_name) <= 4):
        raise FlasherError("Short Name muss 1 bis 4 Zeichen lang sein.")
    meshtastic(port, "--set-owner", long_name, timeout=60)
    meshtastic(port, "--set-owner-short", short_name, timeout=60)


def reboot_node(port: str) -> None:
    meshtastic(port, "--reboot", timeout=30, check=False)


def verify_node(port: str, expected_board: str | None = None) -> str:
    result = meshtastic(port, "--info", timeout=60)
    output = "\n".join(filter(None, (result.stdout, result.stderr)))
    if expected_board:
        detected = detect_board_from_text(output)
        if detected and detected != expected_board:
            raise FlasherError(
                f"Verifikation meldet falsches Board: {BOARD_PROFILES[detected]['label']}"
            )
    return output


def wait_for_serial(port: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if any(p.device.upper() == port.upper() for p in list_ports.comports()):
            time.sleep(3)
            return
        time.sleep(1)
    raise FlasherError(f"{port} ist nach dem Flash nicht wieder erschienen.")


class GitHubFirmwareClient:
    api = "https://api.github.com"

    def __init__(self) -> None:
        self.token = self._find_token()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "JarnsenMeshFlasher",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    @staticmethod
    def _find_token() -> str | None:
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            value = os.environ.get(name)
            if value:
                return value.strip()

        gh = shutil.which("gh")
        if gh:
            try:
                proc = subprocess.run(
                    [gh, "auth", "token"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                    startupinfo=_startupinfo(),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout.strip()
            except Exception:
                pass
        return None

    def _get_json(self, url: str, **params) -> dict:
        response = self.session.get(url, params=params, timeout=30)
        if response.status_code >= 400:
            raise FlasherError(
                f"GitHub API: HTTP {response.status_code} · {response.text[:220]}"
            )
        return response.json()

    def resolve_latest(self, board_key: str) -> FirmwareBundle:
        if board_key not in BOARD_PROFILES:
            raise FlasherError("Unbekanntes Board.")

        profile = BOARD_PROFILES[board_key]
        branch = str(profile["branch"])
        env = str(profile["pio_env"])

        runs = self._get_json(
            f"{self.api}/repos/{REPOSITORY}/actions/runs",
            branch=branch,
            status="success",
            per_page=30,
        ).get("workflow_runs", [])

        if not runs:
            raise FlasherError(f"Kein erfolgreicher GitHub-Run auf {branch} gefunden.")

        selected_run = None
        selected_artifact = None
        for run in runs:
            artifacts = self._get_json(
                f"{self.api}/repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts",
                per_page=100,
            ).get("artifacts", [])
            matches = [
                a
                for a in artifacts
                if not a.get("expired")
                and str(a.get("name", "")).startswith(f"firmware-{env}-")
            ]
            if matches:
                selected_run = run
                selected_artifact = matches[0]
                break

        if not selected_artifact or not selected_run:
            raise FlasherError(
                f"Kein gültiges Firmware-Artifact für {env} in den letzten erfolgreichen Runs gefunden."
            )

        if not self.token:
            raise FlasherError(
                "Für den Artifact-Download fehlt die GitHub-Anmeldung. "
                "Einmalig 'gh auth login' ausführen oder GH_TOKEN setzen."
            )

        artifact_id = int(selected_artifact["id"])
        run_id = int(selected_run["id"])
        run_number = int(selected_run.get("run_number") or 0)
        artifact_name = str(selected_artifact["name"])

        cache_dir = PATHS.firmware / f"{artifact_id}-{artifact_name}"
        marker = cache_dir / ".complete"
        if not marker.exists():
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            zip_path = cache_dir / "artifact.zip"
            self._download_zip(artifact_id, zip_path)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(cache_dir)
            zip_path.unlink(missing_ok=True)
            marker.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "run_number": run_number,
                        "artifact_id": artifact_id,
                        "artifact_name": artifact_name,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        return self._bundle_from_dir(
            board_key=board_key,
            run_id=run_id,
            run_number=run_number,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            root=cache_dir,
        )

    def _download_zip(self, artifact_id: int, destination: Path) -> None:
        response = self.session.get(
            f"{self.api}/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
            timeout=120,
            stream=True,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            raise FlasherError(
                f"Artifact-Download fehlgeschlagen: HTTP {response.status_code}"
            )
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    @staticmethod
    def _bundle_from_dir(
        *,
        board_key: str,
        run_id: int,
        run_number: int,
        artifact_id: int,
        artifact_name: str,
        root: Path,
    ) -> FirmwareBundle:
        env = str(BOARD_PROFILES[board_key]["pio_env"])
        factories = sorted(root.rglob(f"firmware-{env}-*.factory.bin"))
        if not factories:
            factories = sorted(root.rglob("firmware-*.factory.bin"))
        if not factories:
            raise FlasherError("Im Artifact fehlt die .factory.bin Firmware.")

        factory = factories[0]
        metadata = factory.with_name(factory.name.replace(".factory.bin", ".mt.json"))
        if not metadata.exists():
            raise FlasherError(f"Firmware-Metadaten fehlen: {metadata.name}")

        data = json.loads(metadata.read_text(encoding="utf-8"))
        mcu = str(data.get("mcu") or "").strip()
        if not mcu:
            raise FlasherError("MCU fehlt in der Firmware-Metadatei.")

        ota = next(iter(root.rglob(f"mt-{mcu}-ota.bin")), None)
        if ota is None:
            raise FlasherError(f"OTA-Systemdatei mt-{mcu}-ota.bin fehlt.")

        program = factory.name[: -len(".factory.bin")]
        littlefs_name = f"littlefs-{program.removeprefix('firmware-')}.bin"
        littlefs = next(iter(root.rglob(littlefs_name)), None)
        if littlefs is None:
            candidates = sorted(root.rglob(f"littlefs-{env}-*.bin"))
            littlefs = candidates[0] if candidates else None
        if littlefs is None:
            raise FlasherError("LittleFS-Datei fehlt im Firmware-Artifact.")

        return FirmwareBundle(
            board_key=board_key,
            run_id=run_id,
            run_number=run_number,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            root=root,
            factory=factory,
            metadata=metadata,
            ota=ota,
            littlefs=littlefs,
        )


def _flash_size_bytes(port: str) -> int:
    result = esptool(port, "flash_id", timeout=45, check=False)
    text = "\n".join(filter(None, (result.stdout, result.stderr)))
    match = re.search(r"Detected flash size:\s*(\d+)\s*(KB|MB)", text, re.IGNORECASE)
    if not match:
        return 8 * 1024 * 1024
    amount = int(match.group(1))
    unit = match.group(2).upper()
    return amount * (1024 if unit == "KB" else 1024 * 1024)


def backup_flash(port: str, board_key: str) -> Path:
    size = _flash_size_bytes(port)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = PATHS.backups / f"{board_key}-{port}-{timestamp}.bin"
    esptool(
        port,
        "--baud",
        "921600",
        "read_flash",
        "0x0",
        hex(size),
        str(destination),
        timeout=900,
    )
    if not destination.exists() or destination.stat().st_size < 1024:
        raise FlasherError("Sicherheitsbackup wurde nicht korrekt erstellt.")
    return destination


def _partition_offset(metadata: dict, subtype: str, fallback: str) -> str:
    for part in metadata.get("part", []):
        if str(part.get("subtype", "")).lower() == subtype.lower():
            value = part.get("offset")
            if value is not None:
                return str(value)
    return fallback


def flash_bundle(port: str, bundle: FirmwareBundle, log: Callable[[str], None] | None = None) -> None:
    metadata = json.loads(bundle.metadata.read_text(encoding="utf-8"))
    ota_offset = _partition_offset(metadata, "ota_1", "0x260000")
    spiffs_offset = _partition_offset(metadata, "spiffs", "0x300000")

    def note(text: str) -> None:
        if log:
            log(text)

    note("Flash löschen")
    esptool(port, "--baud", "115200", "erase_flash", timeout=180)

    note(f"Factory schreiben · {bundle.factory.name}")
    esptool(
        port,
        "--baud",
        "921600",
        "write_flash",
        "0x0",
        str(bundle.factory),
        timeout=600,
    )

    note(f"OTA-Systembereich schreiben · {ota_offset}")
    esptool(
        port,
        "--baud",
        "921600",
        "write_flash",
        ota_offset,
        str(bundle.ota),
        timeout=300,
    )

    note(f"LittleFS schreiben · {spiffs_offset}")
    esptool(
        port,
        "--baud",
        "921600",
        "write_flash",
        spiffs_offset,
        str(bundle.littlefs),
        timeout=300,
    )


def make_log_file() -> Path:
    return PATHS.logs / f"flasher-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
