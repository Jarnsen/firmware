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
JARNSEN_BASE_VERSION = "2.0.0"
UNIFIED_BRANCH = "refactor/jarn-mesh-unified-core"
UNIFIED_WORKFLOW_PATH = ".github/workflows/build-jarn-mesh-unified-core.yml"

# The flasher is intentionally pinned to the shared JARNSEN-MESH 2.0.0
# Unified Core.  It must never fall back to the legacy per-device 1.x builds.
BOARD_PROFILES = {
    "tracker": {
        "label": "Heltec Wireless Tracker V1.1",
        "pio_env": "heltec-wireless-tracker",
        "branch": UNIFIED_BRANCH,
        "workflow_path": UNIFIED_WORKFLOW_PATH,
        "artifact_prefix": f"JARNSEN-MESH-Heltec-Tracker-V1.1-v{JARNSEN_BASE_VERSION}",
        "match": (
            "HELTEC_WIRELESS_TRACKER",
            "HELTEC WIRELESS TRACKER",
            "WIRELESS_TRACKER",
            "TRACKER V1.1",
            "heltec-wireless-tracker",
        ),
    },
    "repeater": {
        "label": "Heltec V3",
        "pio_env": "heltec-v3",
        "branch": UNIFIED_BRANCH,
        "workflow_path": UNIFIED_WORKFLOW_PATH,
        "artifact_prefix": f"JARNSEN-MESH-Heltec-V3-v{JARNSEN_BASE_VERSION}",
        "match": ("HELTEC_V3", "HELTEC V3", "HELTEC-V3", "heltec-v3"),
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
    update: Path
    webflasher: Path
    checksums: Path
    version: str
    product: str = "JARNSEN-MESH"

    # Compatibility aliases for the existing detailed diagnostics layer.
    # JARNSEN-MESH 2.0.0 no longer uses the old otaBTupdate/.ota.json bundle.
    @property
    def metadata(self) -> Path:
        return self.checksums

    @property
    def ota(self) -> Path:
        return self.webflasher

    @property
    def littlefs(self) -> Path:
        return self.update

    @property
    def display_name(self) -> str:
        return (
            f"{self.product} v{self.version} · "
            f"{BOARD_PROFILES[self.board_key]['label']} · Build #{self.run_number}"
        )


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


def meshtastic(
    port: str,
    *args: str,
    timeout: int = 45,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_helper("meshtastic", ["--port", port, *args], timeout=timeout, check=check)


def esptool(
    port: str,
    *args: str,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
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
    active = PATHS.active_profile
    try:
        same_file = source.resolve() == active.resolve()
    except Exception:
        same_file = source == active
    if not same_file:
        shutil.copy2(source, active)
    # Return the user's selected file so the UI keeps the meaningful filename.
    return source


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


def _parse_version(artifact_name: str) -> str:
    match = re.search(
        rf"-v({re.escape(JARNSEN_BASE_VERSION)}(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?)-Build-\d+$",
        artifact_name,
    )
    if not match:
        raise FlasherError(
            f"Artifact gehört nicht zur hinterlegten JARNSEN-MESH {JARNSEN_BASE_VERSION} Linie: "
            f"{artifact_name}"
        )
    return match.group(1)


def _read_checksum_manifest(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if not match:
            continue
        name = match.group(2).strip()
        while name.startswith("./") or name.startswith(".\\"):
            name = name[2:]
        checksums[Path(name).name] = match.group(1).lower()
    return checksums


class GitHubFirmwareClient:
    api = "https://api.github.com"

    def __init__(self) -> None:
        self.token = self._find_token()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "JARNSEN-MESH-Flasher",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    @staticmethod
    def _find_token() -> str | None:
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            value = os.environ.get(name, "").strip()
            if value:
                return value
        try:
            if shutil.which("gh"):
                proc = subprocess.run(
                    ["gh", "auth", "token"],
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

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        response = self.session.request(method, url, timeout=30, **kwargs)
        if response.status_code >= 400:
            details = response.text[:500].strip()
            raise FlasherError(
                f"GitHub API {response.status_code}: {details or response.reason}"
            )
        return response

    def _get_json(self, url: str, **params) -> dict:
        return self._request("GET", url, params=params).json()

    def _run_matches_unified_core(self, run: dict) -> bool:
        return (
            str(run.get("head_branch") or "") == UNIFIED_BRANCH
            and str(run.get("path") or "") == UNIFIED_WORKFLOW_PATH
        )

    def resolve_latest(self, board_key: str) -> FirmwareBundle:
        if board_key not in BOARD_PROFILES:
            raise FlasherError(f"Nicht unterstütztes Board: {board_key}")
        profile = BOARD_PROFILES[board_key]
        wanted_prefix = str(profile["artifact_prefix"])
        runs = self._get_json(
            f"{self.api}/repos/{REPOSITORY}/actions/runs",
            branch=UNIFIED_BRANCH,
            status="success",
            per_page=50,
        ).get("workflow_runs", [])

        candidates = [run for run in runs if self._run_matches_unified_core(run)]
        if not candidates:
            raise FlasherError(
                "Kein erfolgreicher JARNSEN-MESH 2.0.0 Unified-Core-Run gefunden."
            )

        diagnostics: list[str] = []
        for run in candidates:
            run_id = int(run["id"])
            run_number = int(run.get("run_number", 0))
            artifacts = self._get_json(
                f"{self.api}/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts",
                per_page=100,
            ).get("artifacts", [])
            artifact = next(
                (
                    item
                    for item in artifacts
                    if not item.get("expired")
                    and str(item.get("name", "")).startswith(wanted_prefix)
                ),
                None,
            )
            if not artifact:
                diagnostics.append(
                    f"Run #{run_number}: kein Artifact mit Prefix {wanted_prefix}"
                )
                continue

            artifact_name = str(artifact["name"])
            version = _parse_version(artifact_name)
            if not version.startswith(JARNSEN_BASE_VERSION):
                diagnostics.append(
                    f"Run #{run_number}: falsche Version {version}"
                )
                continue

            return self._download_and_resolve(
                board_key=board_key,
                run_id=run_id,
                run_number=run_number,
                artifact=artifact,
                version=version,
            )

        detail = "\n".join(diagnostics[:10])
        raise FlasherError(
            f"Kein gültiges JARNSEN-MESH {JARNSEN_BASE_VERSION} Artifact für "
            f"{profile['label']} gefunden."
            + (f"\n\n{detail}" if detail else "")
        )

    def _download_and_resolve(
        self,
        *,
        board_key: str,
        run_id: int,
        run_number: int,
        artifact: dict,
        version: str,
    ) -> FirmwareBundle:
        artifact_id = int(artifact["id"])
        artifact_name = str(artifact["name"])
        cache_root = PATHS.firmware / f"{artifact_id}-{artifact_name}"
        marker = cache_root / ".complete"

        if not marker.exists():
            if not self.token:
                raise FlasherError(
                    "GitHub Actions Artifact-Download braucht eine GitHub-Anmeldung. "
                    "Bitte einmal 'gh auth login' ausführen oder GH_TOKEN setzen."
                )
            cache_root.mkdir(parents=True, exist_ok=True)
            archive = cache_root.with_suffix(".zip")
            response = self._request(
                "GET",
                f"{self.api}/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
            )
            archive.write_bytes(response.content)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(cache_root)
            archive.unlink(missing_ok=True)
            marker.write_text(
                json.dumps(
                    {
                        "artifact_id": artifact_id,
                        "artifact_name": artifact_name,
                        "run_id": run_id,
                        "run_number": run_number,
                        "version": version,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        return self._resolve_bundle_files(
            board_key=board_key,
            run_id=run_id,
            run_number=run_number,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            cache_root=cache_root,
            version=version,
        )

    def _resolve_bundle_files(
        self,
        *,
        board_key: str,
        run_id: int,
        run_number: int,
        artifact_id: int,
        artifact_name: str,
        cache_root: Path,
        version: str,
    ) -> FirmwareBundle:
        profile = BOARD_PROFILES[board_key]
        env_name = str(profile["pio_env"])
        all_files = [p for p in cache_root.rglob("*") if p.is_file() and p.name != ".complete"]

        def pick_exact(name: str) -> Path:
            matches = [p for p in all_files if p.name.lower() == name.lower()]
            if len(matches) != 1:
                raise FlasherError(
                    f"Artifact {artifact_name}: {name} nicht eindeutig gefunden ({len(matches)} Treffer)."
                )
            return matches[0]

        factory = pick_exact(f"firmware-{env_name}.factory.bin")
        update = pick_exact(f"firmware-{env_name}.bin")
        webflasher = pick_exact(f"firmware-{env_name}.webflasher.bin")
        checksums = pick_exact("SHA256SUMS.txt")
        expected = _read_checksum_manifest(checksums)
        for file_path in (factory, update, webflasher):
            wanted = expected.get(file_path.name)
            if not wanted:
                raise FlasherError(f"SHA256SUMS enthält {file_path.name} nicht.")
            actual = _sha256(file_path)
            if actual != wanted:
                raise FlasherError(
                    f"SHA256-Prüfung fehlgeschlagen: {file_path.name}\n"
                    f"Erwartet: {wanted}\nIst: {actual}"
                )

        return FirmwareBundle(
            board_key=board_key,
            run_id=run_id,
            run_number=run_number,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            root=cache_root,
            factory=factory,
            update=update,
            webflasher=webflasher,
            checksums=checksums,
            version=version,
        )


def _flash_size_bytes(port: str) -> int:
    result = esptool(port, "flash_id", timeout=45)
    text = "\n".join(filter(None, (result.stdout, result.stderr)))
    match = re.search(r"Detected flash size:\s*(\d+)MB", text, re.IGNORECASE)
    if not match:
        raise FlasherError("Flash-Größe konnte nicht ermittelt werden.")
    return int(match.group(1)) * 1024 * 1024


def backup_flash(port: str, board_key: str) -> Path:
    size = _flash_size_bytes(port)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = PATHS.backups / f"{board_key}-{port}-{timestamp}.bin"
    esptool(port, "read_flash", "0x0", hex(size), str(target), timeout=900)
    if not target.exists() or target.stat().st_size != size:
        raise FlasherError("Sicherheitsbackup wurde nicht vollständig erstellt.")
    return target


def flash_bundle(port: str, bundle: FirmwareBundle, log: Callable[[str], None] | None = None) -> None:
    """Install a verified JARNSEN-MESH 2.0.0 factory image to both OTA slots."""
    if log:
        log(
            f"JARNSEN-MESH v{bundle.version} · Factory={bundle.factory.name} · "
            f"OTA0/OTA1 aus {bundle.webflasher.name}"
        )

    # JARNSEN-MESH 2.0.0 Unified Core packages a full factory image plus a
    # webflasher/OTA image.  The app partition starts at 0x10000 and the
    # second JARNSEN OTA slot is fixed at 0x340000.
    esptool(port, "erase_flash", timeout=180)
    esptool(
        port,
        "--baud",
        "921600",
        "write_flash",
        "--flash_mode",
        "dio",
        "--flash_freq",
        "80m",
        "--flash_size",
        "keep",
        "0x0",
        str(bundle.factory),
        timeout=600,
    )

    # Make sure both OTA application slots contain the exact same current build.
    esptool(
        port,
        "--baud",
        "921600",
        "write_flash",
        "--flash_mode",
        "dio",
        "--flash_freq",
        "80m",
        "--flash_size",
        "keep",
        "0x10000",
        str(bundle.webflasher),
        "0x340000",
        str(bundle.webflasher),
        timeout=600,
    )

    # The factory image includes bootloader/partition metadata and LittleFS.
    # The second write only synchronizes the two OTA app slots; reset so the
    # bootloader chooses the freshly installed application normally.
    esptool(port, "run", timeout=30, check=False)


def make_log_file() -> Path:
    PATHS.logs.mkdir(parents=True, exist_ok=True)
    return PATHS.logs / f"flasher-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
