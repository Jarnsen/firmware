"""Enable the common JARNSEN WLAN service on LILYGO T-Beam Supreme.

The Supreme already advertises Wi-Fi in the Unified-Core hardware profile and
already has a dedicated NodeServiceDescriptor. This transform closes the
remaining runtime gaps without creating a board fork:

- select the Supreme service descriptor in the common service platform;
- compile the common JARNSEN Service Web implementation for Supreme;
- expose WLAN SERVICE through the shared local menu used by non-Tracker boards;
- protect WLAN start/stop and password display with the common five-minute
  JARNSEN menu authorization session;
- pump the temporary SoftAP in a small shared service thread so Full Lock,
  portal requests and the existing idle timeout continue to work after the
  display goes dark.

The menu adapter stays capability-driven, so Wio L1 never exposes WLAN while
other Wi-Fi-capable shared-display boards use the same behavior.
"""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Common hardware/service descriptor selection.
# ---------------------------------------------------------------------------
PLATFORM = Path("src/jarnsen/hardware/JarnsenServicePlatform.h")
platform = PLATFORM.read_text(encoding="utf-8")
if "JARNSEN_TBEAM_SUPREME_SERVICE_PLATFORM" not in platform:
    platform = replace_once(
        platform,
        "#elif defined(_VARIANT_HELTEC_V4)\n    return heltecV4ServiceDescriptor();\n#else\n",
        "#elif defined(_VARIANT_HELTEC_V4)\n    return heltecV4ServiceDescriptor();\n"
        "#elif defined(LILYGO_TBEAM_S3_CORE)\n"
        "    // JARNSEN_TBEAM_SUPREME_SERVICE_PLATFORM\n"
        "    return lilygoTBeamSupremeServiceDescriptor();\n"
        "#else\n",
        "Supreme service descriptor selector",
    )
PLATFORM.write_text(platform, encoding="utf-8")


