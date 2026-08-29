"""Compatibility wrapper for the v2.1.32 tile dashboard on top of v2.1.24+ UI.

v2.1.24 changed the legacy all-node Treeview from pack() to grid() inside an
all_tree frame and added scrollbars. v2.1.32 intentionally keeps that Treeview
only as a hidden compatibility data surface while the visible first page uses
cards. Normalize the old geometry anchor before delegating to v2.1.32, then
hide the complete legacy frame so no pack/grid conflict or empty space remains.
"""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v2132 as v2132


def patch(source: str) -> str:
    grid_anchor = '        self.all_nodes_tree.grid(row=0, column=0, sticky="nsew")\n'
    pack_anchor = '        self.all_nodes_tree.pack(fill="both", expand=True)\n'
    converted = False
    if pack_anchor not in source and grid_anchor in source:
        source = source.replace(grid_anchor, pack_anchor, 1)
        converted = True

    result = v2132.patch(source)

    if converted:
        scrollbar_block = '''        all_tree_scroll_y = ttk.Scrollbar(all_tree, orient="vertical", command=self.all_nodes_tree.yview)\n        all_tree_scroll_y.grid(row=0, column=1, sticky="ns")\n        all_tree_scroll_x = ttk.Scrollbar(all_tree, orient="horizontal", command=self.all_nodes_tree.xview)\n        all_tree_scroll_x.grid(row=1, column=0, sticky="ew")\n        self.all_nodes_tree.configure(yscrollcommand=all_tree_scroll_y.set, xscrollcommand=all_tree_scroll_x.set)\n'''
        if scrollbar_block not in result:
            raise SystemExit("v2.1.32 compatibility: legacy scrollbar block not found")
        result = result.replace(scrollbar_block, '        all_tree.pack_forget()\n', 1)

    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2132_fix.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied v2.1.32 compatibility fix for v2.1.24 all-node grid layout")


if __name__ == "__main__":
    main()
