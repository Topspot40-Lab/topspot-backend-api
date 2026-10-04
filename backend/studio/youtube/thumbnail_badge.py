"""Consistent language badges for TopSpot40 YouTube thumbnails."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

STYLES = {
    "en": ("ENGLISH", "#1557A6"),
    "es": ("ESPAÑOL", "#B31B24"),
    "pt-BR": ("PORTUGUÊS", "#146B3A"),
}

def save_language_thumbnail(source, destination, language, top_fraction=.25):
    if language not in STYLES:
        raise ValueError(f"Unsupported thumbnail language: {language}")
    if isinstance(source, Image.Image):
        image = source.convert("RGB")
    else:
        with Image.open(source) as original:
            image = original.convert("RGB")

    label, color = STYLES[language]
    w, h = image.size
    size = max(20, round(w * .045))
    font = None
    for path in (
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ):
        if path.is_file():
            font = ImageFont.truetype(str(path), size=size)
            break
    if font is None:
        raise RuntimeError("A bold TrueType font is required for language badges.")

    draw = ImageDraw.Draw(image)
    bounds = draw.textbbox((0, 0), label, font=font)
    pad = round(w * .016)
    bw = bounds[2] - bounds[0] + pad * 2
    bh = bounds[3] - bounds[1] + pad * 2
    x, y = w - bw - pad, round(h * top_fraction)
    if x < 0 or y < 0 or y + bh > h:
        raise ValueError("Language badge does not fit the thumbnail.")
    draw.rounded_rectangle(
        (x, y, x + bw, y + bh),
        radius=round(w * .008), fill=color,
        outline="white", width=max(2, round(w * .002))
    )
    draw.text(
        (x + pad - bounds[0], y + pad - bounds[1]),
        label, font=font, fill="white"
    )

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() in (".jpg", ".jpeg"):
        image.save(destination, quality=95)
    elif destination.suffix.lower() == ".png":
        image.save(destination, optimize=True)
        if destination.stat().st_size >= 2097152:
            image.quantize(colors=256).save(destination, optimize=True)
    else:
        raise ValueError("Thumbnail destination must be JPEG or PNG.")
    if destination.stat().st_size >= 2097152:
        raise RuntimeError(f"Thumbnail exceeds 2 MiB: {destination}")