# ---------------------------------------------------------------------------
# Compile the existing ESP32 JARNSEN Service Web transport for Supreme.
# ---------------------------------------------------------------------------
OLD_GUARD = (
    "#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(_VARIANT_HELTEC_V4) || "
    "defined(HELTEC_TRACKER_V1_1))"
)
NEW_GUARD = (
    "#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(_VARIANT_HELTEC_V4) || "
    "defined(HELTEC_TRACKER_V1_1) || defined(LILYGO_TBEAM_S3_CORE))"
)
for web_path in (Path("src/mesh/http/JarnsenServiceWeb.h"), Path("src/mesh/http/JarnsenServiceWeb.cpp")):
    web = web_path.read_text(encoding="utf-8")
    if "defined(LILYGO_TBEAM_S3_CORE)" not in web.splitlines()[2:8]:
        web = replace_once(web, OLD_GUARD, NEW_GUARD, f"Supreme WLAN compile guard in {web_path}")
    web_path.write_text(web, encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared OLED menu/runtime used by V3/V4/Wio/T-Beam/T-Beam Supreme.
# The shared menu-PIN transform must run first so requireMenuAuthorization()
# exists and WLAN mutations inherit the already-agreed five-minute policy.
# ---------------------------------------------------------------------------
COMMON = Path("src/jarnsen/adapters/JarnsenDisplayRuntime.cpp")
common = COMMON.read_text(encoding="utf-8")
MARKER = "JARNSEN_SHARED_WLAN_SERVICE_MENU_V1"
if MARKER not in common:
    if "JARNSEN_SHARED_MENU_PIN_AUTH_V1" not in common:
        raise SystemExit("Shared menu PIN transform must run before Supreme WLAN transform")

    include_anchor = '#include "jarnsen/core/service/JarnsenMenuAuthorization.h"\n'
    common = replace_once(
        common,
        include_anchor,
        include_anchor
        + '#include "jarnsen/core/service/JarnsenServiceSecurity.h"\n'
        + '#include "jarnsen/hardware/JarnsenHardwareProfiles.h"\n'
        + '#include "mesh/http/JarnsenServiceWeb.h"\n'
        + '#include "concurrency/OSThread.h"\n',
        "Shared WLAN includes",
    )

    common = replace_once(
        common,
        "enum class MenuView : uint8_t {\n    NONE = 0,\n    ROOT,\n    PROFILE,\n    SYSTEM,\n};\n",
        "enum class MenuView : uint8_t {\n    NONE = 0,\n    ROOT,\n    PROFILE,\n    SERVICE,\n    WLAN_SERVICE,\n    SYSTEM,\n};\n",
        "Shared WLAN menu views",
    )

    state_anchor = "const char *profileError = nullptr;\n"
    state_block = r'''const char *profileError = nullptr;

// JARNSEN_SHARED_WLAN_SERVICE_MENU_V1
constexpr auto sharedHardwareProfile = jarnsen::currentHardwareRoleProfile();
constexpr bool sharedHasWlanService = sharedHardwareProfile.hardware.capabilities.wifi;
bool wlanPasswordVisible = false;
bool wlanLastActionFailed = false;

class JarnsenSharedServicePump final : public concurrency::OSThread
{
  public:
    JarnsenSharedServicePump() : concurrency::OSThread("JarnsenService") {}

  protected:
    int32_t runOnce() override
    {
        jarnsenServiceWebPump();
        jarnsen::serviceSecurityPump();
        return jarnsenServiceWebActive() ? 20 : 500;
    }
};

JarnsenSharedServicePump *sharedServicePump = nullptr;

void ensureSharedServicePump()
{
    if (!sharedServicePump)
        sharedServicePump = new JarnsenSharedServicePump();
}
'''
    common = replace_once(common, state_anchor, state_block, "Shared WLAN state/service pump")

    old_count = '''uint8_t menuCount()\n{\n    if (menuView == MenuView::PROFILE)\n        return 4U;\n    return menuView == MenuView::SYSTEM ? 3U : 6U;\n}\n'''
    new_count = '''uint8_t menuCount()\n{\n    if (menuView == MenuView::PROFILE)\n        return 4U;\n    if (menuView == MenuView::SERVICE)\n        return sharedHasWlanService ? 2U : 1U;\n    if (menuView == MenuView::WLAN_SERVICE)\n        return 6U;\n    return menuView == MenuView::SYSTEM ? 3U : 6U;\n}\n'''
    common = replace_once(common, old_count, new_count, "Shared WLAN menu count")

    label_anchor = '''const char *menuLabel(uint8_t index)\n{\n    if (menuView == MenuView::PROFILE) {\n'''
    label_block = '''const char *menuLabel(uint8_t index)\n{\n    if (menuView == MenuView::SERVICE) {\n        if (sharedHasWlanService && index == 0U)\n            return "WLAN SERVICE";\n        return "ZURUECK";\n    }\n    if (menuView == MenuView::WLAN_SERVICE) {\n        switch (index % 6U) {\n        case 0: return jarnsenServiceWebActive() ? "WLAN BEENDEN" : "WLAN STARTEN";\n        case 1: return "STATUS";\n        case 2: return "SSID";\n        case 3: return "PASSWORT";\n        case 4: return "IP";\n        default: return "ZURUECK";\n        }\n    }\n    if (menuView == MenuView::PROFILE) {\n'''
    common = replace_once(common, label_anchor, label_block, "Shared WLAN menu labels")

    header_anchor = '''    const char *header = menuView == MenuView::PROFILE ? "FUNKPROFIL" : (menuView == MenuView::SYSTEM ? "SYSTEM MENUE" : "MENUE");\n'''
    header_block = '''    const char *header = menuView == MenuView::PROFILE\n                             ? "FUNKPROFIL"\n                             : menuView == MenuView::SERVICE\n                                   ? "SERVICE"\n                                   : menuView == MenuView::WLAN_SERVICE\n                                         ? "WLAN SERVICE"\n                                         : (menuView == MenuView::SYSTEM ? "SYSTEM MENUE" : "MENUE");\n'''
    common = replace_once(common, header_anchor, header_block, "Shared WLAN menu header")

    bottom_anchor = '''    if (menuView == MenuView::PROFILE && profileError)\n        std::snprintf(next, sizeof(next), "%s", profileError);\n    else if (menuView == MenuView::PROFILE)\n        std::snprintf(next, sizeof(next), "aktiv: %s", jarnsen::radioProfileLabel(jarnsen::radioProfileActive()));\n    else\n        std::snprintf(next, sizeof(next), "danach: %s", menuLabel((menuSelection + 1U) % count));\n'''
    bottom_block = '''    if (menuView == MenuView::PROFILE && profileError)\n        std::snprintf(next, sizeof(next), "%s", profileError);\n    else if (menuView == MenuView::PROFILE)\n        std::snprintf(next, sizeof(next), "aktiv: %s", jarnsen::radioProfileLabel(jarnsen::radioProfileActive()));\n    else if (menuView == MenuView::WLAN_SERVICE) {\n        switch (menuSelection % 6U) {\n        case 0:\n            if (wlanLastActionFailed)\n                std::snprintf(next, sizeof(next), "%s", jarnsenServiceWebLastError());\n            else\n                std::snprintf(next, sizeof(next), "Status: %s", jarnsenServiceWebActive() ? "AKTIV" : "AUS");\n            break;\n        case 1:\n            std::snprintf(next, sizeof(next), "%s", jarnsenServiceWebActive() ? "AKTIV" : "AUS");\n            break;\n        case 2:\n            std::snprintf(next, sizeof(next), "%s", jarnsenServiceWebSsid());\n            break;\n        case 3:\n            std::snprintf(next, sizeof(next), "%s",\n                          wlanPasswordVisible && jarnsen::menuAuthorizationValid() ? jarnsenServiceWebPassword() : "PIN GESCHUETZT");\n            break;\n        case 4:\n            std::snprintf(next, sizeof(next), "%s", jarnsenServiceWebAddress());\n            break;\n        default:\n            std::snprintf(next, sizeof(next), "SERVICE MENUE");\n            break;\n        }\n    } else\n        std::snprintf(next, sizeof(next), "danach: %s", menuLabel((menuSelection + 1U) % count));\n'''
    common = replace_once(common, bottom_anchor, bottom_block, "Shared WLAN menu details")

    step_anchor = '''    if (menuPinMode) {\n        menuPinStep(next);\n        return true;\n    }\n    if (menuView != MenuView::NONE) {\n        const uint8_t count = menuCount();\n'''
    step_block = '''    if (menuPinMode) {\n        menuPinStep(next);\n        return true;\n    }\n    if (menuView != MenuView::NONE) {\n        if (menuView == MenuView::WLAN_SERVICE)\n            wlanPasswordVisible = false;\n        const uint8_t count = menuCount();\n'''
    common = replace_once(common, step_anchor, step_block, "Hide WLAN password on navigation")

    service_root_anchor = '''        case jarnsen::MainMenuItem::SERVICE:\n            closeMenuTo(DisplayPage::SERVICE);\n            return true;\n'''
    service_root_block = '''        case jarnsen::MainMenuItem::SERVICE:\n            menuView = MenuView::SERVICE;\n            menuSelection = 0;\n            wlanPasswordVisible = false;\n            wlanLastActionFailed = false;\n            redraw();\n            return true;\n'''
    common = replace_once(common, service_root_anchor, service_root_block, "Open shared SERVICE menu")

    profile_anchor = '''    if (menuView == MenuView::PROFILE) {\n        if (menuSelection < 3U) {\n'''
    service_handlers = '''    if (menuView == MenuView::SERVICE) {\n        if (sharedHasWlanService && menuSelection == 0U) {\n            menuView = MenuView::WLAN_SERVICE;\n            menuSelection = 0;\n            wlanPasswordVisible = false;\n            wlanLastActionFailed = false;\n            redraw();\n        } else {\n            menuView = MenuView::ROOT;\n            menuSelection = 0;\n            redraw();\n        }\n        return true;\n    }\n\n    if (menuView == MenuView::WLAN_SERVICE) {\n        switch (menuSelection % 6U) {\n        case 0:\n            if (!requireMenuAuthorization())\n                return true;\n            ensureSharedServicePump();\n            if (jarnsenServiceWebActive()) {\n                jarnsenServiceWebStop();\n                wlanLastActionFailed = false;\n            } else {\n                wlanLastActionFailed = !jarnsenServiceWebStart();\n            }\n            wlanPasswordVisible = false;\n            redraw();\n            return true;\n        case 3:\n            if (!requireMenuAuthorization())\n                return true;\n            wlanPasswordVisible = true;\n            redraw();\n            return true;\n        case 5:\n            wlanPasswordVisible = false;\n            menuView = MenuView::SERVICE;\n            menuSelection = 0;\n            redraw();\n            return true;\n        default:\n            wlanPasswordVisible = false;\n            redraw();\n            return true;\n        }\n    }\n\n    if (menuView == MenuView::PROFILE) {\n        if (menuSelection < 3U) {\n'''
    common = replace_once(common, profile_anchor, service_handlers, "Shared WLAN select handlers")

    back_anchor = '''    if (menuView == MenuView::SYSTEM || menuView == MenuView::PROFILE) {\n        menuView = MenuView::ROOT;\n        menuSelection = 0;\n        profileError = nullptr;\n        redraw();\n        return true;\n    }\n'''
    back_block = '''    if (menuView == MenuView::WLAN_SERVICE) {\n        wlanPasswordVisible = false;\n        menuView = MenuView::SERVICE;\n        menuSelection = 0;\n        redraw();\n        return true;\n    }\n    if (menuView == MenuView::SYSTEM || menuView == MenuView::PROFILE || menuView == MenuView::SERVICE) {\n        wlanPasswordVisible = false;\n        menuView = MenuView::ROOT;\n        menuSelection = 0;\n        profileError = nullptr;\n        redraw();\n        return true;\n    }\n'''
    common = replace_once(common, back_anchor, back_block, "Shared WLAN back navigation")

COMMON.write_text(common, encoding="utf-8")


# ---------------------------------------------------------------------------
# Contract: Supreme must be recognized as Wi-Fi capable and the transform must
# leave all required runtime hooks present.
# ---------------------------------------------------------------------------
for path, required in (
    (PLATFORM, "JARNSEN_TBEAM_SUPREME_SERVICE_PLATFORM"),
    (Path("src/mesh/http/JarnsenServiceWeb.h"), "defined(LILYGO_TBEAM_S3_CORE)"),
    (Path("src/mesh/http/JarnsenServiceWeb.cpp"), "defined(LILYGO_TBEAM_S3_CORE)"),
    (COMMON, MARKER),
    (COMMON, "ensureSharedServicePump"),
    (COMMON, "requireMenuAuthorization"),
    (COMMON, "jarnsenServiceWebStart"),
    (COMMON, "jarnsenServiceWebStop"),
    (COMMON, "jarnsenServiceWebPump"),
):
    text = path.read_text(encoding="utf-8")
    if required not in text:
        raise SystemExit(f"Supreme WLAN validation failed for {path}: {required}")
