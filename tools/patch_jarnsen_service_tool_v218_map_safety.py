"""v2.1.8: avoid tkintermapview delete_all_marker/delete_all_path index errors."""
from __future__ import annotations

import sys
from pathlib import Path

APP_VERSION = "2.1.8"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    if "    def _clear_online_map_objects(self)" not in source:
        helper = r'''    def _clear_online_map_objects(self) -> None:
        """Delete map markers/paths from a stable snapshot.

        tkintermapview 1.30 mutates its internal marker/path lists from each
        object's delete() method. Its delete_all_* helpers iterate those same
        lists by numeric index and can therefore raise IndexError when several
        objects exist. Iterate a snapshot instead and clear any stale residue.
        """
        if not hasattr(self, "online_map"):
            return
        marker_list = list(getattr(self.online_map, "canvas_marker_list", []) or [])
        path_list = list(getattr(self.online_map, "canvas_path_list", []) or [])
        for marker in marker_list:
            with contextlib.suppress(Exception):
                marker.delete()
        for path in path_list:
            with contextlib.suppress(Exception):
                path.delete()
        with contextlib.suppress(Exception):
            getattr(self.online_map, "canvas_marker_list", []).clear()
        with contextlib.suppress(Exception):
            getattr(self.online_map, "canvas_path_list", []).clear()
        tool_log(
            "MAP_CLEAR_SAFE_V218",
            markers=len(marker_list),
            paths=len(path_list),
        )
'''
        source = insert_before_method(source, "sync_online_map", helper)

    def patch_sync(method: str) -> str:
        old = '''        self.online_map.delete_all_marker()\n        self.online_map.delete_all_path()\n'''
        new = '''        self._clear_online_map_objects()\n'''
        if old not in method:
            raise SystemExit("v2.1.8 safe-map clear anchor not found")
        return method.replace(old, new, 1)

    source = replace_method(source, "sync_online_map", patch_sync)

    required = (
        "def _clear_online_map_objects(self)",
        "MAP_CLEAR_SAFE_V218",
        "self._clear_online_map_objects()",
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.1.8 safe-map validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v218_map_safety.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    patched = patch(source)
    path.write_text(patched, encoding="utf-8")
    print(f"Added safe map clearing to {path} for v{APP_VERSION}")


if __name__ == "__main__":
    main()
