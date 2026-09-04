from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import customtkinter as ctk


@dataclass(frozen=True)
class FirmwareIdentity:
    product: str = ""
    version: str = ""
    build: int | None = None
    edition: str = ""

    @property
    def is_jarnsen(self) -> bool:
        text = f"{self.product} {self.edition}".upper().replace("_", "-")
        return "JARNSEN" in text


@dataclass(frozen=True)
class AvailableFirmware:
    version: str
    build: int
    run_id: int
    artifact_name: str


_CACHE: dict[str, tuple[float, AvailableFirmware]] = {}
_CACHE_LOCK = threading.Lock()


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _walk(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk(child)


def _label_text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "")
    except Exception:
        return ""


def _first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def parse_installed_firmware(text: str) -> FirmwareIdentity:
    text = text or ""
    product = ""
    edition = _first_match(
        text,
        [
            r'["\']firmwareEdition["\']\s*[:=]\s*["\']?([^"\'\s,}]+)',
            r'(?m)^\s*firmwareEdition\s*[:=]\s*([^\r\n]+)',
            r'(?m)^\s*Firmware Edition\s*[:=]\s*([^\r\n]+)',
        ],
    )
    if "JARNSEN-MESH" in text.upper() or "JARNSEN_MESH" in text.upper():
        product = "JARNSEN-MESH"
        if not edition:
            edition = "JARNSEN-MESH"
    elif edition:
        product = edition

    version = _first_match(
        text,
        [
            r'JARNSEN[-_ ]MESH\s*(?:VERSION\s*[:=]?\s*)?v?([0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc)\.\d+)?)',
            r'["\']jarnsen(?:Firmware)?Version["\']\s*[:=]\s*["\']?v?([^"\'\s,}]+)',
            r'["\']firmwareVersion["\']\s*[:=]\s*["\']?v?([^"\'\s,}]+)',
            r'(?m)^\s*firmwareVersion\s*[:=]\s*v?([^\r\n\s]+)',
            r'(?m)^\s*Firmware\s*[:=]\s*v?([^\r\n\s]+)',
        ],
    )
    build_text = _first_match(
        text,
        [
            r'JARNSEN[-_ ]MESH[^\r\n]*?Build\s*[#:=]?\s*(\d+)',
            r'["\'](?:jarnsen)?buildNumber["\']\s*[:=]\s*(\d+)',
            r'(?m)^\s*(?:JARNSEN )?Build\s*[#:=]?\s*(\d+)\s*$',
        ],
    )
    build = int(build_text) if build_text.isdigit() else None
    return FirmwareIdentity(product=product, version=version, build=build, edition=edition)


def _semver_key(version: str) -> tuple[int, int, int, int, int]:
    value = str(version or "").strip().lstrip("vV")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?", value, re.IGNORECASE)
    if not match:
        return (-1, -1, -1, -1, -1)
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    channel = (match.group(4) or "final").lower()
    sequence = int(match.group(5) or 0)
    rank = {"alpha": 0, "beta": 1, "rc": 2, "final": 3}.get(channel, -1)
    return (major, minor, patch, rank, sequence)


def _artifact_version(name: str) -> str:
    match = re.search(r"-v([0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc)\.\d+)?)-Build-\d+$", name, re.IGNORECASE)
    return match.group(1) if match else ""


