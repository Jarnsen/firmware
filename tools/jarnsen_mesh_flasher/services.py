from __future__ import annotations

import hashlib
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

# These are the real JARN-MESH build sources.  The flasher deliberately binds
# to the product workflows/artifacts instead of the generic Meshtastic naming.
BOARD_PROFILES = {
    "tracker": {
        "label": "Heltec Wireless Tracker V1.1",
        "pio_env": "heltec-wireless-tracker",
        "branch": "heltec-tracker-v11-vehicle-motion-wake",
        "workflow_path": ".github/workflows/build-heltec-tracker-v11-vehicle-motion-wake.yml",
        "artifact_prefix": "heltec-tracker-v11-jarn-mesh-v",
        "metadata_device": "HELTEC_TRACKER_V1.1",
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
        "workflow_path": ".github/workflows/build-heltec-v3-repeater-light-sleep.yml",
        "artifact_prefix": "heltec-v3-repeater-jarn-mesh-v",
        "metadata_device": "HELTEC_V3_REPEATER",
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
    update: Path
    version: str = ""
    product: str = "JARN-MESH"

    # Compatibility for the diagnostics module from older builds.  JARN-MESH
    # does not ship a separate LittleFS image in these complete packages.
    @property
    def littlefs(self) -> Path:
        return self.update

    @property
    def display_name(self) -> str:
        version = f" · {self.product} v{self.version}" if self.version else ""
        return f"{self.artifact_name}{version} · Run #{self.run_number}"


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
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "_JarnsenMeshHelper.exe")
        candidates.append(Path(sys.executable).with_name("_JarnsenMeshHelper.exe"))
        for helper in candidates:
            if helper.exists():
                return [str(helper)]
        raise FlasherError("Eingebetteter JARNSEN-MESH Helper fehlt.")

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


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
        workflow_path = str(profile["workflow_path"])
        artifact_prefix = str(profile["artifact_prefix"])

        # Search only successful push builds from the actual JARN-MESH product
        # branch.  Other CI/Semgrep/PR runs on the same branch are ignored.
        runs = self._get_json(
            f"{self.api}/repos/{REPOSITORY}/actions/runs",
            branch=branch,
            event="push",
            status="success",
            per_page=50,
        ).get("workflow_runs", [])

        product_runs = [
            run
            for run in runs
            if str(run.get("path") or "") == workflow_path
            and str(run.get("head_branch") or "") == branch
            and str(run.get("conclusion") or "") == "success"
        ]
        if not product_runs:
            raise FlasherError(
                f"Kein erfolgreicher JARN-MESH Firmware-Build für {profile['label']} gefunden."
            )

        selected_run = None
        selected_artifact = None
        for run in product_runs:
            artifacts = self._get_json(
                f"{self.api}/repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts",
                per_page=100,
            ).get("artifacts", [])
            matches = [
                artifact
                for artifact in artifacts
                if not artifact.get("expired")
                and str(artifact.get("name") or "").startswith(artifact_prefix)
                and not str(artifact.get("name") or "").endswith("-part")
            ]
            if matches:
                selected_run = run
                selected_artifact = max(
                    matches,
                    key=lambda item: str(item.get("created_at") or ""),
                )
                break

        if not selected_artifact or not selected_run:
            raise FlasherError(
                f"JARN-MESH Build gefunden, aber kein vollständiges Firmware-Paket mit Präfix "
                f"'{artifact_prefix}' vorhanden."
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
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    archive.extractall(cache_dir)
            except zipfile.BadZipFile as exc:
                raise FlasherError("GitHub hat kein gültiges Firmware-ZIP geliefert.") from exc
            finally:
                zip_path.unlink(missing_ok=True)
            marker.write_text(
                json.dumps(
                    {
                        "source": "JARN-MESH",
                        "workflow_path": workflow_path,
                        "branch": branch,
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
            timeout=180,
            stream=True,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            auth_hint = ""
            if response.status_code in (401, 403) and not self.token:
                auth_hint = " · GitHub CLI anmelden (gh auth login), falls GitHub den Download nicht anonym zulässt."
            raise FlasherError(
                f"JARN-MESH Artifact-Download fehlgeschlagen: HTTP {response.status_code}{auth_hint}"
            )
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        if not destination.exists() or destination.stat().st_size < 1024:
            raise FlasherError("JARN-MESH Artifact-Download ist leer oder unvollständig.")

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
        profile = BOARD_PROFILES[board_key]
        expected_device = str(profile["metadata_device"])

        metadata_candidates = sorted(root.rglob("*.ota.json"))
        # Prefer the versioned metadata; aliases have branch names and are only
        # used as fallback.
        metadata_candidates.sort(
            key=lambda path: ("jarn-mesh" not in path.name.lower(), len(path.name))
        )
        metadata = None
        data: dict = {}
        for candidate in metadata_candidates:
            try:
                candidate_data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(candidate_data.get("device") or "") == expected_device:
                metadata = candidate
                data = candidate_data
                break
        if metadata is None:
            raise FlasherError(
                f"Im JARN-MESH Paket fehlt eine gültige OTA-Metadatei für {expected_device}."
            )

        firmware_asset = str(data.get("firmware_asset") or "").strip()
        if not firmware_asset:
            raise FlasherError("JARN-MESH OTA-Metadaten enthalten kein firmware_asset.")
        update = next(iter(root.rglob(firmware_asset)), None)
        if update is None:
            raise FlasherError(f"JARN-MESH Update-Datei fehlt: {firmware_asset}")

        ota_loader_name = str(data.get("ota_loader_asset") or "otaBTupdate.bin").strip()
        ota = next(iter(root.rglob(ota_loader_name)), None)
        if ota is None:
            raise FlasherError(f"JARN-MESH OTA-Loader fehlt: {ota_loader_name}")

        factories = sorted(root.rglob("*.factory.bin"))
        factory = next(
            (path for path in factories if "jarn-mesh" in path.name.lower()),
            factories[0] if factories else None,
        )
        if factory is None:
            raise FlasherError("Im JARN-MESH Paket fehlt die .factory.bin Firmware.")

        expected_firmware_hash = str(data.get("firmware_sha256") or "").lower().strip()
        if expected_firmware_hash and _sha256(update) != expected_firmware_hash:
            raise FlasherError("SHA-256 der JARN-MESH Update-Firmware stimmt nicht.")

        expected_loader_hash = str(data.get("ota_loader_sha256") or "").lower().strip()
        if expected_loader_hash and _sha256(ota) != expected_loader_hash:
            raise FlasherError("SHA-256 des JARN-MESH OTA-Loaders stimmt nicht.")

        metadata_run = int(data.get("workflow_run_number") or 0)
        if metadata_run and metadata_run != run_number:
            raise FlasherError(
                f"JARN-MESH Metadaten gehören zu Build {metadata_run}, Artifact aber zu Build {run_number}."
            )

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
            update=update,
            version=str(data.get("version") or ""),
            product=str(data.get("product") or "JARN-MESH"),
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


def flash_bundle(port: str, bundle: FirmwareBundle, log: Callable[[str], None] | None = None) -> None:
    metadata = json.loads(bundle.metadata.read_text(encoding="utf-8"))
    ota_offset = str(metadata.get("ota_partition_offset") or "0x340000")

    def note(text: str) -> None:
        if log:
            log(text)

    note(f"JARN-MESH Paket geprüft · {bundle.product} v{bundle.version} · Build {bundle.run_number}")
    note("Flash löschen")
    esptool(port, "--baud", "115200", "erase_flash", timeout=180)

    note(f"JARN-MESH Factory schreiben · {bundle.factory.name} · 0x0")
    esptool(
        port,
        "--baud",
        "921600",
        "write_flash",
        "0x0",
        str(bundle.factory),
        timeout=600,
    )

    note(f"JARN-MESH OTA-Loader schreiben · {bundle.ota.name} · {ota_offset}")
    esptool(
        port,
        "--baud",
        "921600",
        "write_flash",
        ota_offset,
        str(bundle.ota),
        timeout=300,
    )

    # The JARN-MESH installer resets OTA selection after writing the main image
    # and otaBTupdate.  Do the same so the freshly provisioned node boots app0.
    note("OTA-Bootwahlschalter auf Hauptfirmware zurücksetzen · 0xE000/0x2000")
    esptool(
        port,
        "--baud",
        "115200",
        "erase_region",
        "0xE000",
        "0x2000",
        timeout=120,
    )


def make_log_file() -> Path:
    return PATHS.logs / f"flasher-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
