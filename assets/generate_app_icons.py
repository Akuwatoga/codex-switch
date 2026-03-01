#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from generate_logo_master import build_master_logo, build_tray_logo


ROOT = Path(__file__).resolve().parents[1]
ICONS_DIR = ROOT / "codex-tauri-app" / "src-tauri" / "icons"
ASSETS_DIR = ROOT / "assets"


TOP_LEVEL_PNGS = {
    "32x32.png": 32,
    "64x64.png": 64,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 1024,
    "Square30x30Logo.png": 30,
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square89x89Logo.png": 89,
    "Square107x107Logo.png": 107,
    "Square142x142Logo.png": 142,
    "Square150x150Logo.png": 150,
    "Square284x284Logo.png": 284,
    "Square310x310Logo.png": 310,
    "StoreLogo.png": 50,
}


def resize_icon(master, size: int):
    return master.resize((size, size), Image.Resampling.LANCZOS)


def save_pngs(master) -> None:
    for filename, size in TOP_LEVEL_PNGS.items():
        resize_icon(master, size).save(ICONS_DIR / filename)


def save_ico(master) -> None:
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ICONS_DIR / "icon.ico", format="ICO", sizes=icon_sizes)


def save_icns(master) -> None:
    iconset_dir = ICONS_DIR / "app.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True)

    iconset_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    for filename, size in iconset_sizes.items():
        resize_icon(master, size).save(iconset_dir / filename)

    master.save(ICONS_DIR / "icon.icns", format="ICNS")
    shutil.rmtree(iconset_dir)


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    master = build_master_logo()
    master.save(ASSETS_DIR / "icon-preview-transparent.png")
    build_tray_logo().save(ASSETS_DIR / "tray-icon.png")
    build_tray_logo().save(ICONS_DIR / "tray-icon.png")
    master.save(ICONS_DIR / "icon.png")
    save_pngs(master)
    save_ico(master)
    save_icns(master)


if __name__ == "__main__":
    main()
