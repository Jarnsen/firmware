"""v2.1.8: classify visible BLE nodes that cannot accept a connection as not free."""
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
    if "    def _ble_unavailable_reason(self, label: str, exc: BaseException)" not in source:
        helper = r'''    def _ble_unavailable_reason(self, label: str, exc: BaseException) -> str:
        """Describe a connect failure without pretending to know the remote owner.

        BLE advertisements do not expose who owns an existing connection. When
        the device was visible in the preceding scan but the service connection
        cannot be established, report the operationally useful state: currently
        not free / possibly in use elsewhere. Keep the original error in the log.
        """
        text = str(exc).strip()
        lowered = text.lower()
        busy_tokens = (
            "timeout",
            "timed out",
            "not connected",
            "could not connect",
            "failed to connect",
            "connection failed",
            "connection refused",
            "connection aborted",
            "connection reset",
            "device not found",
            "unreachable",
            "gatt",
            "att error",
            "operation already in progress",
            "busy",
            "resource in use",
        )
        likely_busy = any(token in lowered for token in busy_tokens)
        state = (
            "anderweitig verwendet / derzeit nicht frei"
            if likely_busy
            else "derzeit nicht frei"
        )
        tool_log(
            "BLE_NODE_NOT_FREE_V218",
            node=label,
            state=state,
            error_type=type(exc).__name__,
            error=text or "--",
        )
        return f"{label}: {state}"
'''
        source = insert_before_method(source, "_ble_download_worker", helper)

    def patch_worker(method: str) -> str:
        old_reserve = '''                    except Exception as exc:\n                        failures.append(\n                            f"{label}: Warteschlangen-Reservierung fehlgeschlagen: {exc}"\n                        )\n'''
        new_reserve = '''                    except Exception as exc:\n                        failures.append(self._ble_unavailable_reason(label, exc))\n                        tool_log("BLE_MULTI_DOWNLOAD_SKIP", node=label, error=exc, reason="not-free")\n'''
        if old_reserve in method:
            method = method.replace(old_reserve, new_reserve, 1)

        # v2.1.3 adds BLE_MULTI_DOWNLOAD_SKIP immediately after the failure
        # append. Match that actual generated shape instead of the older block.
        old_download = '''                except Exception as exc:\n                    failures.append(f"{label}: {exc}")\n                    tool_log("BLE_MULTI_DOWNLOAD_SKIP", node=label, error=exc)\n                    if queue_hold_active:\n'''
        new_download = '''                except Exception as exc:\n                    failures.append(self._ble_unavailable_reason(label, exc))\n                    tool_log("BLE_MULTI_DOWNLOAD_SKIP", node=label, error=exc, reason="not-free")\n                    if queue_hold_active:\n'''
        if old_download not in method:
            raise SystemExit("v2.1.8 BLE download failure anchor not found")
        method = method.replace(old_download, new_download, 1)
        return method

    source = replace_method(source, "_ble_download_worker", patch_worker)

    required = (
        "def _ble_unavailable_reason(self, label: str, exc: BaseException)",
        "anderweitig verwendet / derzeit nicht frei",
        "BLE_NODE_NOT_FREE_V218",
        "failures.append(self._ble_unavailable_reason(label, exc))",
        'reason="not-free"',
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.1.8 BLE-busy validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v218_ble_busy.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    patched = patch(source)
    path.write_text(patched, encoding="utf-8")
    print(f"Added BLE not-free classification to {path} for v{APP_VERSION}")


if __name__ == "__main__":
    main()