def latest_available(services: Any, board_key: str, *, force: bool = False) -> AvailableFirmware:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(board_key)
        if cached and not force and now - cached[0] < 120.0:
            return cached[1]

    if board_key not in services.BOARD_PROFILES:
        raise services.FlasherError(f"Nicht unterstütztes Board: {board_key}")
    profile = services.BOARD_PROFILES[board_key]
    client = services.GitHubFirmwareClient()
    runs = client._get_json(
        f"{client.api}/repos/{services.REPOSITORY}/actions/runs",
        branch=services.UNIFIED_BRANCH,
        status="success",
        per_page=50,
    ).get("workflow_runs", [])
    wanted_prefix = str(profile["artifact_prefix"])
    for run in runs:
        if str(run.get("head_branch") or "") != services.UNIFIED_BRANCH:
            continue
        if str(run.get("path") or "") != services.UNIFIED_WORKFLOW_PATH:
            continue
        run_id = int(run["id"])
        artifacts = client._get_json(
            f"{client.api}/repos/{services.REPOSITORY}/actions/runs/{run_id}/artifacts",
            per_page=100,
        ).get("artifacts", [])
        artifact = next(
            (
                item
                for item in artifacts
                if not item.get("expired") and str(item.get("name") or "").startswith(wanted_prefix)
            ),
            None,
        )
        if artifact is None:
            continue
        artifact_name = str(artifact.get("name") or "")
        version = _artifact_version(artifact_name)
        if not version:
            continue
        available = AvailableFirmware(
            version=version,
            build=int(run.get("run_number") or 0),
            run_id=run_id,
            artifact_name=artifact_name,
        )
        with _CACHE_LOCK:
            _CACHE[board_key] = (time.monotonic(), available)
        return available
    raise services.FlasherError(f"Keine erfolgreiche JARNSEN-MESH Firmware für {profile['label']} gefunden.")


def comparison_text(installed: FirmwareIdentity, available: AvailableFirmware) -> tuple[str, str]:
    if not installed.is_jarnsen:
        if installed.version:
            return (
                "ANDERE FIRMWARE",
                f"Installiert ist {installed.edition or installed.product or 'Meshtastic'} {installed.version}; JARNSEN-MESH ist verfügbar.",
            )
        return ("JARNSEN-MESH VERFÜGBAR", "Installierte Firmware ist nicht eindeutig als JARNSEN-MESH erkannt.")

    installed_key = _semver_key(installed.version)
    available_key = _semver_key(available.version)
    if installed_key[0] >= 0 and available_key[0] >= 0:
        if installed_key < available_key:
            return ("UPDATE VERFÜGBAR", f"v{installed.version} → v{available.version}")
        if installed_key > available_key:
            return ("NEUER ALS GITHUB", f"Installiert v{installed.version}; GitHub v{available.version}")
        if installed.build is not None and available.build and installed.build < available.build:
            return ("UPDATE VERFÜGBAR", f"v{installed.version} · Build {installed.build} → Build {available.build}")
        if installed.build is not None and available.build and installed.build > available.build:
            return ("NEUER ALS GITHUB", f"Installiert Build {installed.build}; GitHub Build {available.build}")
        return ("AKTUELL", f"v{available.version}" + (f" · Build {available.build}" if available.build else ""))

    if installed.build is not None and available.build:
        if installed.build < available.build:
            return ("UPDATE VERFÜGBAR", f"Build {installed.build} → Build {available.build}")
        if installed.build == available.build:
            return ("AKTUELL", f"Build {available.build}")
        return ("NEUER ALS GITHUB", f"Installiert Build {installed.build}; GitHub Build {available.build}")

    return (
        "VERSION NICHT VERGLEICHBAR",
        "JARNSEN-MESH erkannt, aber der Node meldet noch keine eindeutige JARNSEN-Version/Buildnummer.",
    )


def _installed_display(identity: FirmwareIdentity) -> str:
    if identity.is_jarnsen:
        text = "JARNSEN-MESH"
    else:
        text = identity.edition or identity.product or "Firmware unbekannt"
    if identity.version:
        text += f" v{identity.version.lstrip('vV')}"
    if identity.build is not None:
        text += f" · Build {identity.build}"
    return text


