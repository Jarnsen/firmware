from __future__ import annotations

from functools import lru_cache
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageDraw


# Icons are drawn into PIL images instead of using Unicode glyphs.  This keeps their
# appearance deterministic on Windows 125% DPI and avoids font/fallback differences.
_BASE = 20
_SCALE = 4


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (_BASE * _SCALE, _BASE * _SCALE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def _p(value: float) -> int:
    return int(round(value * _SCALE))


def _pts(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    return [(_p(x), _p(y)) for x, y in points]


def _line(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], color: str, width: float = 1.55) -> None:
    draw.line(_pts(points), fill=color, width=max(1, _p(width)), joint="curve")


def _ellipse(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], color: str, width: float = 1.45, fill: str | None = None) -> None:
    draw.ellipse(tuple(_p(v) for v in box), outline=color, fill=fill, width=max(1, _p(width)))


def _rect(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], color: str, width: float = 1.45, radius: float = 0.0, fill: str | None = None) -> None:
    coords = tuple(_p(v) for v in box)
    if radius:
        draw.rounded_rectangle(coords, radius=_p(radius), outline=color, fill=fill, width=max(1, _p(width)))
    else:
        draw.rectangle(coords, outline=color, fill=fill, width=max(1, _p(width)))


def _arc(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], start: float, end: float, color: str, width: float = 1.55) -> None:
    draw.arc(tuple(_p(v) for v in box), start=start, end=end, fill=color, width=max(1, _p(width)))


def _device(d: ImageDraw.ImageDraw, c: str) -> None:
    _rect(d, (5, 2.5, 15, 16), c, radius=1.4)
    _line(d, [(8, 17.5), (12, 17.5)], c)
    _line(d, [(7.3, 5.2), (12.7, 5.2)], c, 1.1)


def _chip(d: ImageDraw.ImageDraw, c: str) -> None:
    _rect(d, (5, 5, 15, 15), c, radius=1.4)
    for x in (7, 10, 13):
        _line(d, [(x, 2.5), (x, 5)], c, 1.2); _line(d, [(x, 15), (x, 17.5)], c, 1.2)
    for y in (7, 10, 13):
        _line(d, [(2.5, y), (5, y)], c, 1.2); _line(d, [(15, y), (17.5, y)], c, 1.2)
    _rect(d, (8, 8, 12, 12), c, width=1.1, radius=.6)


def _settings(d: ImageDraw.ImageDraw, c: str) -> None:
    _ellipse(d, (6.3, 6.3, 13.7, 13.7), c, 1.5)
    _ellipse(d, (8.6, 8.6, 11.4, 11.4), c, 1.25)
    for a in range(0, 360, 45):
        import math
        r1, r2 = 4.2, 7.0
        x1, y1 = 10 + math.cos(math.radians(a))*r1, 10 + math.sin(math.radians(a))*r1
        x2, y2 = 10 + math.cos(math.radians(a))*r2, 10 + math.sin(math.radians(a))*r2
        _line(d, [(x1, y1), (x2, y2)], c, 1.5)


def _user(d: ImageDraw.ImageDraw, c: str) -> None:
    _ellipse(d, (7, 3, 13, 9), c, 1.4)
    _arc(d, (4.2, 8, 15.8, 18), 190, 350, c, 1.7)


def _wrench(d: ImageDraw.ImageDraw, c: str) -> None:
    _arc(d, (3, 2.5, 10.5, 10), 35, 255, c, 1.6)
    _line(d, [(8.3, 8.3), (16.2, 16.2)], c, 2.0)
    _ellipse(d, (14.5, 14.5, 17.5, 17.5), c, 1.3)


def _clock(d: ImageDraw.ImageDraw, c: str) -> None:
    _ellipse(d, (3, 3, 17, 17), c, 1.55)
    _line(d, [(10, 5.8), (10, 10.2), (13.1, 12)], c, 1.55)


def _bulb(d: ImageDraw.ImageDraw, c: str) -> None:
    _arc(d, (4.5, 2.5, 15.5, 13.5), 150, 390, c, 1.5)
    _line(d, [(7.7, 12.2), (8.5, 15), (11.5, 15), (12.3, 12.2)], c, 1.35)
    _line(d, [(8.3, 17), (11.7, 17)], c, 1.35)


def _list(d: ImageDraw.ImageDraw, c: str) -> None:
    for y in (5, 10, 15):
        _rect(d, (3, y-1, 5, y+1), c, width=1.1, radius=.3)
        _line(d, [(7, y), (17, y)], c, 1.45)


def _search(d: ImageDraw.ImageDraw, c: str) -> None:
    _ellipse(d, (3.5, 3.5, 12.8, 12.8), c, 1.65)
    _line(d, [(12, 12), (17, 17)], c, 1.8)


def _download(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(10, 3), (10, 12)], c, 1.7)
    _line(d, [(6.5, 8.7), (10, 12.2), (13.5, 8.7)], c, 1.7)
    _line(d, [(4, 15), (4, 17), (16, 17), (16, 15)], c, 1.5)


def _upload(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(10, 17), (10, 8)], c, 1.7)
    _line(d, [(6.5, 11.3), (10, 7.8), (13.5, 11.3)], c, 1.7)
    _line(d, [(4, 5), (4, 3), (16, 3), (16, 5)], c, 1.5)


def _folder(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(3, 7), (3, 5), (8, 5), (9.5, 7), (17, 7), (16, 16), (4, 16), (3, 7)], c, 1.5)


def _edit(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(5, 15), (6, 11.5), (13.5, 4), (16, 6.5), (8.5, 14), (5, 15)], c, 1.65)
    _line(d, [(12.2, 5.3), (14.7, 7.8)], c, 1.2)


