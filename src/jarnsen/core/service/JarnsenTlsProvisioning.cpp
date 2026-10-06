#include "jarnsen/core/service/JarnsenTlsProvisioning.h"

#if defined(ARCH_ESP32)

#include "DebugConfiguration.h"

#include <Preferences.h>
#include <mbedtls/base64.h>
#include <new>

namespace jarnsen
{
namespace
{
constexpr const char *HTTPS_NAMESPACE = "MeshtasticHTTPS";
constexpr const char *JARNSEN_TLS_NAMESPACE = "JarnsenTLS";
constexpr const char *CERT_KEY = "cert";
constexpr const char *PRIVATE_KEY_KEY = "PK";
constexpr const char *ROOT_CA_KEY = "root";
constexpr const char *READY_KEY = "ready";
constexpr uint32_t READY_MAGIC = 0x31534c54U; // "TLS1"
constexpr size_t MAX_TLS_BLOB = 8192U;

struct ProvisionBuffer {
    uint8_t *data = nullptr;
    size_t expected = 0;
    size_t received = 0;
};

ProvisionBuffer certBuffer{};
ProvisionBuffer keyBuffer{};
ProvisionBuffer rootBuffer{};

void clearBuffer(ProvisionBuffer &buffer)
{
    delete[] buffer.data;
    buffer = {};
}

void clearAllBuffers()
{
    clearBuffer(certBuffer);
    clearBuffer(keyBuffer);
    clearBuffer(rootBuffer);
}

ProvisionBuffer *selectBuffer(TlsBlobKind kind)
{
    switch (kind) {
    case TlsBlobKind::CERT:
        return &certBuffer;
    case TlsBlobKind::PRIVATE_KEY:
        return &keyBuffer;
    case TlsBlobKind::ROOT_CA:
        return &rootBuffer;
    default:
        return nullptr;
    }
}

bool validLength(size_t length)
{
    return length > 0U && length <= MAX_TLS_BLOB;
}

bool readLengths(size_t &certLength, size_t &keyLength, size_t &rootLength, uint32_t &ready)
{
    certLength = keyLength = rootLength = 0U;
    ready = 0U;

    Preferences httpsPrefs;
    if (!httpsPrefs.begin(HTTPS_NAMESPACE, true))
        return false;
    certLength = httpsPrefs.getBytesLength(CERT_KEY);
    keyLength = httpsPrefs.getBytesLength(PRIVATE_KEY_KEY);
    httpsPrefs.end();

    Preferences tlsPrefs;
    if (!tlsPrefs.begin(JARNSEN_TLS_NAMESPACE, true))
        return false;
    rootLength = tlsPrefs.getBytesLength(ROOT_CA_KEY);
    ready = tlsPrefs.getUInt(READY_KEY, 0U);
    tlsPrefs.end();
    return true;
}
} // namespace

bool tlsProvisioningInfo(TlsProvisioningInfo &info)
{
    size_t certLength = 0U;
    size_t keyLength = 0U;
    size_t rootLength = 0U;
    uint32_t ready = 0U;
    const bool readable = readLengths(certLength, keyLength, rootLength, ready);
    info.certLength = certLength;
    info.keyLength = keyLength;
    info.rootLength = rootLength;
    info.ready = readable && ready == READY_MAGIC && validLength(certLength) && validLength(keyLength) &&
                 validLength(rootLength);
    return readable;
}

bool tlsProvisioned()
{
    TlsProvisioningInfo info{};
    return tlsProvisioningInfo(info) && info.ready;
}

bool tlsProvisionBegin(size_t certLength, size_t keyLength, size_t rootLength)
{
    tlsProvisionAbort();
    if (!validLength(certLength) || !validLength(keyLength) || !validLength(rootLength))
        return false;

    certBuffer.data = new (std::nothrow) uint8_t[certLength];
    keyBuffer.data = new (std::nothrow) uint8_t[keyLength];
    rootBuffer.data = new (std::nothrow) uint8_t[rootLength];
    if (!certBuffer.data || !keyBuffer.data || !rootBuffer.data) {
        tlsProvisionAbort();
        return false;
    }

    certBuffer.expected = certLength;
    keyBuffer.expected = keyLength;
    rootBuffer.expected = rootLength;
    return true;
}

bool tlsProvisionChunk(TlsBlobKind kind, size_t offset, const char *base64Data)
{
    ProvisionBuffer *buffer = selectBuffer(kind);
    if (!buffer || !buffer->data || !base64Data || offset != buffer->received || offset >= buffer->expected)
        return false;

    const size_t inputLength = strlen(base64Data);
    if (inputLength == 0U || inputLength > 112U)
        return false;

    uint8_t decoded[96] = {};
    size_t decodedLength = 0U;
    const int result =
        mbedtls_base64_decode(decoded, sizeof(decoded), &decodedLength,
                              reinterpret_cast<const unsigned char *>(base64Data), inputLength);
    if (result != 0 || decodedLength == 0U || buffer->received + decodedLength > buffer->expected)
        return false;

    memcpy(buffer->data + buffer->received, decoded, decodedLength);
    buffer->received += decodedLength;
    return true;
}

bool tlsProvisionCommit()
{
    if (!certBuffer.data || !keyBuffer.data || !rootBuffer.data || certBuffer.received != certBuffer.expected ||
        keyBuffer.received != keyBuffer.expected || rootBuffer.received != rootBuffer.expected)
        return false;

    // Invalidate the provisioning marker first. Existing material is considered
    // usable only after all three new blobs have been persisted successfully.
    Preferences tlsPrefs;
    if (!tlsPrefs.begin(JARNSEN_TLS_NAMESPACE, false))
        return false;
    tlsPrefs.putUInt(READY_KEY, 0U);
    tlsPrefs.end();

    Preferences httpsPrefs;
    if (!httpsPrefs.begin(HTTPS_NAMESPACE, false))
        return false;
    const size_t keyWritten = httpsPrefs.putBytes(PRIVATE_KEY_KEY, keyBuffer.data, keyBuffer.expected);
    const size_t certWritten = httpsPrefs.putBytes(CERT_KEY, certBuffer.data, certBuffer.expected);
    httpsPrefs.end();

    if (keyWritten != keyBuffer.expected || certWritten != certBuffer.expected) {
        tlsProvisionAbort();
        return false;
    }

    if (!tlsPrefs.begin(JARNSEN_TLS_NAMESPACE, false)) {
        tlsProvisionAbort();
        return false;
    }
    const size_t rootWritten = tlsPrefs.putBytes(ROOT_CA_KEY, rootBuffer.data, rootBuffer.expected);
    if (rootWritten == rootBuffer.expected)
        tlsPrefs.putUInt(READY_KEY, READY_MAGIC);
    tlsPrefs.end();

    const bool ok = rootWritten == rootBuffer.expected;
    tlsProvisionAbort();

    TlsProvisioningInfo verify{};
    return ok && tlsProvisioningInfo(verify) && verify.ready;
}

void tlsProvisionAbort()
{
    clearAllBuffers();
}

bool tlsReadBlob(TlsBlobKind kind, uint8_t *buffer, size_t capacity, size_t &length)
{
    length = 0U;
    if (!buffer || capacity == 0U)
        return false;

    const char *name = nullptr;
    const char *space = nullptr;
    switch (kind) {
    case TlsBlobKind::CERT:
        space = HTTPS_NAMESPACE;
        name = CERT_KEY;
        break;
    case TlsBlobKind::PRIVATE_KEY:
        space = HTTPS_NAMESPACE;
        name = PRIVATE_KEY_KEY;
        break;
    case TlsBlobKind::ROOT_CA:
        space = JARNSEN_TLS_NAMESPACE;
        name = ROOT_CA_KEY;
        break;
    default:
        return false;
    }

    Preferences prefs;
    if (!prefs.begin(space, true))
        return false;
    const size_t stored = prefs.getBytesLength(name);
    if (stored == 0U || stored > capacity) {
        prefs.end();
        return false;
    }
    const size_t got = prefs.getBytes(name, buffer, capacity);
    prefs.end();
    if (got != stored)
        return false;
    length = got;
    return true;
}

} // namespace jarnsen

#else

namespace jarnsen
{
bool tlsProvisioningInfo(TlsProvisioningInfo &info)
{
    info = {};
    return true;
}
bool tlsProvisioned()
{
    return false;
}
bool tlsProvisionBegin(size_t, size_t, size_t)
{
    return false;
}
bool tlsProvisionChunk(TlsBlobKind, size_t, const char *)
{
    return false;
}
bool tlsProvisionCommit()
{
    return false;
}
void tlsProvisionAbort() {}
bool tlsReadBlob(TlsBlobKind, uint8_t *, size_t, size_t &length)
{
    length = 0U;
    return false;
}
} // namespace jarnsen

#endif