def install(services: Any) -> None:
    """Show installed firmware metadata and compare it with the latest successful Unified-Core artifact."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if getattr(self, "_jarnsen_firmware_status_installed", False):
                return
            if not all(hasattr(self, name) for name in ("device_var", "board_var", "_selected_device", "_selected_board_key", "_append_log")):
                try:
                    self.after(180, patch_app)
                except Exception:
                    pass
                return

            board_label = None
            for widget in _walk(self):
                if _label_text(widget) == "Board":
                    board_label = widget
                    break
            if board_label is None:
                try:
                    self.after(200, patch_app)
                except Exception:
                    pass
                return
            board_row = getattr(board_label, "master", None)
            card = getattr(board_row, "master", None) if board_row is not None else None
            if card is None:
                return

            status_frame = ctk.CTkFrame(card, fg_color=("gray90", "gray20"), corner_radius=10)
            try:
                status_frame.pack(fill="x", padx=18, pady=(0, 12), after=board_row)
            except Exception:
                status_frame.pack(fill="x", padx=18, pady=(0, 12))
            status_frame.grid_columnconfigure(1, weight=1)

            self.installed_firmware_var = ctk.StringVar(value="Installiert: wird nach Geräteerkennung gelesen")
            self.available_firmware_var = ctk.StringVar(value="Verfügbar: noch nicht geprüft")
            self.firmware_compare_var = ctk.StringVar(value="")

            ctk.CTkLabel(status_frame, text="Firmware", font=ctk.CTkFont(size=11, weight="bold"), anchor="w").grid(row=0, column=0, sticky="w", padx=(10, 12), pady=(8, 2))
            ctk.CTkLabel(status_frame, textvariable=self.installed_firmware_var, anchor="w").grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(8, 2))
            ctk.CTkLabel(status_frame, text="GitHub", font=ctk.CTkFont(size=11, weight="bold"), anchor="w").grid(row=1, column=0, sticky="w", padx=(10, 12), pady=2)
            ctk.CTkLabel(status_frame, textvariable=self.available_firmware_var, anchor="w").grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=2)
            compare_label = ctk.CTkLabel(status_frame, textvariable=self.firmware_compare_var, anchor="w", font=ctk.CTkFont(size=11, weight="bold"))
            compare_label.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(2, 8))

            generation = {"value": 0}

            def refresh(force: bool = False) -> None:
                generation["value"] += 1
                token = generation["value"]
                device = self._selected_device()
                board_key = self._selected_board_key()
                if device is None:
                    self.installed_firmware_var.set("Installiert: kein Gerät ausgewählt")
                    self.available_firmware_var.set("Verfügbar: Board zuerst erkennen")
                    self.firmware_compare_var.set("")
                    return

                identity = parse_installed_firmware(getattr(device, "model_text", ""))
                self.installed_firmware_var.set(f"Installiert: {_installed_display(identity)}")
                if board_key not in services.BOARD_PROFILES:
                    self.available_firmware_var.set("Verfügbar: Board nicht eindeutig erkannt")
                    self.firmware_compare_var.set("Board manuell auswählen oder neu erkennen")
                    return

                self.available_firmware_var.set("Verfügbar: GitHub wird geprüft …")
                self.firmware_compare_var.set("")

                def worker() -> None:
                    try:
                        available = latest_available(services, board_key, force=force)
                        state, detail = comparison_text(identity, available)
                        def update() -> None:
                            if token != generation["value"]:
                                return
                            self.available_firmware_var.set(
                                f"Verfügbar: JARNSEN-MESH v{available.version} · Build {available.build}"
                            )
                            self.firmware_compare_var.set(f"{state} · {detail}")
                            try:
                                self._append_log(
                                    f"FIRMWARE STATUS · Port={device.port} · Installiert={_installed_display(identity)} · "
                                    f"Verfügbar=JARNSEN-MESH v{available.version} Build {available.build} · Status={state}"
                                )
                            except Exception:
                                pass
                        self.after(0, update)
                    except Exception as exc:
                        def fail() -> None:
                            if token != generation["value"]:
                                return
                            self.available_firmware_var.set("Verfügbar: GitHub-Prüfung fehlgeschlagen")
                            self.firmware_compare_var.set(str(exc))
                        self.after(0, fail)
                        _emit(f"FIRMWARE STATUS ERROR board={board_key!r} type={type(exc).__name__} message={exc}")

                threading.Thread(target=worker, name="jarnsen-firmware-status", daemon=True).start()

            self.refresh_firmware_status = refresh
            self.device_var.trace_add("write", lambda *_: self.after(220, refresh))
            self.board_var.trace_add("write", lambda *_: self.after(220, refresh))
            self._jarnsen_firmware_status_installed = True
            self.after(450, refresh)
            _emit("FIRMWARE STATUS UI installed auto-compare=1 artifact-download=0")

        try:
            self.after(820, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    services.parse_installed_firmware = parse_installed_firmware
    services.latest_available_firmware = lambda board_key, force=False: latest_available(services, board_key, force=force)
    _emit("FIRMWARE STATUS layer installed")
