#!/usr/bin/env python3
"""Offline regression test for the exact, idempotent pinned HTTPS patch."""

from pathlib import Path
from tempfile import TemporaryDirectory

from patch_jarnsen_https_dependency import (
    CONTEXT_MARKER,
    HANDSHAKE_MARKER,
    patch,
)

UPSTREAM_CONNECTION = """#include "HTTPSConnection.hpp"
#include "mbedtls/error.h"

bool HTTPSConnection::handshake() {
  int res;
  while (true) {
    res = mbedtls_ssl_handshake(&_ssl);
    if (res == 0) {
      return true;
    }
    if (res != MBEDTLS_ERR_SSL_WANT_READ && res != MBEDTLS_ERR_SSL_WANT_WRITE) {
      return false;
    }
  }
}

/**
 * Initializes the connection from a server socket.
 */
void close() { mbedtls_ssl_free(&_ssl); }
"""

UPSTREAM_SERVER = """#include "HTTPSServer.hpp"
HTTPSServer::~HTTPSServer() {

  mbedtls_ctr_drbg_init(&_ssl_ctr_drbg);
  mbedtls_entropy_init(&_ssl_entropy);
  mbedtls_pk_free(&_ssl_pk);
  mbedtls_x509_crt_free(&_ssl_cert);
  mbedtls_ssl_config_free(&_ssl_config);
}
"""


def main() -> None:
    with TemporaryDirectory() as folder:
        root = Path(folder) / "esp32_https_server" / "src"
        root.mkdir(parents=True)
        connection, server = root / "HTTPSConnection.cpp", root / "HTTPSServer.cpp"
        connection.write_text(UPSTREAM_CONNECTION)
        server.write_text(UPSTREAM_SERVER)
        patch(connection, server)
        first_connection, first_server = connection.read_text(), server.read_text()
        assert HANDSHAKE_MARKER in first_connection
        assert "MAX_HANDSHAKE_MS = 3500U" in first_connection
        assert 'HTTPS_LOGE("Jarnsen TLS handshake failed code=' in first_connection
        assert "mbedtls_ctr_drbg_free" in first_server
        assert "mbedtls_entropy_free" in first_server
        assert CONTEXT_MARKER in first_server
        patch(connection, server)
        assert first_connection == connection.read_text()
        assert first_server == server.read_text()
    print("JARNSEN TLS dependency patch test OK")


if __name__ == "__main__":
    main()
