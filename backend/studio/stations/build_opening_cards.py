from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from backend.studio.production import Production
from backend.studio.studio_config import (
    ASSETS_DIR,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)


BACKGROUND = (12, 14, 18)
PRIMARY_TEXT = (245, 245, 245)
SECONDARY_TEXT = (190, 194, 202)
ACCENT_TEXT = (225, 185, 70)


def font_candidates(*names: str) -> list[Path]:
    windows_fonts = Path("C:/Windows/Fonts")

    return [
        windows_fonts / name
        for name in names
    ] + [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]


def load_font(
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        ("arialbd.ttf", "calibrib.ttf", "segoeuib.ttf")
        if bold
        else ("arial.ttf", "calibri.ttf", "segoeui.ttf")
    )

    for candidate in font_candidates(*names):
        if candidate.exists():
            return ImageFont.truetype(
                str(candidate),
                size=size,
            )

    return ImageFont.load_default()


def text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    y: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]

    x = (VIDEO_WIDTH - width) // 2

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
    )

    return y + height


def fit_font(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    starting_size: int,
    maximum_width: int,
    bold: bool = True,
    minimum_size: int = 44,
) -> ImageFont.ImageFont:
    size = starting_size

    while size >= minimum_size:
        font = load_font(size, bold=bold)

        if text_width(draw, text, font) <= maximum_width:
            return font

        size -= 4

    return load_font(minimum_size, bold=bold)


def create_canvas() -> Image.Image:
    return Image.new(
        "RGB",
        (VIDEO_WIDTH, VIDEO_HEIGHT),
        BACKGROUND,
    )


def save_card(
    image: Image.Image,
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary = destination.with_suffix(".png.tmp")

    image.save(
        temporary,
        format="PNG",
        optimize=True,
    )

    temporary.replace(destination)


def add_footer(
    draw: ImageDraw.ImageDraw,
    website: str,
) -> None:
    font = load_font(34)

    draw_centered_text(
        draw,
        text=website,
        y=VIDEO_HEIGHT - 92,
        font=font,
        fill=SECONDARY_TEXT,
    )


def build_logo_card(
    production: Production,
    destination: Path,
) -> None:
    canvas = create_canvas()
    draw = ImageDraw.Draw(canvas)

    logo_path = ASSETS_DIR / "old_dog_new_tracks.png"

    if logo_path.exists():
        with Image.open(logo_path) as source:
            logo = source.convert("RGBA")

            maximum_width = 1_180
            maximum_height = 650

            scale = min(
                maximum_width / logo.width,
                maximum_height / logo.height,
                1.0,
            )

            size = (
                max(1, round(logo.width * scale)),
                max(1, round(logo.height * scale)),
            )

            logo = logo.resize(
                size,
                Image.Resampling.LANCZOS,
            )

            x = (VIDEO_WIDTH - logo.width) // 2
            y = 145

            canvas.paste(
                logo,
                (x, y),
                logo,
            )
    else:
        title_font = load_font(112, bold=True)

        draw_centered_text(
            draw,
            text="TopSpot40",
            y=310,
            font=title_font,
            fill=PRIMARY_TEXT,
        )

    program_font = load_font(54, bold=True)

    draw_centered_text(
        draw,
        text="Music Docuseries",
        y=815,
        font=program_font,
        fill=ACCENT_TEXT,
    )

    add_footer(
        draw,
        production.documentary.subtitle
        and production.manifest.get("website", "TopSpot40.com")
        or "TopSpot40.com",
    )

    save_card(canvas, destination)


def language_display_name(code: str) -> str:
    return {
        "en": "English",
        "es": "Español",
        "pt-BR": "Português (Brasil)",
    }.get(code, code)


def build_languages_card(
    production: Production,
    destination: Path,
) -> None:
    canvas = create_canvas()
    draw = ImageDraw.Draw(canvas)

    heading_font = load_font(76, bold=True)
    language_font = load_font(64)

    y = 205

    y = draw_centered_text(
        draw,
        text="Available in",
        y=y,
        font=heading_font,
        fill=ACCENT_TEXT,
    )

    y += 90

    for code in production.documentary.language_codes():
        y = draw_centered_text(
            draw,
            text=language_display_name(code),
            y=y,
            font=language_font,
            fill=PRIMARY_TEXT,
        )
        y += 52

    add_footer(
        draw,
        production.manifest.get(
            "website",
            "TopSpot40.com",
        ),
    )

    save_card(canvas, destination)


def wrap_subtitle(
    draw: ImageDraw.ImageDraw,
    *,
    subtitle: str,
    font: ImageFont.ImageFont,
    maximum_width: int,
) -> list[str]:
    words = subtitle.split()

    if not words:
        return []

    lines: list[str] = []
    current: list[str] = []

    for word in words:
        trial = " ".join(current + [word])

        if current and text_width(draw, trial, font) > maximum_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)

    if current:
        lines.append(" ".join(current))

    return lines


