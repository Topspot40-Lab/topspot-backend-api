from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any


EXPECTED_ASPECT_RATIO = 16 / 9
MIN_WIDTH = 1024
MIN_HEIGHT = 576
PASSING_SCORE = 72


@dataclass(frozen=True)
class ImageQualityResult:
    valid: bool
    passed: bool
    score: int
    width: int
    height: int
    aspect_ratio: float
    brightness: float
    contrast: float
    sharpness: float
    grayscale_score: float
    black_border_score: float
    issues: tuple[str, ...]
    recommendations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = list(self.issues)
        payload["recommendations"] = list(self.recommendations)
        return payload


def _channel_difference_score(image: Any) -> float:
    """
    Return a rough 0-255 estimate of how different the RGB channels are.

    A very small value suggests the image is effectively grayscale.
    """
    from PIL import ImageChops, ImageStat

    red, green, blue = image.split()

    rg = ImageStat.Stat(
        ImageChops.difference(red, green)
    ).mean[0]
    rb = ImageStat.Stat(
        ImageChops.difference(red, blue)
    ).mean[0]
    gb = ImageStat.Stat(
        ImageChops.difference(green, blue)
    ).mean[0]

    return float((rg + rb + gb) / 3.0)


def _sharpness_score(image: Any) -> float:
    """
    Estimate sharpness from edge variation.

    This is intentionally lightweight and avoids OpenCV.
    """
    from PIL import ImageFilter, ImageStat

    grayscale = image.convert("L")
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def _border_darkness(image: Any) -> float:
    """
    Return the fraction of border pixels that are nearly black.
    """
    grayscale = image.convert("L")
    width, height = grayscale.size

    border_size = max(
        2,
        min(width, height) // 50,
    )

    regions = (
        grayscale.crop((0, 0, width, border_size)),
        grayscale.crop(
            (0, height - border_size, width, height)
        ),
        grayscale.crop((0, 0, border_size, height)),
        grayscale.crop(
            (width - border_size, 0, width, height)
        ),
    )

    dark_pixels = 0
    total_pixels = 0

    for region in regions:
        histogram = region.histogram()
        pixel_count = sum(histogram)
        dark_count = sum(histogram[:12])

        dark_pixels += dark_count
        total_pixels += pixel_count

    if total_pixels == 0:
        return 0.0

    return float(dark_pixels / total_pixels)


def evaluate_image_bytes(
    image_bytes: bytes,
) -> ImageQualityResult:
    from PIL import Image, ImageStat

    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            opened.verify()

        with Image.open(BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")

    except Exception as exc:
        return ImageQualityResult(
            valid=False,
            passed=False,
            score=0,
            width=0,
            height=0,
            aspect_ratio=0.0,
            brightness=0.0,
            contrast=0.0,
            sharpness=0.0,
            grayscale_score=0.0,
            black_border_score=0.0,
            issues=(
                f"Image is unreadable or corrupted: {exc}",
            ),
            recommendations=(
                "Generate a complete valid 16:9 image.",
            ),
        )

    width, height = image.size
    aspect_ratio = (
        width / height
        if height
        else 0.0
    )

    grayscale = image.convert("L")
    statistics = ImageStat.Stat(grayscale)

    brightness = float(statistics.mean[0])
    contrast = float(statistics.stddev[0])
    sharpness = _sharpness_score(image)
    grayscale_score = _channel_difference_score(image)
    black_border_score = _border_darkness(image)

    issues: list[str] = []
    recommendations: list[str] = []
    score = 100

    if width < MIN_WIDTH or height < MIN_HEIGHT:
        issues.append(
            f"Resolution is only {width}x{height}."
        )
        recommendations.append(
            "Generate a higher-resolution widescreen image."
        )
        score -= 30

    aspect_error = abs(
        aspect_ratio - EXPECTED_ASPECT_RATIO
    )

    if aspect_error > 0.08:
        issues.append(
            f"Aspect ratio is {aspect_ratio:.3f}, not close to 16:9."
        )
        recommendations.append(
            "Generate a true 16:9 widescreen composition."
        )
        score -= 30

    if brightness < 35:
        issues.append("Image is extremely dark.")
        recommendations.append(
            "Increase natural subject lighting and visible detail."
        )
        score -= 25

    elif brightness < 55:
        issues.append("Image may be too dark.")
        recommendations.append(
            "Increase exposure slightly while preserving atmosphere."
        )
        score -= 12

    elif brightness > 225:
        issues.append("Image is severely overexposed.")
        recommendations.append(
            "Reduce highlights and restore visible detail."
        )
        score -= 25

    elif brightness > 205:
        issues.append("Image may be too bright.")
        recommendations.append(
            "Reduce exposure and preserve highlight detail."
        )
        score -= 10

    if contrast < 18:
        issues.append("Image has very low contrast.")
        recommendations.append(
            "Add clearer tonal separation and dimensional lighting."
        )
        score -= 18

    elif contrast < 28:
        issues.append("Image may appear flat.")
        recommendations.append(
            "Improve tonal contrast and subject separation."
        )
        score -= 8

    if sharpness < 45:
        issues.append("Image appears very soft or blurry.")
        recommendations.append(
            "Generate sharper facial features and scene details."
        )
        score -= 22

    elif sharpness < 80:
        issues.append("Image may be somewhat soft.")
        recommendations.append(
            "Increase clarity and fine-detail definition."
        )
        score -= 8

    if grayscale_score < 1.5:
        issues.append(
            "Image appears almost entirely grayscale."
        )
        recommendations.append(
            "Use rich natural color unless monochrome is essential."
        )
        score -= 8

    if black_border_score > 0.75:
        issues.append(
            "Large black borders or letterboxing may be present."
        )
        recommendations.append(
            "Fill the complete 16:9 frame without black borders."
        )
        score -= 25

    elif black_border_score > 0.40:
        issues.append(
            "Dark borders may occupy too much of the frame."
        )
        recommendations.append(
            "Use more of the full widescreen canvas."
        )
        score -= 10

    score = max(0, min(100, round(score)))

    return ImageQualityResult(
        valid=True,
        passed=score >= PASSING_SCORE,
        score=score,
        width=width,
        height=height,
        aspect_ratio=aspect_ratio,
        brightness=brightness,
        contrast=contrast,
        sharpness=sharpness,
        grayscale_score=grayscale_score,
        black_border_score=black_border_score,
        issues=tuple(issues),
        recommendations=tuple(recommendations),
    )


def build_corrective_prompt(
    original_prompt: str,
    quality: ImageQualityResult,
) -> str:
    if not quality.recommendations:
        return original_prompt

    corrections = " ".join(
        f"- {recommendation}"
        for recommendation in quality.recommendations
    )

    return (
        f"{original_prompt}\n\n"
        "IMPORTANT CORRECTIONS FOR THIS NEW ATTEMPT:\n"
        f"{corrections}\n"
        "Do not reproduce defects from the previous attempt."
    )