def _file(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(5, 2.8), (12, 2.8), (16, 6.8), (16, 17), (5, 17), (5, 2.8)], c, 1.45)
    _line(d, [(12, 2.8), (12, 7), (16, 7)], c, 1.35)
    _line(d, [(8, 10), (13, 10), (8, 13), (13, 13)], c, 1.05)


def _info(d: ImageDraw.ImageDraw, c: str) -> None:
    _ellipse(d, (3.5, 3.5, 16.5, 16.5), c, 1.45)
    _ellipse(d, (9.2, 6, 10.8, 7.6), c, 1.0, fill=c)
    _line(d, [(10, 9), (10, 14)], c, 1.55)


def _refresh(d: ImageDraw.ImageDraw, c: str) -> None:
    _arc(d, (3.5, 3.5, 16.5, 16.5), 40, 205, c, 1.55)
    _arc(d, (3.5, 3.5, 16.5, 16.5), 220, 385, c, 1.55)
    d.polygon(_pts([(14.6, 3.7), (17.4, 4.4), (16.2, 7.0)]), fill=c)
    d.polygon(_pts([(5.4, 16.3), (2.6, 15.6), (3.8, 13.0)]), fill=c)


def _cloud(d: ImageDraw.ImageDraw, c: str) -> None:
    _arc(d, (4, 6, 16, 16), 180, 360, c, 1.55)
    _arc(d, (3, 8, 10, 15), 90, 270, c, 1.55)
    _arc(d, (7, 3, 14, 11), 185, 355, c, 1.55)
    _line(d, [(5.8, 14.5), (14.6, 14.5)], c, 1.5)


def _play(d: ImageDraw.ImageDraw, c: str) -> None:
    d.polygon(_pts([(7, 4.5), (16, 10), (7, 15.5)]), fill=c)


def _copy(d: ImageDraw.ImageDraw, c: str) -> None:
    _rect(d, (6, 5, 16, 16), c, 1.4, radius=1.0)
    _rect(d, (3, 2, 13, 13), c, 1.4, radius=1.0)


def _trash(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(4, 6), (16, 6)], c, 1.5)
    _line(d, [(7, 3.5), (13, 3.5)], c, 1.5)
    _line(d, [(6, 7), (7, 17), (13, 17), (14, 7)], c, 1.5)
    _line(d, [(9, 9), (9, 15), (11, 9), (11, 15)], c, 1.1)


def _expand(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(3, 8), (3, 3), (8, 3)], c, 1.5)
    _line(d, [(12, 3), (17, 3), (17, 8)], c, 1.5)
    _line(d, [(3, 12), (3, 17), (8, 17)], c, 1.5)
    _line(d, [(12, 17), (17, 17), (17, 12)], c, 1.5)


def _usb(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(10, 17), (10, 4)], c, 1.45)
    _line(d, [(10, 8), (6, 8), (6, 5)], c, 1.35)
    _line(d, [(10, 11), (14, 11), (14, 8)], c, 1.35)
    d.polygon(_pts([(10, 2.5), (8.2, 5.4), (11.8, 5.4)]), fill=c)
    _ellipse(d, (4.7, 3.6, 7.3, 6.2), c, 1.0, fill=c)
    _rect(d, (12.8, 6.5, 15.2, 8.9), c, 1.0, fill=c)


def _check(d: ImageDraw.ImageDraw, c: str) -> None:
    _line(d, [(4, 10.5), (8.2, 14.2), (16, 5.7)], c, 2.0)


def _alert(d: ImageDraw.ImageDraw, c: str) -> None:
    d.polygon(_pts([(10, 2.8), (18, 17), (2, 17)]), outline=c, fill=None)
    _line(d, [(10, 7), (10, 12)], c, 1.7)
    _ellipse(d, (9.2, 14, 10.8, 15.6), c, 1.0, fill=c)


def _radio_on(d: ImageDraw.ImageDraw, c: str) -> None:
    _ellipse(d, (4, 4, 16, 16), c, 1.45)
    _ellipse(d, (8, 8, 12, 12), c, 1.0, fill=c)


def _radio_off(d: ImageDraw.ImageDraw, c: str) -> None:
    _ellipse(d, (4, 4, 16, 16), c, 1.45)


_DRAWERS: dict[str, Callable[[ImageDraw.ImageDraw, str], None]] = {
    "device": _device,
    "chip": _chip,
    "settings": _settings,
    "user": _user,
    "wrench": _wrench,
    "clock": _clock,
    "bulb": _bulb,
    "list": _list,
    "search": _search,
    "download": _download,
    "upload": _upload,
    "folder": _folder,
    "edit": _edit,
    "file": _file,
    "info": _info,
    "refresh": _refresh,
    "cloud": _cloud,
    "play": _play,
    "copy": _copy,
    "trash": _trash,
    "expand": _expand,
    "usb": _usb,
    "check": _check,
    "alert": _alert,
    "radio_on": _radio_on,
    "radio_off": _radio_off,
}


@lru_cache(maxsize=256)
def icon(name: str, size: int = 14, color: str = "#E8EEF5") -> ctk.CTkImage:
    if name not in _DRAWERS:
        raise KeyError(f"Unknown UI icon: {name}")
    image, draw = _canvas()
    _DRAWERS[name](draw, color)
    image = image.resize((max(1, int(size * 2)), max(1, int(size * 2))), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


def smoke_test() -> None:
    # Pure PIL drawing portion can be exercised in CI before a window exists.
    for name, drawer in _DRAWERS.items():
        image, draw = _canvas()
        drawer(draw, "#FFFFFF")
        if image.getbbox() is None:
            raise AssertionError(f"Icon rendered empty: {name}")
