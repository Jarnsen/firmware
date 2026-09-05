from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

CANVAS = 1024
ICON_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def _gradient_polygon(base: Image.Image, points, top: str, bottom: str, *, horizontal: bool = False) -> None:
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    gradient = Image.linear_gradient("L").resize(base.size)
    if horizontal:
        gradient = gradient.rotate(90, expand=False)
    fill = ImageOps.colorize(gradient, black=top, white=bottom).convert("RGBA")
    base.alpha_composite(Image.composite(fill, Image.new("RGBA", base.size), mask))


def _build_source() -> Image.Image:
    radial = Image.radial_gradient("L").resize((CANVAS, CANVAS))
    background = ImageOps.colorize(radial, black="#12345f", white="#030b17").convert("RGBA")

    # Soft blue halo behind the mark, matching the original JARNSEN badge mood.
    halo = Image.new("RGBA", background.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((100, 75, 924, 899), fill=(18, 65, 118, 55))
    halo = halo.filter(ImageFilter.GaussianBlur(145))
    background.alpha_composite(halo)

    # Angular mountain mark. Coordinates intentionally keep the symbol large in the square.
    _gradient_polygon(background, [(42, 760), (292, 408), (315, 594)], "#f8fbff", "#aabbd0")
    _gradient_polygon(background, [(292, 408), (315, 594), (356, 507)], "#dbe5f2", "#6f819a", horizontal=True)

    _gradient_polygon(
        background,
        [(297, 643), (550, 174), (561, 449), (494, 520), (519, 416)],
        "#ffffff",
        "#c9d7e8",
    )
    _gradient_polygon(background, [(550, 174), (561, 449), (756, 626)], "#eef5fd", "#9db2cc", horizontal=True)
    _gradient_polygon(background, [(561, 449), (676, 597), (548, 722), (756, 626)], "#f8fbff", "#a8bbd0")

    _gradient_polygon(background, [(756, 626), (806, 479), (806, 650)], "#cfdbea", "#6f8199", horizontal=True)
    _gradient_polygon(background, [(806, 479), (969, 801), (806, 650)], "#ffffff", "#b6c7db")

    # Tiny highlights sharpen the folded-metal look at icon sizes.
    draw = ImageDraw.Draw(background)
    draw.line([(550, 175), (561, 449)], fill="#ffffff", width=3)
    draw.line([(42, 760), (292, 408)], fill="#eef6ff", width=2)
    draw.line([(806, 479), (969, 801)], fill="#eef6ff", width=2)
    return background.convert("RGB")


def generate_icon() -> Path:
    assets = Path(__file__).resolve().parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    icon_path = assets / "jarnsen_mesh_flasher_icon.ico"
    _build_source().save(icon_path, format="ICO", sizes=list(ICON_SIZES))
    return icon_path


if __name__ == "__main__":
    print(generate_icon())
