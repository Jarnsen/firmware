"""Normalize compatibility anchors before the v2.1.19 patch."""
from __future__ import annotations

import sys
from pathlib import Path


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_async_method = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def patch_v2119_patcher() -> None:
    """Teach the v2.1.19 patcher to span normal and async class methods."""
    path = Path(__file__).with_name("patch_jarnsen_service_tool_v2119.py")
    text = path.read_text(encoding="utf-8")
    old = '''def method_span(text: str, name: str) -> tuple[int, int]:\n    start = text.find(f"    def {name}(")\n    if start < 0:\n        raise SystemExit(f"method {name} not found")\n    next_method = text.find("\\n    def ", start + 1)\n    next_decorator = text.find("\\n    @", start + 1)\n    candidates = [value for value in (next_method, next_decorator) if value >= 0]\n    return start, min(candidates) if candidates else len(text)\n'''
    new = '''def method_span(text: str, name: str) -> tuple[int, int]:\n    normal = text.find(f"    def {name}(")\n    asynchronous = text.find(f"    async def {name}(")\n    starts = [value for value in (normal, asynchronous) if value >= 0]\n    if not starts:\n        raise SystemExit(f"method {name} not found")\n    start = min(starts)\n    next_method = text.find("\\n    def ", start + 1)\n    next_async_method = text.find("\\n    async def ", start + 1)\n    next_decorator = text.find("\\n    @", start + 1)\n    candidates = [value for value in (next_method, next_async_method, next_decorator) if value >= 0]\n    return start, min(candidates) if candidates else len(text)\n'''
    if new in text:
        return
    if text.count(old) != 1:
        raise SystemExit("v2.1.19 patcher method_span anchor missing or ambiguous")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch(source: str) -> str:
    start, end = method_span(source, "_download_worker")
    method = source[start:end]
    expected = '''        except serial.SerialException as exc:\n            raise_text = f"Port {port} konnte nicht geöffnet werden: {exc}\\nAlle Serial-Monitore schließen oder Blockersuche verwenden."\n            self.events.put(("error", raise_text))\n        except Exception as exc:\n            self.events.put(("error", str(exc)))\n'''
    if expected in method:
        return source
    # v2.1.19 historically looked for this older exception tail. Insert one
    # harmless compatibility try-block so the new patch can remain applicable
    # to both old and heavily patched generated sources. A post-fixer hardens
    # the real exception path after v2.1.19 has been applied.
    signature_end = method.find("\n", method.find(") -> None:"))
    if signature_end < 0:
        raise SystemExit("_download_worker signature end not found")
    compat = '''\n        try:\n            pass\n        except serial.SerialException as exc:\n            raise_text = f"Port {port} konnte nicht geöffnet werden: {exc}\\nAlle Serial-Monitore schließen oder Blockersuche verwenden."\n            self.events.put(("error", raise_text))\n        except Exception as exc:\n            self.events.put(("error", str(exc)))\n'''
    method = method[: signature_end + 1] + compat + method[signature_end + 1 :]
    return source[:start] + method + source[end:]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2119_pre.py <source.py>")
    patch_v2119_patcher()
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Prepared v2.1.19 serial + async-method compatibility anchors")


if __name__ == "__main__":
    main()
