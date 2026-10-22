#!/usr/bin/env python3
"""Apply a narrowly scoped safety patch to the pinned Meshtastic HTTPS dependency.

PlatformIO installs meshtastic/esp32_https_server outside the firmware tree.
The pinned dependency's handshake() spins forever on WANT_READ/WANT_WRITE, and
HTTPSServer::~HTTPSServer() calls init() rather than free() on two mbedTLS
contexts. Do not change the SDK's 16 KiB TLS record-buffer ABI here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

HANDSHAKE_MARKER = "JARNSEN_TLS_BOUNDED_HANDSHAKE_V1"
CONTEXT_MARKER = "JARNSEN_TLS_CONTEXT_FREE_V1"

HANDSHAKE_IMPL = """bool HTTPSConnection::handshake() {
  // JARNSEN_TLS_BOUNDED_HANDSHAKE_V1
  // The original WANT_READ/WANT_WRITE busy-loop could pin the Meshtastic
  // loopTask indefinitely while holding both large TLS record buffers.
  const uint32_t startedAt = millis();
  constexpr uint32_t MAX_HANDSHAKE_MS = 3500U;
  while (true) {
    const int res = mbedtls_ssl_handshake(&_ssl);
    if (res == 0) {
      HTTPS_LOGI("Jarnsen TLS handshake ok elapsed_ms=%u heap=%u largest=%u",
                 (unsigned)(millis() - startedAt),
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
      return true;
    }
    if (res != MBEDTLS_ERR_SSL_WANT_READ && res != MBEDTLS_ERR_SSL_WANT_WRITE) {
      HTTPS_LOGE("Jarnsen TLS handshake failed code=%d elapsed_ms=%u heap=%u largest=%u",
                 res, (unsigned)(millis() - startedAt),
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
      return false;
    }
    if ((uint32_t)(millis() - startedAt) >= MAX_HANDSHAKE_MS) {
      HTTPS_LOGE("Jarnsen TLS handshake timeout last_code=%d heap=%u largest=%u",
                 res, (unsigned)heap_caps_get_free_size(MALLOC_CAP_8BIT),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
      return false;
    }
    delay(1); // Yield so WiFi/FreeRTOS tasks can progress during the handshake.
  }
}

"""


def find_sources(libdeps: Path) -> tuple[Path, Path]:
    candidates = [
        path
        for path in libdeps.rglob("HTTPSConnection.cpp")
        if path.parent.joinpath("HTTPSServer.cpp").is_file()
        and "esp32_https_server" in str(path).lower()
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one pinned esp32_https_server dependency in {libdeps}; "
            f"found {len(candidates)}. Install PlatformIO dependencies first."
        )
    return candidates[0], candidates[0].with_name("HTTPSServer.cpp")


def patch(connection_file: Path, server_file: Path) -> None:
    connection = connection_file.read_text(encoding="utf-8")
    server = server_file.read_text(encoding="utf-8")

    if HANDSHAKE_MARKER not in connection:
        head = "bool HTTPSConnection::handshake() {"
        next_section = "\n/**\n * Initializes the connection"
        start = connection.find(head)
        stop = connection.find(next_section, start)
        if start < 0 or stop < 0:
            raise RuntimeError(
                "Pinned HTTPSConnection::handshake layout changed; refuse unsafe patch"
            )
        original = connection[start:stop]
        for required in (
            "while (true)",
            "mbedtls_ssl_handshake(&_ssl)",
            "MBEDTLS_ERR_SSL_WANT_READ",
            "MBEDTLS_ERR_SSL_WANT_WRITE",
        ):
            if required not in original:
                raise RuntimeError(f"Unexpected upstream handshake: missing {required}")
        connection = connection[:start] + HANDSHAKE_IMPL.rstrip() + connection[stop:]
        if "#include <esp_heap_caps.h>" not in connection:
            connection = connection.replace(
                '#include "mbedtls/error.h"',
                '#include "mbedtls/error.h"\n#include <esp_heap_caps.h>',
                1,
            )

    if CONTEXT_MARKER not in server:
        old = """HTTPSServer::~HTTPSServer() {

  mbedtls_ctr_drbg_init(&_ssl_ctr_drbg);
  mbedtls_entropy_init(&_ssl_entropy);
"""
        new = """HTTPSServer::~HTTPSServer() {
  // JARNSEN_TLS_CONTEXT_FREE_V1: init() here leaked entropy and RNG state
  // after stop()/delete during repeated WLAN sessions.
  mbedtls_ctr_drbg_free(&_ssl_ctr_drbg);
  mbedtls_entropy_free(&_ssl_entropy);
"""
        if old not in server:
            raise RuntimeError(
                "Pinned HTTPSServer destructor changed; refuse unsafe patch"
            )
        server = server.replace(old, new, 1)

    for required in (
        HANDSHAKE_MARKER,
        "MAX_HANDSHAKE_MS = 3500U",
        "delay(1)",
        "mbedtls_ssl_free(&_ssl);",
    ):
        if required not in connection:
            raise RuntimeError(f"Patched HTTPSConnection failed validation: {required}")
    for required in (
        CONTEXT_MARKER,
        "mbedtls_ctr_drbg_free(&_ssl_ctr_drbg)",
        "mbedtls_entropy_free(&_ssl_entropy)",
    ):
        if required not in server:
            raise RuntimeError(f"Patched HTTPSServer failed validation: {required}")

    if connection != connection_file.read_text(encoding="utf-8"):
        connection_file.write_text(connection, encoding="utf-8")
        print(f"JARNSEN TLS: patched bounded handshake: {connection_file}")
    if server != server_file.read_text(encoding="utf-8"):
        server_file.write_text(server, encoding="utf-8")
        print(f"JARNSEN TLS: patched context cleanup: {server_file}")
    print("JARNSEN TLS: upstream patches verified (idempotent)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--libdeps", type=Path, required=True)
    args = parser.parse_args()
    patch(*find_sources(args.libdeps))


if __name__ == "__main__":
    main()
