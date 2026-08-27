"""Fix v2.1 decorator boundary when extending on_node_selected."""
from __future__ import annotations

import sys
from pathlib import Path


def patch(source: str) -> str:
    broken = '''    @staticmethod\n        if hasattr(self, "all_nodes_tree"):\n            self.refresh_all_nodes_overview()\n\n    def history_comparison'''
    fixed = '''        if hasattr(self, "all_nodes_tree"):\n            self.refresh_all_nodes_overview()\n\n    @staticmethod\n    def history_comparison'''
    if broken in source:
        source = source.replace(broken, fixed, 1)
    elif fixed not in source:
        raise SystemExit("v2.1 on_node_selected decorator boundary not found")

    required = (
        '        if hasattr(self, "all_nodes_tree"):\n            self.refresh_all_nodes_overview()\n\n    @staticmethod\n    def history_comparison',
        'APP_VERSION = "2.1.0"',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1 fix marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.0 fix: all-node refresh kept inside node-selection method")


if __name__ == "__main__":
    main()
