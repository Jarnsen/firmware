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
# Structural signature derived from the approved Build 148 screenshot at 1920x1080 / 125%.
# Payload = blurred grayscale row+column means followed by edge row+column means.
REFERENCE_SIGNATURE_B64 = (
    "eNptlGuP4zQUhnPpZJo4cXx34sTOtU3bpJ3ZuYEQA7uj1bASAoQESPCV38F/x2k7M7uIR1Fz7HPxeXsiI8zyethfX+26MhOccyGklGK2rClkXpimW61Xq642ZVGYdr0Z+rpUmTwGW7/W8ypTprNBldZVt95N+6vrm9u723dX027oaq1saXYMVzO67gcbM03T/nB1dZg2XWVr66qujS5K06w24zTtNiubqMq634zjOB2urw/jbn/37dPz8/PHp8f7ad02da2LuWuRF1Xb922lJOeyqJraFMeTbPYwrPrVsN30Zm561mRfDKPUgjAhs4UQppRaEx03mcisUpu0mxlnpr1lmjs+GuO421qO/u2JzcybPcwc94ZhPXNaDZ+xPnlWK9t5U1eVqSx1Pf8aoy3muHNam/Pr6Cn/l8LyupizbZKpzimnrOINpfJsJleFNnXTdX2/eqWf6dq2manPB7/x2svn5hdBLweeWtHG6porfcmbOH2S+58KL9Zr33ai+ZF5tsVZ71nMeVcdY14sZT8nY8pcckqOE0+d0Bf65peHsg+8ZeEsHO8iCBzXsY+/DBzf+R15gdaL8G/nwFwODh/ucu4+OQvm+J0buG6ZZa7vOIGrfvh04YXvvS1Y9034qVXf+yVqDp57sXFT7bDMDRwPo8hGT8DLijr0nhs/7utg8ZOTJguww0Im3kJ8FS6yOFn4j9FFsFio8f7mQ7KF4vHX6mKB/+luKS3Xf/4cAKC7hnr+rePcOdq7fHewVUPHD9DXD99FXtyZLbiMH3/8Q/nR+9/+6nxIRQm9gJqK+oHnWhxnmiU6juf6yniOa/+PWfl1eLEc2+ZeqdVOtnv9wOvbbX27yR90P2719ajX3/C1GDd1Zu+JblWsi3pdqaqsh4rvVd6UvOG0yWQjskHiRtKC6c6QqiKVEo2gE6c9Y52UVY6UYkWRMy6YQIpjLpFiScEhA1gKlAuoEBIJzhkUDEqIsjTEMEogSBOIaYRJRJIE4ViAMIGQ4ATBmEDIMeaUMY4ZSwiFFIEURjAJE3CZxBE3yygyEFxiekmR/eBNV9kroxxM1bZFW2WjqLa81LkuW1Exw5kscjsfJhVnuShFoeb7jktBM4mEojQnOcXcxnHCBZEIcJliiRHkkpDc7jOREyyQzBHDjMx9USxTe8lQnKIkJQgjgghOCSSMkDTBMI1pihjlaYyB1RvFMYhBCMAyBhDCNE0AFDYowUkazZ4wghEASRSFcQhhAkC4TGE4XpHFEhSOZ0eb/gtU7Jnk"
)

CRASH_TITLES = (
    "Unhandled exception in script",
    "Fatal error detected",
    "Python error",
)

LOCK_SCREEN_PROCESSES = {"lockapp.exe", "logonui.exe"}
LOCK_SCREEN_TITLES = ("lock screen", "sperrbildschirm", "windows default lock screen")


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


def _input_desktop_name() -> str | None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    desktop = None
    try:
        desktop = user32.OpenInputDesktop(0, False, 0x0001)
        if not desktop:
            return None
        needed = ctypes.c_ulong(0)
        user32.GetUserObjectInformationW(desktop, 2, None, 0, ctypes.byref(needed))
        if needed.value <= 2:
            return None
        buffer = ctypes.create_unicode_buffer(max(1, needed.value // ctypes.sizeof(ctypes.c_wchar)))
        if not user32.GetUserObjectInformationW(desktop, 2, buffer, needed.value, ctypes.byref(needed)):
            return None
        return buffer.value.strip() or None
    except Exception:
        return None
    finally:
        if desktop:
            try:
                user32.CloseDesktop(desktop)
            except Exception:
                pass


def _foreground_window_description() -> str:
    if sys.platform != "win32":
        return "unknown"
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "none"
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, len(title))
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_name, len(class_name))
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_name = "unknown"
    if pid.value:
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                size = ctypes.c_ulong(32768)
                path = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                    process_name = Path(path.value).name
            except Exception:
                pass
            finally:
                kernel32.CloseHandle(handle)
    return f"process={process_name} class={class_name.value} title={title.value}"


