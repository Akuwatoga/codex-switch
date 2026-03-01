#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
MASTER_SIZE = 1024
EXPORTS = {
    "logo-master.png": 1024,
    "logo-128.png": 128,
    "logo-64.png": 64,
    "logo-32.png": 32,
}
TRAY_ICON_SIZE = 64


def clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def lerp_color(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(clamp(start[i] + (end[i] - start[i]) * t) for i in range(3))


def vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    px = image.load()
    for y in range(size):
        t = y / (size - 1)
        color = lerp_color(top, bottom, t)
        for x in range(size):
            px[x, y] = (*color, 255)
    return image


def solid_fill(size: int, color: tuple[int, int, int], alpha: int) -> Image.Image:
    return Image.new("RGBA", (size, size), (*color, alpha))


def radial_glow(size: int, color: tuple[int, int, int], radius: float, opacity: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx = cy = size / 2
    for step in range(14, -1, -1):
        t = step / 14
        alpha = int(opacity * (t ** 1.8))
        r = radius * (0.28 + 0.72 * t)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, alpha))
    return image.filter(ImageFilter.GaussianBlur(radius=18))


def offset_mask(mask: Image.Image, dx: int = 0, dy: int = 0) -> Image.Image:
    shifted = ImageChops.offset(mask, dx, dy)
    width, height = mask.size
    clear = Image.new("L", mask.size, 0)
    if dx > 0:
        shifted.paste(clear.crop((0, 0, dx, height)), (0, 0))
    elif dx < 0:
        shifted.paste(clear.crop((0, 0, -dx, height)), (width + dx, 0))
    if dy > 0:
        shifted.paste(clear.crop((0, 0, width, dy)), (0, 0))
    elif dy < 0:
        shifted.paste(clear.crop((0, 0, width, -dy)), (0, height + dy))
    return shifted


def build_cloud_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((162, 420, 434, 700), fill=255)
    draw.ellipse((248, 244, 548, 534), fill=255)
    draw.ellipse((456, 236, 776, 548), fill=255)
    draw.ellipse((640, 396, 848, 680), fill=255)
    draw.rounded_rectangle((252, 438, 752, 728), radius=144, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(4))


def build_master_logo() -> Image.Image:
    size = MASTER_SIZE
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    frame_mask = Image.new("L", (size, size), 0)
    frame_draw = ImageDraw.Draw(frame_mask)
    frame_draw.rounded_rectangle((208, 260, 816, 764), radius=148, fill=255)

    inner_mask = Image.new("L", (size, size), 0)
    inner_draw = ImageDraw.Draw(inner_mask)
    inner_draw.rounded_rectangle((262, 314, 762, 710), radius=102, fill=255)

    border_mask = ImageChops.subtract(frame_mask, inner_mask)

    shadow = Image.composite(
        solid_fill(size, (7, 16, 34), 70),
        Image.new("RGBA", (size, size), (0, 0, 0, 0)),
        offset_mask(frame_mask, dy=20).filter(ImageFilter.GaussianBlur(22)),
    )
    icon = Image.alpha_composite(icon, shadow)

    panel_gradient = vertical_gradient(size, (52, 79, 148), (22, 39, 86))
    panel_glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    panel_glow.alpha_composite(radial_glow(size, (188, 218, 255), 220, 108), dest=(-64, -118))
    panel_glow.alpha_composite(radial_glow(size, (104, 146, 255), 240, 96), dest=(112, 64))
    panel = Image.alpha_composite(panel_gradient, panel_glow)
    icon = Image.alpha_composite(
        icon,
        Image.composite(panel, Image.new("RGBA", (size, size), (0, 0, 0, 0)), frame_mask),
    )

    border = Image.composite(
        solid_fill(size, (244, 249, 255), 238),
        Image.new("RGBA", (size, size), (0, 0, 0, 0)),
        border_mask.filter(ImageFilter.GaussianBlur(1)),
    )
    icon = Image.alpha_composite(icon, border)

    inner_panel = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner_panel_draw = ImageDraw.Draw(inner_panel)
    inner_panel_draw.rounded_rectangle((278, 330, 746, 694), radius=88, fill=(9, 18, 42, 108))
    inner_panel_draw.rounded_rectangle((278, 330, 746, 694), radius=88, outline=(235, 244, 255, 34), width=4)
    icon = Image.alpha_composite(icon, inner_panel)

    gloss = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gloss_draw = ImageDraw.Draw(gloss)
    gloss_draw.rounded_rectangle((236, 286, 788, 470), radius=118, fill=(255, 255, 255, 34))
    icon.alpha_composite(gloss.filter(ImageFilter.GaussianBlur(24)))

    glyph = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glyph_draw = ImageDraw.Draw(glyph)
    glyph_draw.line((408, 426, 496, 512, 408, 598), fill=(250, 252, 255, 250), width=38, joint="curve")
    glyph_draw.rounded_rectangle((550, 558, 654, 592), radius=17, fill=(250, 252, 255, 250))
    icon.alpha_composite(glyph.filter(ImageFilter.GaussianBlur(0.4)))

    return icon


def build_tray_logo(size: int = TRAY_ICON_SIZE) -> Image.Image:
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)

    border = max(2, size // 14)
    outer = (
        int(size * 0.12),
        int(size * 0.2),
        int(size * 0.88),
        int(size * 0.8),
    )
    radius = max(6, size // 6)
    color = (0, 0, 0, 255)

    draw.rounded_rectangle(outer, radius=radius, outline=color, width=border)

    chevron = [
        (int(size * 0.36), int(size * 0.38)),
        (int(size * 0.48), int(size * 0.5)),
        (int(size * 0.36), int(size * 0.62)),
    ]
    draw.line(chevron, fill=color, width=max(3, size // 12), joint="curve")

    underscore = (
        int(size * 0.58),
        int(size * 0.58),
        int(size * 0.74),
        int(size * 0.58),
    )
    draw.line(underscore, fill=color, width=max(3, size // 12))

    return icon


def export_logo_assets() -> None:
    master = build_master_logo()
    for filename, size in EXPORTS.items():
        master.resize((size, size), Image.Resampling.LANCZOS).save(ROOT / filename)
    build_tray_logo().save(ROOT / "tray-icon.png")


if __name__ == "__main__":
    export_logo_assets()
