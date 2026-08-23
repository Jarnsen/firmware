from pathlib import Path

POLICY = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
POWER = Path("src/infrastructure/HeltecV3PowerMonitor.cpp")

policy = POLICY.read_text()
power = POWER.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Service lifetime
# ---------------------------------------------------------------------------
# The OLED timeout and the service lifetime are deliberately different:
#   - OLED: 20 s after the last accepted button action.
#   - Service/BLE window: 120 s after the last accepted local/meaningful action.
#
# A separate 60 s "no BLE connection" close used to tear down the whole service
# session while the user was still navigating locally. That made a later wake
# press reopen a fresh session/page and looked like a crash. Keep the discovery
# grace constant for diagnostics/backward compatibility, but do not let it close
# the local service UI. The existing 120 s idle timer remains the authority.
old_timeout = '''        const bool connectGraceExpired =
            !v3ServiceEverConnected &&
            (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_CONNECT_GRACE_MS;
        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;
        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;
        if (connectGraceExpired || hardCapReached || idleExpired) {
            if (connectGraceExpired)
                LOG_INFO("Heltec V3 service: no BLE connection within %us; closing service",
                         (unsigned)(V3_SERVICE_CONNECT_GRACE_MS / 1000UL));
            stopV3ServiceMode();
            continue;
        }
'''
new_timeout = '''        // Do not close the complete local service UI merely because no phone
        // connected during the BLE discovery grace. The agreed user-visible
        // behavior is 20 s OLED inactivity plus a 120 s service inactivity
        // window. Local button actions and meaningful BLE bursts reset that
        // service timer; GPS/LoRa/background polling do not.
        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;
        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;
        if (hardCapReached || idleExpired) {
            stopV3ServiceMode();
            continue;
        }
'''
policy = replace_once(policy, old_timeout, new_timeout, "V3 service uses 120s idle instead of 60s no-BLE close")

# ---------------------------------------------------------------------------
# INA226 / external I2C bus ownership
# ---------------------------------------------------------------------------
# Meshtastic already initializes Wire1 on the Heltec V3 external bus
# (GPIO41/42) before the custom power monitor starts. Calling Wire1.begin()
# again produced "Bus already started" followed by ESP_ERR_INVALID_STATE in the
# user's runtime log. Reuse the board-owned bus instead of reinitializing it.
old_wire = '''bool ensureInaWire()
{
    if (inaWireReady)
        return true;
    inaWireReady = Wire1.begin(I2C_SDA1, I2C_SCL1);
    return inaWireReady;
}
'''
new_wire = '''bool ensureInaWire()
{
    if (inaWireReady)
        return true;

    // Heltec V3 board setup owns Wire1 and starts it on I2C_SDA1/I2C_SCL1
    // before this monitor is initialized. A second begin() on Arduino-ESP32
    // can invalidate the active master state. Just attach to the existing bus.
    inaWireReady = true;
    return true;
}
'''
power = replace_once(power, old_wire, new_wire, "V3 INA226 reuses initialized Wire1 bus")

# Guardrails for the two runtime regressions seen in the supplied serial log.
for needle in [
    "#define V3_SERVICE_DISPLAY_MS (20UL * 1000UL)",
    "#define V3_SERVICE_IDLE_MS (120UL * 1000UL)",
    "const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs)",
    "Heltec V3 board setup owns Wire1",
    "inaWireReady = true;",
]:
    if needle not in (policy + power):
        raise SystemExit(f"V3 runtime-log fix verification failed: {needle}")

if "(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_CONNECT_GRACE_MS" in policy:
    raise SystemExit("V3 runtime-log fix failed: 60s connect grace can still close service")
if "Wire1.begin(I2C_SDA1, I2C_SCL1)" in power:
    raise SystemExit("V3 runtime-log fix failed: INA226 still reinitializes Wire1")

POLICY.write_text(policy)
POWER.write_text(power)
print("V3 runtime log fixes ready: 20s OLED / 120s service idle + safe INA226 Wire1 reuse")