def _lock_screen_is_foreground() -> tuple[bool, str]:
    description = _foreground_window_description()
    lowered = description.casefold()
    locked = any(name in lowered for name in LOCK_SCREEN_PROCESSES) or any(
        title in lowered for title in LOCK_SCREEN_TITLES
    )
    return locked, description


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

        candidates: list[tuple[int, object]] = []
        for window in desktop.windows(visible_only=True):
            title = (window.window_text() or "").strip()
            if "JARNSEN MESH Flasher" not in title:
                continue
            try:
                rect = window.rectangle()
                width = max(0, int(rect.width()))
                height = max(0, int(rect.height()))
                area = width * height
            except Exception:
                area = 0
            if area > 0:
                candidates.append((area, window))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
        time.sleep(0.25)
    raise TimeoutError("Visible JARNSEN MESH Flasher window did not appear within timeout")


def _wait_for_reference_window(timeout: float):
    """Wait through transient iconic/non-maximized onefile startup windows.

    The visual thresholds remain unchanged; this only gives the application time
    to finish its bounded dashboard rebuild before the hard 1920x1080 gate runs.
    """
    deadline = time.monotonic() + max(1.0, float(timeout))
    last = None
    while time.monotonic() < deadline:
        try:
            window = _find_flasher_window(min(2.0, max(0.5, deadline - time.monotonic())))
            rect = window.rectangle()
            width = int(rect.width())
            height = int(rect.height())
            last = (window, rect, width, height)
            if width >= 1800 and height >= 950 and rect.left > -10000 and rect.top > -10000:
                return last
        except Exception:
            pass
        time.sleep(0.25)
    if last is not None:
        return last
    raise TimeoutError("JARNSEN MESH Flasher reference window did not become measurable")


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

        input_desktop = _input_desktop_name()
        locked, foreground = _lock_screen_is_foreground()
        log(f"DESKTOP · input={input_desktop or 'unknown'} foreground={foreground}")
        if (input_desktop and input_desktop.casefold() != "default") or locked:
            log("EXE GUI · SKIP · Windows lock/secure surface is active; source UI smoke remains the hard UI gate")
            return 0

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

        input_desktop = _input_desktop_name()
        locked, foreground = _lock_screen_is_foreground()
        log(f"DESKTOP · before-capture={input_desktop or 'unknown'} foreground={foreground}")
        if (input_desktop and input_desktop.casefold() != "default") or locked:
            log("EXE GUI · SKIP · Windows lock/secure surface became active before capture; source UI smoke remains the hard UI gate")
            return 0

        window, rect, width, height = _wait_for_reference_window(12.0)
        log(f"WINDOW · left={rect.left} top={rect.top} width={width} height={height}")
        if width < 1800 or height < 950 or rect.left <= -10000 or rect.top <= -10000:
            raise AssertionError(
                f"Window is not maximized for the 1920x1080 reference: left={rect.left} top={rect.top} {width}x{height}"
            )

        try:
            screenshot = window.capture_as_image().convert("RGB")
            if screenshot.width < 1800 or screenshot.height < 950:
                raise RuntimeError(f"window capture too small: {screenshot.width}x{screenshot.height}")
            log("CAPTURE · source=window-hwnd")
        except Exception as capture_exc:
            log(f"CAPTURE · window-hwnd unavailable ({type(capture_exc).__name__}); fallback=ImageGrab")
            screenshot = ImageGrab.grab(
                bbox=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)), all_screens=True
            ).convert("RGB")

        screenshot.save(out / "actual-window.png")
        thumb = screenshot.resize((REFERENCE_WIDTH, REFERENCE_HEIGHT), Image.Resampling.LANCZOS)
        thumb.save(out / "actual-480x272.png")

        input_desktop = _input_desktop_name()
        locked, foreground = _lock_screen_is_foreground()
        log(f"DESKTOP · after-capture={input_desktop or 'unknown'} foreground={foreground}")
        if (input_desktop and input_desktop.casefold() != "default") or locked:
            log("EXE GUI · SKIP · Windows lock/secure surface became active during capture; source UI smoke remains the hard UI gate")
            return 0

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
