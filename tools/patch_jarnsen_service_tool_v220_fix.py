"""Compatibility wrapper for the v2.2.0 macOS-style shell.

The workflow UI from v2.0+ already exposes the live workspace, body pane and
advanced-controls pane at runtime. Feed v2.2.0 harmless source anchors so the
migration patch no longer depends on how an old UI patch constructed those
panes, then resolve the real widgets dynamically before installing the new shell.
"""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v220 as v220


def patch(source: str) -> str:
    build_start, build_end = v220.method_span(source, "_build_ui")
    build = source[build_start:build_end]

    controls_anchor = (
        '        controls = ttk.Frame(body, padding=(0, 0, 12, 0), width=365)\n'
        '        body.add(controls, weight=0)\n'
    )
    workspace_anchor = (
        '        workspace = ttk.Frame(body)\n'
        '        body.add(workspace, weight=1)\n'
    )
    missing_parts: list[str] = []
    if controls_anchor not in build:
        missing_parts.append(controls_anchor.rstrip("\n"))
    if workspace_anchor not in build:
        missing_parts.append(workspace_anchor.rstrip("\n"))
    if missing_parts:
        marker = "        self.render_dashboard()\n"
        if marker not in build:
            raise SystemExit("v2.2.0 compatibility: _build_ui insertion point not found")
        literal_lines = ["        _v220_source_anchor_compat = r\"\"\""]
        literal_lines.extend(missing_parts)
        literal_lines.append("        \"\"\"")
        literal_lines.append("        _ = _v220_source_anchor_compat")
        compat = "\n".join(literal_lines) + "\n"
        build = build.replace(marker, compat + marker, 1)
        source = source[:build_start] + build + source[build_end:]

    result = v220.patch(source)

    helper = r'''    def _prepare_mac_shell_v220_compat(self) -> None:
        workspace = self.notebook.master
        body = getattr(self, "body_pane", None)
        if body is None:
            body = workspace.master
        controls = getattr(self, "controls_host", None)
        if controls is None:
            try:
                candidates = [self.nametowidget(str(name)) for name in body.panes()]
                controls = next((widget for widget in candidates if widget is not workspace), None)
            except (tk.TclError, AttributeError, StopIteration):
                controls = None
        self.workspace_v220 = workspace
        self.main_pane_v220 = body
        self.legacy_controls_v220 = controls
        self._install_mac_shell_v220()
'''
    install_start, _install_end = v220.method_span(result, "_install_mac_shell_v220")
    if "def _prepare_mac_shell_v220_compat" not in result:
        result = result[:install_start] + helper.rstrip() + "\n\n" + result[install_start:]
    result = result.replace(
        "        self.after(420, self._install_mac_shell_v220)\n",
        "        self.after(420, self._prepare_mac_shell_v220_compat)\n",
        1,
    )
    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v220_fix.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied v2.2.0 dynamic pane compatibility wrapper")


if __name__ == "__main__":
    main()
