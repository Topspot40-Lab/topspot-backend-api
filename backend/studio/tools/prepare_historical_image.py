from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from backend.studio.historical_assets import (
    historical_directories_for_production,
)
from backend.studio.production import Production
from backend.studio.studio_config import (
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def find_historical_image(
    *,
    historical_dir: Path,
    requested_name: str,
) -> Path:
    requested = historical_dir / requested_name

    if requested.exists():
        return requested

    matches = [
        path
        for path in historical_dir.iterdir()
        if path.is_file()
        and path.stem == Path(requested_name).stem
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if len(matches) == 1:
        return matches[0]

    raise FileNotFoundError(
        f"Historical image not found: {requested}"
    )


def prepare_contain(source: Image.Image) -> Image.Image:
    """
    Preserve the complete historical photograph.

    A softly blurred version fills the widescreen background,
    while the uncropped original is centered in front.
    """
    background = ImageOps.fit(
        source,
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    background = background.filter(
        ImageFilter.GaussianBlur(radius=22)
    )

    # Darken the blurred background so the original remains dominant.
    dark_overlay = Image.new(
        "RGB",
        background.size,
        (0, 0, 0),
    )

    background = Image.blend(
        background,
        dark_overlay,
        0.38,
    )

    foreground = ImageOps.contain(
        source,
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        method=Image.Resampling.LANCZOS,
    )

    x = (VIDEO_WIDTH - foreground.width) // 2
    y = (VIDEO_HEIGHT - foreground.height) // 2

    background.paste(
        foreground,
        (x, y),
    )

    return background



def prepare_portrait_zoom(source: Image.Image) -> Image.Image:
    """
    Enlarge a portrait-oriented image by 25 percent for a stronger
    documentary presentation. A small amount may be cropped at the
    top and bottom.
    """
    background = ImageOps.fit(
        source,
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    background = background.filter(
        ImageFilter.GaussianBlur(radius=22)
    )

    dark_overlay = Image.new(
        "RGB",
        background.size,
        (0, 0, 0),
    )

    background = Image.blend(
        background,
        dark_overlay,
        0.38,
    )

    contained = ImageOps.contain(
        source,
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        method=Image.Resampling.LANCZOS,
    )

    zoomed_width = round(contained.width * 1.25)
    zoomed_height = round(contained.height * 1.25)

    foreground = contained.resize(
        (zoomed_width, zoomed_height),
        Image.Resampling.LANCZOS,
    )

    x = (VIDEO_WIDTH - foreground.width) // 2
    y = (VIDEO_HEIGHT - foreground.height) // 2

    background.paste(
        foreground,
        (x, y),
    )

    return background

def prepare_cover(source: Image.Image) -> Image.Image:
    """
    Fill the widescreen frame by cropping evenly from the edges.
    """
    return ImageOps.fit(
        source,
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def backup_ai_image(
    *,
    current_image: Path,
    backup_image: Path,
) -> None:
    if not current_image.exists():
        return

    if backup_image.exists():
        return

    backup_image.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        current_image,
        backup_image,
    )

    print(f"✓ AI original preserved: {backup_image}")


def restore_ai_image(
    *,
    current_image: Path,
    backup_image: Path,
) -> None:
    if not backup_image.exists():
        raise FileNotFoundError(
            f"No preserved AI image found: {backup_image}"
        )

    shutil.copy2(
        backup_image,
        current_image,
    )

    print(f"✅ AI image restored: {current_image}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a historical image for a TopSpot Studio scene."
        )
    )

    parser.add_argument(
        "--slug",
        required=True,
    )

    parser.add_argument(
        "--scene",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--image",
        help=(
            "Filename from the production's "
            "historical photos directory."
        ),
    )

    parser.add_argument(
        "--mode",
        choices=["contain", "portrait", "cover"],
        default="contain",
        help=(
            "contain preserves the complete photograph; "
            "portrait enlarges it by 25 percent; "
            "cover fills 16:9 by cropping."
        ),
    )

    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore the preserved AI image for this scene.",
    )

    args = parser.parse_args()

    production = Production(args.slug)
    production.ensure_work_dirs()

    scene_name = f"{args.scene:03d}.png"

    images_dir = production.work_root / "images"
    current_image = images_dir / scene_name

    backup_image = (
        production.work_root
        / "images"
        / "ai_originals"
        / scene_name
    )

    if args.restore:
        restore_ai_image(
            current_image=current_image,
            backup_image=backup_image,
        )
        return

    if not args.image:
        raise SystemExit(
            "--image is required unless --restore is used."
        )

    historical_dir = (
        historical_directories_for_production(
            production
        ).photos
    )

    if not historical_dir.exists():
        raise FileNotFoundError(
            f"Historical folder not found: {historical_dir}"
        )

    source_path = find_historical_image(
        historical_dir=historical_dir,
        requested_name=args.image,
    )

    backup_ai_image(
        current_image=current_image,
        backup_image=backup_image,
    )

    with Image.open(source_path) as opened:
        source = opened.convert("RGB")

        if args.mode == "cover":
            prepared = prepare_cover(source)
        else:
            prepared = prepare_contain(source)

        images_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        prepared.save(
            current_image,
            format="PNG",
            optimize=True,
        )

    print()
    print("✅ Historical scene prepared")
    print(f"Source: {source_path}")
    print(f"Scene:  {args.scene}")
    print(f"Mode:   {args.mode}")
    print(f"Output: {current_image}")
    print(
        f"Size:   {VIDEO_WIDTH}×{VIDEO_HEIGHT}"
    )


if __name__ == "__main__":
    main()
