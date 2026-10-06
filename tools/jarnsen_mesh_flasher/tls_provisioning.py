from __future__ import annotations

import base64
import ipaddress
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import serial
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_TLS_MARKER = "===JARNSEN_TLS==="
_TLS_OK = "===JARNSEN_TLS_OK==="
_TLS_ERROR = "===JARNSEN_TLS_ERROR==="
_INFO_MARKER = "===JARNSEN_INFO==="
_HW_MARKER = "JARNSEN_HW_INFO"
_SERVICE_IP = ipaddress.ip_address("192.168.4.1")


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _tls_dir(services: Any) -> Path:
    root = Path(services.PATHS.root) / "tls"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _private_mode(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _ensure_root_ca(services: Any) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    root = _tls_dir(services)
    key_path = root / "JARNSEN-MESH-Root-CA.key.pem"
    cert_path = root / "JARNSEN-MESH-Root-CA.cer.pem"

    if key_path.exists() and cert_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        if not isinstance(key, rsa.RSAPrivateKey):
            raise services.FlasherError("JARNSEN Root-CA benutzt keinen RSA-Schlüssel.")
        return key, cert

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JARNSEN MESH"),
            x509.NameAttribute(NameOID.COMMON_NAME, "JARNSEN MESH Root CA"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365 * 20))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _private_mode(key_path)
    _emit(f"TLS ROOT CA created cert={cert_path} key={key_path}")
    return key, cert


def _make_node_material(
    ca_key: rsa.RSAPrivateKey, ca_cert: x509.Certificate, chip_id: str
) -> tuple[bytes, bytes, bytes]:
    node_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    clean_chip = re.sub(r"[^0-9A-F]", "", chip_id.upper()) or "UNKNOWN"
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JARNSEN MESH"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"JARNSEN-{clean_chip}"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(node_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=800))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(_SERVICE_IP)]), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    key_der = node_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    root_der = ca_cert.public_bytes(serialization.Encoding.DER)
    return cert_der, key_der, root_der


class _RawSession:
    def __init__(self, port: str) -> None:
        self.port = port
        self.ser: serial.Serial | None = None

    def __enter__(self) -> "_RawSession":
        self.ser = serial.Serial(
            port=self.port, baudrate=115200, timeout=0.12, write_timeout=2.0
        )
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        time.sleep(0.20)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def command(self, command: str, expected: str, timeout: float = 8.0) -> str:
        assert self.ser is not None
        self.ser.write((command.rstrip() + "\n").encode("ascii"))
        self.ser.flush()
        deadline = time.monotonic() + timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            chunk = self.ser.read(512)
            if not chunk:
                time.sleep(0.02)
                continue
            buffer.extend(chunk)
            text = buffer.decode("utf-8", errors="replace")
            for line in text.replace("\r", "\n").split("\n")[:-1]:
                line = line.strip()
                if not line:
                    continue
                if line.startswith(_TLS_ERROR) or (
                    line.startswith("===JARNSEN_") and "_ERROR===" in line
                ):
                    raise RuntimeError(line)
                if line.startswith(expected):
                    return line
        seen = buffer.decode("utf-8", errors="replace")[-500:]
        raise TimeoutError(f"Keine Antwort auf {command!r} von {self.port}. Empfangen: {seen!r}")


def _parse_ready(line: str) -> bool:
    return bool(re.search(r"\bready=1\b", line))


def _parse_chip(line: str) -> str:
    match = re.search(r"\bchip=([0-9A-Fa-f]{16})\b", line)
    if not match:
        raise ValueError(f"Chip-ID fehlt in Firmware-Antwort: {line}")
    return match.group(1).upper()


def _send_blob(session: _RawSession, kind: str, payload: bytes) -> None:
    # 72 raw bytes -> 96 base64 characters, keeping the complete command safely
    # below the firmware's 160-byte JARNSEN_TOOL line buffer.
    offset = 0
    while offset < len(payload):
        chunk = payload[offset : offset + 72]
        encoded = base64.b64encode(chunk).decode("ascii")
        session.command(
            f"JARNSEN_TOOL_TLS_CHUNK {kind} {offset} {encoded}",
            _TLS_OK,
            timeout=8.0,
        )
        offset += len(chunk)


