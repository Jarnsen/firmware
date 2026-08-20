Import("env")

from pathlib import Path

if env["PIOENV"] == "heltec-v3":
    path = Path(env["PROJECT_DIR"]) / "src" / "infrastructure" / "HeltecV3RepeaterPolicy.cpp"
    text = path.read_text(encoding="utf-8")

    marker = "V3_SERVICE_PACKET_LIMIT"
    if marker not in text:
        replacements = [
            (
                "#ifndef V3_SERVICE_MAX_MS\n#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n",
                "#ifndef V3_SERVICE_MAX_MS\n#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n"
                "#ifndef V3_SERVICE_PACKET_LIMIT\n#define V3_SERVICE_PACKET_LIMIT 20U\n#endif\n",
            ),
            (
                "#define V3_POSITION_FRESH_SECS 60UL",
                "#define V3_POSITION_FRESH_SECS 180UL",
            ),
            (
                "static char v3ServiceBanner[160];\n",
                "static char v3ServiceBanner[160];\n"
                "static uint32_t v3ServicePacketCount = 0;\n"
                "static uint32_t v3ServiceLastFromNum = 0;\n"
                "static bool v3ServiceHaveFromNum = false;\n"
                "static bool v3FromNumObserverInstalled = false;\n",
            ),
            (
                "        if (!isFromUs(&mp) || mp.transport_mechanism != meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API)\n"
                "            return false;\n",
                "        // Phone position packets arrive through PhoneAPI as TRANSPORT_INTERNAL with from=0\n"
                "        // on this firmware. Also accept TRANSPORT_API for compatibility with other clients.\n"
                "        const bool phoneTransport =\n"
                "            mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API ||\n"
                "            (mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_INTERNAL && mp.from == 0);\n"
                "        const bool phoneSource = isFromUs(&mp) || mp.from == 0;\n"
                "        if (!phoneSource || !phoneTransport)\n"
                "            return false;\n",
            ),
            (
                "        snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), \"V3 SERVICE\\n%s  BAT %u%%\\nSHORT: NEXT\\nBT %us\", role, battery, remaining);",
                "        snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), \"V3 SERVICE\\n%s BAT %u%%\\nBT %us P%u/%u\\nSHORT: NEXT\",\n"
                "                 role, battery, remaining, (unsigned)v3ServicePacketCount, (unsigned)V3_SERVICE_PACKET_LIMIT);",
            ),
            (
                "        v3DisplayVisible = false;\n        v3LastFrameAssertMs = 0;\n        v3ResetAutoConfirmation();\n",
                "        v3DisplayVisible = false;\n        v3LastFrameAssertMs = 0;\n"
                "        v3ServicePacketCount = 0;\n        v3ServiceHaveFromNum = false;\n"
                "        v3ResetAutoConfirmation();\n",
            ),
            (
                "class V3LightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>\n",
                "class V3FromNumObserver : public Observer<uint32_t>\n"
                "{\n"
                "  protected:\n"
                "    int onNotify(uint32_t newValue) override\n"
                "    {\n"
                "        if (!v3RepeaterRoleEnabled() || !v3ServiceActive)\n"
                "            return 0;\n"
                "        if (!v3ServiceHaveFromNum) {\n"
                "            v3ServiceLastFromNum = newValue;\n"
                "            v3ServiceHaveFromNum = true;\n"
                "            return 0;\n"
                "        }\n"
                "        uint32_t delta = newValue - v3ServiceLastFromNum;\n"
                "        v3ServiceLastFromNum = newValue;\n"
                "        if (delta > V3_SERVICE_PACKET_LIMIT)\n"
                "            delta = V3_SERVICE_PACKET_LIMIT;\n"
                "        v3ServicePacketCount += delta;\n"
                "        if (v3ServiceTaskHandle)\n"
                "            xTaskNotifyGive(v3ServiceTaskHandle);\n"
                "        return 0;\n"
                "    }\n"
                "};\n\n"
                "static V3FromNumObserver v3FromNumObserver;\n\n"
                "class V3LightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>\n",
            ),
            (
                "        if (v3BleConnected())\n            v3ServiceLastActivityMs = now;\n\n",
                "        // A connected phone, client heartbeat, GPS update, or background packet must not\n"
                "        // extend the service timer. Only GPIO0 interaction refreshes v3ServiceLastActivityMs.\n\n",
            ),
            (
                "        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n"
                "        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;\n"
                "        if (hardCapReached || idleExpired) {\n"
                "            stopV3ServiceMode();\n"
                "            continue;\n"
                "        }\n",
                "        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n"
                "        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;\n"
                "        const bool packetLimitReached = v3ServicePacketCount >= (uint32_t)V3_SERVICE_PACKET_LIMIT;\n"
                "        if (hardCapReached || idleExpired || packetLimitReached) {\n"
                "            if (packetLimitReached)\n"
                "                LOG_INFO(\"Heltec V3 service: BLE packet budget reached (%u/%u); closing service\",\n"
                "                         (unsigned)v3ServicePacketCount, (unsigned)V3_SERVICE_PACKET_LIMIT);\n"
                "            stopV3ServiceMode();\n"
                "            continue;\n"
                "        }\n",
            ),
            (
                "    setupV3ServiceButton();\n\n    LOG_INFO(\"Heltec V3 %s duty:",
                "    setupV3ServiceButton();\n"
                "    if (service && !v3FromNumObserverInstalled) {\n"
                "        v3FromNumObserver.observe(&service->fromNumChanged);\n"
                "        v3FromNumObserverInstalled = true;\n"
                "    }\n\n    LOG_INFO(\"Heltec V3 %s duty:",
            ),
        ]

        for old, new in replacements:
            if old not in text:
                raise RuntimeError("Heltec V3 runtime patch anchor not found: %r" % old[:100])
            text = text.replace(old, new, 1)

        path.write_text(text, encoding="utf-8")
        print("Applied Heltec V3 runtime policy patch: phone GPS + 20-packet BLE budget + strict 120s idle")
    else:
        print("Heltec V3 runtime policy patch already applied")
