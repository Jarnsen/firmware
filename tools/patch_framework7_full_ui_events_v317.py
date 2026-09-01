"""Make the complete Framework7 desktop surface independent from bubbling clicks.

Physical Windows/WebView2 testing showed that not only Service/Recovery but also
Live, Activity and other controls can become unclickable while the backend stays
healthy. app-v31.js historically routes nearly every dynamic control through one
document-level bubbling click listener. Framework7 owns that event pipeline and
can consume events before they reach the handler.

Install one capture-phase router at document level. It runs before Framework7,
handles every first-party control family, and stops propagation so the historical
bubbling listener is only a fallback. Static top-bar buttons are also handled in
capture phase. Dynamic controls remain safe after innerHTML rerenders because the
router delegates by data attributes.
"""
from __future__ import annotations

import pathlib
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_full_ui_events_v317.py <app-v31.js>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "jarnsenCaptureUiClick" in text:
        print("Framework7 full UI capture routing v3.17 already installed")
        return 0

    anchor = "  document.addEventListener('click', event => {\n"
    router = r'''  function jarnsenCaptureUiClick(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const handled = () => {
      event.preventDefault();
      event.stopPropagation();
    };

    // Top bar: own these before Framework7 can consume the click.
    if (target.closest('#scanBleButton')) { handled(); apiAction('scan_ble'); return; }
    if (target.closest('#activityButton')) { handled(); renderActivity(); activitySheet.open(); return; }
    if (target.closest('#themeButton')) { handled(); toggleTheme(); return; }

    const nav = target.closest('[data-view]');
    if (nav) { handled(); setView(nav.dataset.view); return; }
    const nav2 = target.closest('[data-nav]');
    if (nav2) { handled(); setView(nav2.dataset.nav); return; }
    const filter = target.closest('[data-filter]');
    if (filter) { handled(); state.filter = filter.dataset.filter; renderOverview(); return; }

    const profileSlot = target.closest('[data-profile-slot]');
    if (profileSlot) { handled(); state.profileSlot = Number(profileSlot.dataset.profileSlot); renderService(); return; }
    const profileSection = target.closest('[data-profile-section]');
    if (profileSection) { handled(); openProfileSectionEditor(Number(profileSection.dataset.slot), profileSection.dataset.kind, profileSection.dataset.name); return; }
    const profileActionButton = target.closest('[data-profile-action]');
    if (profileActionButton) { handled(); profileAction(profileActionButton); return; }

    const liveActionButton = target.closest('[data-live-action]');
    if (liveActionButton) { handled(); liveAction(liveActionButton.dataset.liveAction); return; }
    const liveControlButton = target.closest('[data-live-control]');
    if (liveControlButton) { handled(); liveAction('command', { control: liveControlButton.dataset.liveControl }); return; }

    const pageAction = target.closest('[data-page-action]');
    if (pageAction) {
      handled();
      const actionName = pageAction.dataset.pageAction;
      if (actionName === 'refresh') fetchState();
      if (actionName === 'select-visible') { filteredNodes().forEach(node => state.selectedSet.add(node.node_id)); renderOverview(); }
      if (actionName === 'firmware-check') apiAction('firmware_check');
      if (actionName === 'theme') toggleTheme();
      if (actionName === 'profiles-refresh') { state.profiles = null; renderService(); }
      return;
    }

    const bulk = target.closest('[data-bulk]');
    if (bulk) {
      handled();
      const ids = [...state.selectedSet];
      if (!ids.length) { toast('Keine Nodes ausgewählt'); return; }
      if (bulk.dataset.bulk === 'delete') confirmDelete(ids); else apiAction(bulk.dataset.bulk, ids);
      return;
    }

    const actionButton = target.closest('[data-action]');
    if (actionButton) {
      handled();
      const id = actionButton.dataset.node;
      const kind = actionButton.dataset.action;
      if (kind === 'select') { state.selectedSet.has(id) ? state.selectedSet.delete(id) : state.selectedSet.add(id); renderOverview(); return; }
      if (kind === 'inspect') { state.selected = id; renderInspector(); if (state.view !== 'overview') renderPage(); return; }
      if (kind === 'menu') { const node = getNode(id); if (node) openNodeMenu(node); return; }
      if (kind === 'log') apiAction('download_log', [id]);
      if (kind === 'ota') apiAction('ota', [id]);
      if (kind === 'wake') apiAction('wake', [id]);
      if (kind === 'live-view') { state.selected = id; setView('live'); }
      return;
    }

    if (target.closest('[data-inspector-close]')) { handled(); state.selected = null; renderInspector(); return; }
  }

  // Capture phase is the primary input path on Windows/WebView2. It runs before
  // Framework7's bubbling handlers and therefore cannot be swallowed by them.
  document.addEventListener('click', jarnsenCaptureUiClick, true);

'''
    text = replace_once(text, anchor, router + anchor, "capture UI router insertion")

    # Prevent duplicate actions from legacy direct top-bar listeners. Capture routing
    # now owns them; retaining listeners would fire twice if propagation semantics
    # differ between WebView2 builds.
    old = "  document.getElementById('scanBleButton').addEventListener('click', () => apiAction('scan_ble'));\n  document.getElementById('activityButton').addEventListener('click', () => { renderActivity(); activitySheet.open(); });\n  document.getElementById('themeButton').addEventListener('click', toggleTheme);\n"
    new = "  // Top-bar click actions are handled by jarnsenCaptureUiClick in capture phase.\n"
    text = replace_once(text, old, new, "top-bar duplicate listener removal")

    path.write_text(text, encoding="utf-8")
    print("Framework7 full UI capture routing v3.17 installed: all first-party clicks precede Framework7")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
