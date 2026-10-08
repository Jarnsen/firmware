from __future__ import annotations

import ipaddress
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tls_provisioning
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        services = SimpleNamespace(
            PATHS=SimpleNamespace(root=root),
            FlasherError=RuntimeError,
        )
        ca_key, ca_cert = tls_provisioning._ensure_root_ca(services)
        assert (root / "tls" / "JARNSEN-MESH-Root-CA.key.pem").exists()
        assert (root / "tls" / "JARNSEN-MESH-Root-CA.cer.pem").exists()

        cert_der, key_der, root_der = tls_provisioning._make_node_material(
            ca_key, ca_cert, "0011223344556677"
        )
        leaf = x509.load_der_x509_certificate(cert_der)
        root_cert = x509.load_der_x509_certificate(root_der)
        assert leaf.issuer == root_cert.subject
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert ipaddress.ip_address("192.168.4.1") in san.get_values_for_type(
            x509.IPAddress
        )
        eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert ExtendedKeyUsageOID.SERVER_AUTH in eku
        assert len(key_der) > 512
        validity = leaf.not_valid_after_utc - leaf.not_valid_before_utc
        assert leaf.not_valid_after_utc > leaf.not_valid_before_utc
        assert validity <= timedelta(days=825), validity
    # Regression: first-flash must not call an early-bound services import
    # that silently bypasses tls_provisioning.install(services).
    flasher_app = Path(__file__).resolve().parents[1] / "app.py"
    app_source = flasher_app.read_text(encoding="utf-8")
    assert "runtime_services.restore_profile(port)" in app_source
    assert "\\n        restore_profile(port)" not in app_source
    provisioning_source = Path(tls_provisioning.__file__).read_text(encoding="utf-8")
    assert "TLS PROVISION POSTPROFILE FAIL" in provisioning_source
    assert "raise services.FlasherError(" in provisioning_source
    print("TLS provisioning certificate + firstflash hook contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
