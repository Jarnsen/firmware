from pathlib import Path

SERVICE = Path("src/infrastructure/HeltecV3ServicePage.cpp")
service = SERVICE.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Mesh Health and Antenna Test already have first-class carousel pages directly
# after Service. Keeping links to those same pages in the Service picker added a
# slower second route with no extra function. Keep the picker for deeper service
# functions only: Power Statistics and Diagnostic Log.
old_root = '''    case V3ServiceMenu::ROOT: {
        // Previous verified root signature retained as a migration breadcrumb:
        // static const char *options[] = {"Back", "Mesh Health", "Antenna Test", "Diagnostic Log"};
        static const char *options[] = {"Back", "Mesh Health", "Antenna Test", "Power Statistics", "Diagnostic Log"};
        showOptions("V3 Service", options, 5, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueAction(V3MenuAction::NAV_MESH); break;
            case 2: queueAction(V3MenuAction::NAV_ANTENNA); break;
            case 3: queueMenu(V3ServiceMenu::POWER_STATS); break;
            case 4: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            default: break;
            }
        });
        break;
    }
'''
new_root = '''    case V3ServiceMenu::ROOT: {
        static const char *options[] = {"Back", "Power Statistics", "Diagnostic Log"};
        showOptions("V3 Service", options, 3, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueMenu(V3ServiceMenu::POWER_STATS); break;
            case 2: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            default: break;
            }
        });
        break;
    }
'''
service = replace_once(service, old_root, new_root, "deduplicate V3 service root")

# Remove now-unreachable navigation actions as well, so there is only one route
# to Mesh Health/Antenna Test: the normal page carousel.
service = replace_once(
    service,
    'enum class V3MenuAction : uint8_t { NONE = 0, CLOSE, NAV_MESH, NAV_ANTENNA, EXPORT_LOG, CLEAR_LOG };',
    'enum class V3MenuAction : uint8_t { NONE = 0, CLOSE, EXPORT_LOG, CLEAR_LOG };',
    "remove duplicate page navigation actions",
)

navigate_block = '''void navigateFromService(unsigned pagesForward)
{
    closeMenuInternal(false);
    if (!screen)
        return;
    for (unsigned i = 0; i < pagesForward; ++i)
        screen->showNextFrame();
    screen->runNow();
}

'''
if navigate_block in service:
    service = service.replace(navigate_block, '', 1)
    print("remove duplicate page navigation helper: applied")
else:
    print("remove duplicate page navigation helper: already absent")

nav_cases = '''    case V3MenuAction::NAV_MESH:
        // Local page order is Position -> Service -> Mesh Health -> Antenna Test.
        navigateFromService(1);
        break;
    case V3MenuAction::NAV_ANTENNA:
        navigateFromService(2);
        break;
'''
if nav_cases in service:
    service = service.replace(nav_cases, '', 1)
    print("remove duplicate page navigation cases: applied")
else:
    print("remove duplicate page navigation cases: already absent")

for needle in [
    'static const char *options[] = {"Back", "Power Statistics", "Diagnostic Log"}',
    'V3ServiceMenu::POWER_STATS',
    'V3ServiceMenu::DIAG_LOG',
    'showOptions("Power Statistics"',
    'showOptions("Diagnostic Log"',
]:
    if needle not in service:
        raise SystemExit(f"V3 service dedupe verification failed: {needle}")

for forbidden in ['V3MenuAction::NAV_MESH', 'V3MenuAction::NAV_ANTENNA', 'navigateFromService(']:
    if forbidden in service:
        raise SystemExit(f"V3 service dedupe verification failed: duplicate route remains: {forbidden}")

SERVICE.write_text(service)
print("V3 service menu simplified: Back + Power Statistics + Diagnostic Log; Mesh Health/Antenna stay normal pages")
