from __future__ import annotations

import argparse
import base64
import ctypes
import subprocess
import sys
import time
import traceback
import winreg
import zlib
from pathlib import Path

from PIL import Image, ImageFilter, ImageGrab, ImageOps
from pywinauto import Desktop


REFERENCE_WIDTH = 480
REFERENCE_HEIGHT = 272
# Structural signature derived from the approved 1920x1080 / 125% reference screenshot.
# Payload = blurred grayscale row+column means followed by edge row+column means.
REFERENCE_SIGNATURE_B64 = (
    "eNpdlMty5DQUhqts2Z2++CbLlmzJsmz51m73JZ1JJ8wMCVMFU0DVLFiwYkvxCMwTsGHHhi1LVjwBT8AzUUU4didUwldl6+gcSf6PdKzff/7+vqZhxIu27+s8icKQxDRJUy6E4JyLTKqybmqtJDiyTOZluz2eTsehKaRIE8YSLgutizwTsqiausylVLrp+mG72x+urm9uTsddp3PO4iimjAs5oqr1/vrNZ5+//+Ldm1dDDVEIqarrmhK+I4u67TebdVupjPOsaNZ9W5VFqau6bmBpEHD7+pPbm1eHTSUTCnoFzN1sh05LDpIojeOYUgbiAGjY1JnaMRRNQENCjMMIYnFI+O7Dj7/9+cvHb68V9GDJvGz63eXx6njY77Y7SOaJ/f6xNxrbM8Om70HyAObuGWf/GNkMw7CBzvqJ7kw70jRNXWldlqXWugILzGJidDxSPlEUSuXPkWcyOB4pnzzwVmeeD330yEzwdNqZJBVZXlZwxKOCR6ppo2twnZlcZ+M/FeNhwJTyhRj5jP8JzLJJn1JTXuqlIFVMql4wTRBPTDbn6chYlufYWKFT7PnYaRueFoE8GYWqjovb737646+HBwMhc4Zmsv/6/tK3bGQYt4ZlWauF582g8962Z8nhgNDFyTCMj4adri7WX36jL0hoGr8aRo1MVPG0mZkwqbs/2RQZle/jC568vliodt219ZwtiekSAzEDLSJMlvDJE18sk7c3d9oJtgIl1oU2rebuK0GsJcK1KeaOYws+t5FtzcMfPnATLfYbO2ujbrBOi6TZYeKo9s4wC8PQpkmXfru9imaNYXf90iQFQ8t2PUP5wNFqs7ZRPJRo3nRzFGcpskVmG8ywSgOZplkVW8tEpmsYDw8PCDELdsGuncXK3X+qT+1brtW6qNrLQ3No+/wkboXSV+2xl81hqIY0a4diz488KeipbKpuVxZ1Lzq9ycq1TGUnCjnIUueN7ljHFS+4kkpyVaZw3DQXGYN/lkqRJ3FKy1CRsRThx4wIxRSrOCeZiGOWRCJkYRIlNAgocYnrhYEf+NiPMPbcMHA8x3GWju96XuB5jut6xAuIw8Ig9GCo53q+twocEsBIn3iQXeAsFl64cFZhrkCThspPoUyzhOqS5gpMluWRzCiXKUsqAckwDtE4i2lKY5aXsU4jyjmGK4fQNEhAXhjTiIEjjKOQ0jQhlJEoZj7FKSZBmJCYRERAEUAGMMrH47VDwjghHl2FDvaDAPsYHh/k+ivHhazgtfSdwHcXy8BxV5678jEmke9hB7L1PT/EPgmw67nYDVYu3GEUNgVTL68c4s7n2RLNLJuh7p+//wXsVLFz"
)

CRASH_TITLES = (
    "Unhandled exception in script",
    "Fatal error detected",
    "Python error",
)


def _mean_abs(a: bytes, b: bytes) -> float:
    if len(a) != len(b):
        raise ValueError(f"signature length mismatch: {len(a)} != {len(b)}")
    return sum(abs(x - y) for x, y in zip(a, b)) / (255.0 * len(a))


def _row_col_signature(image: Image.Image) -> bytes:
    gray = ImageOps.grayscale(image.resize((REFERENCE_WIDTH, REFERENCE_HEIGHT), Image.Resampling.LANCZOS))
    blur = gray.filter(ImageFilter.GaussianBlur(2))
    edges = gray.filter(ImageFilter.FIND_EDGES)

    def means(img: Image.Image) -> bytes:
        rows = img.resize((1, REFERENCE_HEIGHT), Image.Resampling.BOX).tobytes()
        cols = img.resize((REFERENCE_WIDTH, 1), Image.Resampling.BOX).tobytes()
        return rows + cols

    return means(blur) + means(edges)


def _reference_signature() -> tuple[bytes, bytes]:
    raw = zlib.decompress(base64.b64decode(REFERENCE_SIGNATURE_B64))
    split = REFERENCE_WIDTH + REFERENCE_HEIGHT
    if len(raw) != split * 2:
        raise RuntimeError(f"Reference signature corrupt: {len(raw)} bytes")
    return raw[:split], raw[split:]


def _dpi_values() -> tuple[int | None, int | None]:
    api_dpi = None
    registry_dpi = None
    try:
        api_dpi = int(ctypes.windll.user32.GetDpiForSystem())
    except Exception:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics") as key:
            registry_dpi = int(winreg.QueryValueEx(key, "AppliedDPI")[0])
    except Exception:
        pass
    return api_dpi, registry_dpi