def build_title_card(
    production: Production,
    destination: Path,
) -> None:
    canvas = create_canvas()
    draw = ImageDraw.Draw(canvas)

    documentary = production.documentary

    title_font = fit_font(
        draw,
        text=documentary.title,
        starting_size=118,
        maximum_width=1_600,
        bold=True,
    )

    subtitle_font = load_font(60)

    title_box = draw.textbbox(
        (0, 0),
        documentary.title,
        font=title_font,
    )
    title_height = title_box[3] - title_box[1]

    subtitle_lines = wrap_subtitle(
        draw,
        subtitle=documentary.subtitle,
        font=subtitle_font,
        maximum_width=1_500,
    )

    subtitle_height = len(subtitle_lines) * 82
    total_height = title_height + 78 + subtitle_height

    y = max(
        180,
        (VIDEO_HEIGHT - total_height) // 2,
    )

    y = draw_centered_text(
        draw,
        text=documentary.title,
        y=y,
        font=title_font,
        fill=PRIMARY_TEXT,
    )

    y += 78

    for line in subtitle_lines:
        y = draw_centered_text(
            draw,
            text=line,
            y=y,
            font=subtitle_font,
            fill=ACCENT_TEXT,
        )
        y += 30

    add_footer(
        draw,
        production.manifest.get(
            "website",
            "TopSpot40.com",
        ),
    )

    save_card(canvas, destination)


def save_manifest(
    production: Production,
    payload: dict[str, Any],
) -> None:
    temporary = production.manifest_path.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(production.manifest_path)


def update_production_record(
    production: Production,
) -> None:
    manifest = dict(production.manifest)
    status = dict(manifest.get("status", {}))
    artifacts = dict(manifest.get("artifacts", {}))

    status.update(
        {
            "current_station": "cards_ready",
            "cards_ready": True,
        }
    )

    artifacts["cards"] = [
        "cards/01_logo.png",
        "cards/02_languages.png",
        "cards/03_title.png",
    ]

    manifest["status"] = status
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = datetime.now(UTC).isoformat()

    save_manifest(
        production,
        manifest,
    )


def build_opening_cards(
    *,
    slug: str,
) -> list[Path]:
    production = Production(slug)
    production.ensure_work_dirs()

    destinations = [
        production.card("logo"),
        production.card("languages"),
        production.card("title"),
    ]

    build_logo_card(
        production,
        destinations[0],
    )

    build_languages_card(
        production,
        destinations[1],
    )

    build_title_card(
        production,
        destinations[2],
    )

    update_production_record(production)

    return destinations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the three opening cards for a "
            "TopSpot Studio documentary."
        )
    )

    parser.add_argument(
        "--slug",
        required=True,
        help="Existing production slug, such as casey_kasem.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        production = Production(args.slug)

        print()
        print("Factory Station 6 — Build Opening Cards")
        print(f"Production: {production.documentary.title}")
        print(f"Slug:       {production.slug}")
        print()

        destinations = build_opening_cards(
            slug=args.slug,
        )

    except (
        FileNotFoundError,
        KeyError,
        LookupError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SystemExit(f"❌ {exc}") from exc

    for destination in destinations:
        print(f"✓ {destination}")

    print()
    print("✅ Factory Station 6 complete")
    print("   Current station: cards_ready")


if __name__ == "__main__":
    main()
