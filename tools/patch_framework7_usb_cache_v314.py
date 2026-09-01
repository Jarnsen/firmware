"""Keep Windows USB/COM discovery off Framework7 API request threads.

The UI polls /api/state and /api/service-status frequently. A physical COM device
can make serial enumeration slow or block transiently. Never perform that work in
a request thread: return the most recent cache immediately and refresh it on one
background worker at a controlled cadence.
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
        print("usage: patch_framework7_usb_cache_v314.py <legacy-compat.py>", file=sys.stderr)
        return 2

    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "_framework7_usb_refresh_worker" in text:
        print("Framework7 USB cache v3.14 already installed")
        return 0

    text = replace_once(
        text,
        "import contextlib\nfrom typing import Any\n",
        "import contextlib\nimport threading\nimport time\nfrom typing import Any\n",
        "USB cache imports",
    )

    start = """    def _usb_targets(self: Any) -> list[dict[str, Any]]:\n        candidates: list[Any] = []\n        try:\n            candidates = list(self.tool._auto_usb_log_candidates())\n        except Exception as exc:\n            _diag(f\"USB candidate scan exception {type(exc).__name__}: {exc}\")\n            return []\n\n        result: list[dict[str, Any]] = []\n"""
    replacement = """    def _framework7_usb_refresh_worker(self: Any) -> None:\n        try:\n            _diag(\"USB background scan start\")\n            candidates: list[Any] = []\n            try:\n                candidates = list(self.tool._auto_usb_log_candidates())\n            except Exception as exc:\n                _diag(f\"USB background scan exception {type(exc).__name__}: {exc}\")\n                return\n\n            result: list[dict[str, Any]] = []\n            seen: set[str] = set()\n            for item in candidates:\n                if not isinstance(item, dict):\n                    continue\n                device = str(item.get(\"device\") or \"\").strip()\n                if not device or device.lower() in seen:\n                    continue\n                seen.add(device.lower())\n                identity = \"\"\n                with contextlib.suppress(Exception):\n                    identity = str(self.tool._serial_identity_key(item) or \"\").strip().lower()\n                mapped_node_id = \"\"\n                if identity and hasattr(self.tool.repository, \"managed_node_by_usb\"):\n                    with contextlib.suppress(Exception):\n                        managed = self.tool.repository.managed_node_by_usb(identity)\n                        if managed:\n                            mapped_node_id = str(dict(managed).get(\"node_id\") or \"\")\n                result.append({\n                    \"device\": device,\n                    \"description\": str(item.get(\"description\") or \"\"),\n                    \"manufacturer\": str(item.get(\"manufacturer\") or \"\"),\n                    \"serial_number\": str(item.get(\"serial_number\") or \"\"),\n                    \"identity\": identity,\n                    \"mapped_node_id\": mapped_node_id,\n                })\n\n            signature = tuple((str(item.get(\"device\") or \"\"), str(item.get(\"identity\") or \"\"), str(item.get(\"mapped_node_id\") or \"\")) for item in result)\n            previous = self.__dict__.get(\"_diag_last_usb_signature\")\n            self.__dict__[\"_framework7_usb_cache\"] = [dict(item) for item in result]\n            self.__dict__[\"_framework7_usb_cache_at\"] = time.monotonic()\n            if previous != signature:\n                self.__dict__[\"_diag_last_usb_signature\"] = signature\n                _diag(f\"USB targets changed count={len(result)} targets={result!r}\")\n            _diag(f\"USB background scan done count={len(result)}\")\n        except BaseException as exc:\n            _diag(f\"USB background worker fatal {type(exc).__name__}: {exc}\")\n        finally:\n            self.__dict__[\"_framework7_usb_scan_running\"] = False\n\n    def _usb_targets(self: Any) -> list[dict[str, Any]]:\n        cached = self.__dict__.get(\"_framework7_usb_cache\")\n        if not isinstance(cached, list):\n            cached = []\n        last = float(self.__dict__.get(\"_framework7_usb_cache_at\") or 0.0)\n        age = time.monotonic() - last if last else 9999.0\n        running = bool(self.__dict__.get(\"_framework7_usb_scan_running\", False))\n        if age >= 2.0 and not running:\n            self.__dict__[\"_framework7_usb_scan_running\"] = True\n            threading.Thread(\n                target=_framework7_usb_refresh_worker,\n                args=(self,),\n                name=\"framework7-usb-discovery\",\n                daemon=True,\n            ).start()\n        # Critical invariant: API request threads NEVER enumerate COM ports.\n        return [dict(item) for item in cached if isinstance(item, dict)]\n\n    def _usb_targets_legacy_removed(self: Any) -> list[dict[str, Any]]:\n        result: list[dict[str, Any]] = []\n"""
    text = replace_once(text, start, replacement, "USB discovery worker split")

    # The original body below the replaced prefix is now unreachable legacy code
    # inside _usb_targets_legacy_removed. Keep it for build-time compatibility,
    # but ensure the real bridge gets only the cached non-blocking implementation.
    text = replace_once(
        text,
        "    LegacyBridge._usb_targets = _usb_targets\n",
        "    LegacyBridge._framework7_usb_refresh_worker = _framework7_usb_refresh_worker\n    LegacyBridge._usb_targets = _usb_targets\n",
        "USB cache bridge wiring",
    )

    path.write_text(text, encoding="utf-8")
    compile(text, str(path), "exec")
    print("Framework7 USB cache v3.14 installed: request threads are non-blocking")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