def _find_crash_dialog() -> str | None:
    try:
        for window in Desktop(backend="win32").windows():
            title = (window.window_text() or "").strip()
            if any(token.lower() in title.lower() for token in CRASH_TITLES):
                return title
            if title:
                try:
                    text = " ".join(window.texts())
                except Exception:
                    text = ""
                if "Failed to execute script 'app'" in text or "invalid command name" in text:
                    return f"{title}: {text[:300]}"
    except Exception:
        pass
    return None


def _find_flasher_window(timeout: float):
    deadline = time.time() + timeout
    desktop = Desktop(backend="win32")
    while time.time() < deadline:
        crash = _find_crash_dialog()
        if crash:
            raise RuntimeError(f"Crash dialog detected before main window: {crash}")
        for window in desktop.windows():
            title = (window.window_text() or "").strip()
            if "JARNSEN MESH Flasher" in title:
                return window
        time.sleep(0.25)
    raise TimeoutError("JARNSEN MESH Flasher window did not appear within timeout")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-dpi", type=int, default=120)
    parser.add_argument("--layout-threshold", type=float, default=0.060)
    parser.add_argument("--edge-threshold", type=float, default=0.075)
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    parser.add_argument("--settle-seconds", type=float, default=4.0)
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    metrics_file = out / "metrics.txt"
    process: subprocess.Popen[str] | None = None

    def log(message: str) -> None:
        print(message, flush=True)
        with metrics_file.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    try:
        api_dpi, registry_dpi = _dpi_values()
        log(f"DPI · expected={args.expected_dpi} api={api_dpi} registry={registry_dpi}")
        known = [value for value in (registry_dpi, api_dpi) if value is not None]
        if known and args.expected_dpi not in known:
            raise AssertionError(
                f"Runner is not at the 125% reference DPI ({args.expected_dpi}); detected {known}"
            )
        if api_dpi is not None and registry_dpi is not None and api_dpi != registry_dpi:
            log("DPI · warning: API and registry differ; screenshot regression remains authoritative")

        exe = Path(args.exe).resolve()
        if not exe.exists():
            raise FileNotFoundError(exe)

        log(f"EXE GUI · starting {exe}")
        process = subprocess.Popen([str(exe)], cwd=str(exe.parent), text=True)
        window = _find_flasher_window(args.startup_timeout)
        try:
            window.set_focus()
        except Exception:
            pass

        time.sleep(args.settle_seconds)
        if process.poll() is not None:
            raise RuntimeError(f"Flasher exited during GUI settle period with code {process.returncode}")
        crash = _find_crash_dialog()
        if crash:
            raise RuntimeError(f"Crash dialog detected: {crash}")

        rect = window.rectangle()
        width = int(rect.width())
        height = int(rect.height())
        log(f"WINDOW · left={rect.left} top={rect.top} width={width} height={height}")
        if width < 1800 or height < 950:
            raise AssertionError(
                f"Window is not maximized for the 1920x1080 reference: {width}x{height}"
            )

        screenshot = ImageGrab.grab(
            bbox=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
            all_screens=True,
        ).convert("RGB")
        screenshot.save(out / "actual-window.png")
        thumb = screenshot.resize((REFERENCE_WIDTH, REFERENCE_HEIGHT), Image.Resampling.LANCZOS)
        thumb.save(out / "actual-480x272.png")

        signature = _row_col_signature(screenshot)
        split = REFERENCE_WIDTH + REFERENCE_HEIGHT
        current_layout, current_edges = signature[:split], signature[split:]
        reference_layout, reference_edges = _reference_signature()
        layout_diff = _mean_abs(current_layout, reference_layout)
        edge_diff = _mean_abs(current_edges, reference_edges)
        log(
            f"REFERENCE · 1920x1080@125% · layout-diff={layout_diff:.5f} "
            f"edge-diff={edge_diff:.5f} thresholds={args.layout_threshold:.3f}/{args.edge_threshold:.3f}"
        )

        if layout_diff > args.layout_threshold:
            raise AssertionError(
                f"Layout differs too much from approved reference: {layout_diff:.5f} > {args.layout_threshold:.5f}"
            )
        if edge_diff > args.edge_threshold:
            raise AssertionError(
                f"Edge/layout structure differs too much from approved reference: {edge_diff:.5f} > {args.edge_threshold:.5f}"
            )

        # A small focus/keyboard round-trip verifies that the frozen window still accepts
        # user input after the asynchronous startup work has settled.
        try:
            window.type_keys("{TAB}{ESC}", set_foreground=True)
        except Exception as exc:
            log(f"INPUT · warning: pywinauto keyboard probe failed: {type(exc).__name__}: {exc}")
        time.sleep(0.4)
        crash = _find_crash_dialog()
        if crash:
            raise RuntimeError(f"Crash dialog detected after input probe: {crash}")
        if process.poll() is not None:
            raise RuntimeError(f"Flasher exited after input probe with code {process.returncode}")

        log("EXE GUI · PASS · startup=stable crash-dialog=none screenshot=within-reference")
        return 0
    except Exception as exc:
        log(f"EXE GUI · FAIL · {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        try:
            ImageGrab.grab(all_screens=True).save(out / "desktop-on-failure.png")
        except Exception as grab_exc:
            log(f"Failure screenshot unavailable: {grab_exc}")
        return 3
    finally:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
