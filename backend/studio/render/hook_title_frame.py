"""Localized widescreen hook artwork; narration and program timing stay unchanged."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from backend.studio.youtube.publishing_package import LOCALIZED_TITLES, DOCUMENTARY_LABELS

LAYOUT_VERSION = "widescreen-title-v1"
SIZE = (1920, 1080)


def localized_title(production, language: str) -> str:
    manifest = getattr(production, "manifest", {})
    override = manifest.get("hook_titles", {}).get(language)
    slug = manifest.get("slug") or getattr(production, "slug", "")
    title = override or LOCALIZED_TITLES.get(slug, {}).get(language)
    if not title and language == "en":
        title = ": ".join(str(manifest.get(k) or getattr(production, k, "") or "").strip()
                          for k in ("title", "subtitle") if manifest.get(k) or getattr(production, k, ""))
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Add an approved hook_titles.{language} title to the production manifest for {slug}")
    return title.strip()


def font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    raise RuntimeError("Install DejaVu Sans or Arial Bold to render multilingual hook titles")


def title_lines(draw, text: str):
    # Fit at most two lines; never clip long translated titles.
    for size in range(72, 23, -1):
        face = font(size)
        lines = [""]
        for word in text.split():
            candidate = (lines[-1] + " " + word).strip()
            if draw.textbbox((0, 0), candidate, font=face)[2] > 1770:
                lines.append(word)
            else:
                lines[-1] = candidate
        if len(lines) <= 2 and all(draw.textbbox((0, 0), line, font=face)[2] <= 1770 for line in lines):
            return lines, face, size + 14
    raise ValueError("Hook title is too long; supply a shorter approved hook_titles title")


def render_hook_title_frame(source: Path, output: Path, *, title: str, language: str) -> Path:
    label = DOCUMENTARY_LABELS[language]
    with Image.open(source) as image:
        original = ImageOps.exif_transpose(image).convert("RGB")
    canvas = Image.new("RGB", SIZE, "#10151e")
    background = ImageOps.fit(original, (1920, 740)).filter(ImageFilter.GaussianBlur(30))
    background = Image.blend(background, Image.new("RGB", background.size, "#10151e"), .5)
    canvas.paste(background, (0, 250))
    # Keep the complete source composition visible, with blurred fill at the sides.
    picture = ImageOps.contain(original, (1920, 740))
    canvas.paste(picture, ((1920-picture.width)//2, 250+(740-picture.height)//2))
    draw = ImageDraw.Draw(canvas)
    lines, face, line_height = title_lines(draw, title)
    y = 30 + (150-len(lines)*line_height)//2
    for line in lines:
        draw.text((960, y), line, font=face, fill="white", anchor="mt")
        y += line_height
    draw.text((960, 190), label.upper(), font=font(30), fill="#e5bb69", anchor="mt")
    draw.line((70, 239, 1850, 239), fill="#b68a42", width=3)
    draw.rounded_rectangle((700, 1002, 1220, 1065), radius=16, fill="#10151e", outline="#b68a42", width=2)
    draw.text((960, 1012), "TopSpot40.com", font=font(40), fill="white", anchor="mt")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.png")
    canvas.save(temporary, format="PNG")
    temporary.replace(output)
    return output
