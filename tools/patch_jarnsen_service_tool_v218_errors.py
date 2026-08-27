"""v2.1.8: make Tk callback failures visible and reliably persisted."""
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


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:].lstrip("\n")


def patch(source: str) -> str:
    replacement = r'''    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        # v2.1.5 could show a generic callback-error dialog without leaving the
        # promised traceback in the tool log. Build the traceback first and then
        # persist it through both the normal logger and a direct emergency append.
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        error_type = getattr(exc_type, "__name__", str(exc_type))
        error_text = str(exc_value)
        path = init_tool_log()

        if isinstance(exc_value, BaseException):
            with contextlib.suppress(Exception):
                tool_log_exception("tk_callback", exc_value)

        # Independent fallback: even if tool_log/tool_log_exception itself ever
        # regresses, the exact traceback still lands in the same session log.
        if path is not None:
            with contextlib.suppress(Exception):
                timestamp = now_local().isoformat(timespec="milliseconds")
                detail = _tool_log_value(message)
                with _TOOL_LOG_LOCK:
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(
                            f"{timestamp} | TK_CALLBACK_DETAIL_V218 | "
                            f"type={_tool_log_value(error_type)} "
                            f"message={_tool_log_value(error_text)} "
                            f"traceback={detail}\n"
                        )

        with contextlib.suppress(Exception):
            self.set_result(f"Tool-Fehler: {error_type}: {error_text}\n\n{message}")

        with contextlib.suppress(Exception):
            messagebox.showerror(
                "Tool-Fehler",
                "Ein interner Bedien-/GUI-Fehler ist aufgetreten.\n\n"
                f"{error_type}: {error_text}\n\n"
                f"Der vollständige Traceback steht im Tool-Log:\n{path}",
            )
'''
    source = replace_method(source, "report_callback_exception", replacement)

    required = (
        'APP_VERSION = "2.1.8"',
        "TK_CALLBACK_DETAIL_V218",
        "Der vollständige Traceback steht im Tool-Log",
        "tool_log_exception(\"tk_callback\"",
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.1.8 callback-error validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v218_errors.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    patched = patch(source)
    path.write_text(patched, encoding="utf-8")
    print(f"Hardened callback diagnostics in {path} for v{APP_VERSION}")


if __name__ == "__main__":
    main()
