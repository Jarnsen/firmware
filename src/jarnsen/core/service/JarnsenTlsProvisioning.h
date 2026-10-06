#pragma once

#include <Arduino.h>
#include <cstddef>
#include <cstdint>

namespace jarnsen
{

enum class TlsBlobKind : uint8_t {
    CERT = 0,
    PRIVATE_KEY = 1,
    ROOT_CA = 2,
};

struct TlsProvisioningInfo {
    bool ready = false;
    size_t certLength = 0;
    size_t keyLength = 0;
    size_t rootLength = 0;
};

bool tlsProvisioningInfo(TlsProvisioningInfo &info);
bool tlsProvisioned();

bool tlsProvisionBegin(size_t certLength, size_t keyLength, size_t rootLength);
bool tlsProvisionChunk(TlsBlobKind kind, size_t offset, const char *base64Data);
bool tlsProvisionCommit();
void tlsProvisionAbort();

bool tlsReadBlob(TlsBlobKind kind, uint8_t *buffer, size_t capacity, size_t &length);

} // namespace jarnsen