def ensure_tls_provisioned(services: Any, port: str) -> bool:
    guard_factory = getattr(services, "jarnsen_serial_guard", None)

    def run() -> bool:
        with _RawSession(port) as session:
            info = session.command("JARNSEN_TOOL_INFO", _INFO_MARKER, timeout=6.0)
            if "tls_provision=1" not in info:
                _emit(f"TLS PROVISION skip port={port} reason=firmware-capability")
                return False

            tls = session.command("JARNSEN_TOOL_TLS_INFO", _TLS_MARKER, timeout=6.0)
            hardware = session.command("JARNSEN_TOOL_HW_INFO", _HW_MARKER, timeout=6.0)
            chip = _parse_chip(hardware)
            node_dir = _tls_dir(services) / "nodes"
            node_dir.mkdir(parents=True, exist_ok=True)
            local_cert_path = node_dir / f"{chip}.cer.der"

            if _parse_ready(tls) and local_cert_path.exists():
                try:
                    existing = x509.load_der_x509_certificate(local_cert_path.read_bytes())
                    remaining = existing.not_valid_after_utc - datetime.now(timezone.utc)
                    if remaining > timedelta(days=90):
                        _emit(
                            f"TLS PROVISION existing port={port} chip={chip} "
                            f"days_remaining={remaining.days} response={tls!r}"
                        )
                        return True
                    _emit(
                        f"TLS PROVISION renew port={port} chip={chip} "
                        f"days_remaining={remaining.days}"
                    )
                except Exception as exc:
                    _emit(
                        f"TLS PROVISION local-cert-invalid port={port} chip={chip} "
                        f"type={type(exc).__name__} message={exc}"
                    )
            elif _parse_ready(tls) and not local_cert_path.exists():
                # The node already has a certificate but this PC no longer has
                # the matching local metadata. Do not silently rotate to a new
                # trust root; preserving the installed iPhone trust chain is safer.
                _emit(
                    f"TLS PROVISION existing-untracked port={port} chip={chip} "
                    "action=preserve-node-certificate"
                )
                return True

            ca_key, ca_cert = _ensure_root_ca(services)
            cert_der, key_der, root_der = _make_node_material(ca_key, ca_cert, chip)

            session.command(
                f"JARNSEN_TOOL_TLS_BEGIN {len(cert_der)} {len(key_der)} {len(root_der)}",
                _TLS_OK,
                timeout=8.0,
            )
            try:
                _send_blob(session, "C", cert_der)
                _send_blob(session, "K", key_der)
                _send_blob(session, "R", root_der)
                session.command("JARNSEN_TOOL_TLS_COMMIT", _TLS_OK, timeout=12.0)
            except Exception:
                try:
                    session.command("JARNSEN_TOOL_TLS_ABORT", _TLS_OK, timeout=3.0)
                except Exception:
                    pass
                raise

            verify = session.command("JARNSEN_TOOL_TLS_INFO", _TLS_MARKER, timeout=6.0)
            if not _parse_ready(verify):
                raise services.FlasherError(
                    f"HTTPS-Zertifikat wurde geschrieben, aber nicht bestätigt: {verify}"
                )

            local_cert_path.write_bytes(cert_der)
            _emit(
                f"TLS PROVISION ok port={port} chip={chip} cert={len(cert_der)} key={len(key_der)} root={len(root_der)}"
            )
            return True

    if callable(guard_factory):
        with guard_factory(port):
            return run()
    return run()


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_tls_provisioning_v1", False):
        return

    base_restore_profile = services.restore_profile

    def restore_profile(port: str, profile=None):
        ensure_tls_provisioned(services, port)
        return base_restore_profile(port, profile)

    services.restore_profile = restore_profile
    services.ensure_tls_provisioned = lambda port: ensure_tls_provisioned(services, port)
    services._jarnsen_tls_provisioning_v1 = True
    _emit("TLS PROVISIONING installed first-flash-hook=restore_profile ip-san=192.168.4.1")
