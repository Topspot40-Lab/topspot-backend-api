from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class ImageQASummary:
    production: str
    total_images: int
    passed: int
    below_threshold: int
    regenerated: int
    average_score: float
    highest_score: int
    lowest_score: int
    average_brightness: float
    average_contrast: float
    average_sharpness: float
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid Image QA report: {path}"
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"Image QA report must be a JSON object: {path}"
        )

    return payload


def _selected_quality(
    report: dict[str, Any],
) -> dict[str, Any]:
    selected_attempt = int(
        report.get("selected_attempt") or 1
    )

    attempts = report.get("attempts") or []

    for attempt in attempts:
        if int(attempt.get("attempt") or 0) == selected_attempt:
            quality = attempt.get("quality") or {}

            if isinstance(quality, dict):
                return quality

    return {}


def build_image_qa_summary(
    *,
    production_slug: str,
    qa_root: Path,
) -> ImageQASummary:
    report_paths = sorted(
        path
        for path in qa_root.glob("*.json")
        if path.name != "summary.json"
    )

    reports = [
        _load_report(path)
        for path in report_paths
    ]

    if not reports:
        return ImageQASummary(
            production=production_slug,
            total_images=0,
            passed=0,
            below_threshold=0,
            regenerated=0,
            average_score=0.0,
            highest_score=0,
            lowest_score=0,
            average_brightness=0.0,
            average_contrast=0.0,
            average_sharpness=0.0,
            generated_at=datetime.now(UTC).isoformat(),
        )

    scores = [
        int(report.get("final_score") or 0)
        for report in reports
    ]

    passed = sum(
        1
        for report in reports
        if bool(report.get("passed"))
    )

    regenerated = sum(
        1
        for report in reports
        if int(report.get("attempt_count") or 1) > 1
    )

    qualities = [
        _selected_quality(report)
        for report in reports
    ]

    brightness_values = [
        float(quality.get("brightness") or 0.0)
        for quality in qualities
    ]

    contrast_values = [
        float(quality.get("contrast") or 0.0)
        for quality in qualities
    ]

    sharpness_values = [
        float(quality.get("sharpness") or 0.0)
        for quality in qualities
    ]

    return ImageQASummary(
        production=production_slug,
        total_images=len(reports),
        passed=passed,
        below_threshold=len(reports) - passed,
        regenerated=regenerated,
        average_score=round(mean(scores), 1),
        highest_score=max(scores),
        lowest_score=min(scores),
        average_brightness=round(
            mean(brightness_values),
            1,
        ),
        average_contrast=round(
            mean(contrast_values),
            1,
        ),
        average_sharpness=round(
            mean(sharpness_values),
            1,
        ),
        generated_at=datetime.now(UTC).isoformat(),
    )


def write_image_qa_summary(
    *,
    production_slug: str,
    qa_root: Path,
) -> ImageQASummary:
    qa_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary = build_image_qa_summary(
        production_slug=production_slug,
        qa_root=qa_root,
    )

    destination = qa_root / "summary.json"
    temporary = destination.with_suffix(".json.tmp")

    temporary.write_text(
        json.dumps(
            summary.to_dict(),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(destination)

    return summary


def print_image_qa_summary(
    summary: ImageQASummary,
) -> None:
    print()
    print("=" * 56)
    print("Image QA Summary")
    print("=" * 56)
    print(f"Images:          {summary.total_images}")
    print(f"Passed:          {summary.passed}")
    print(f"Below threshold: {summary.below_threshold}")
    print(f"Regenerated:     {summary.regenerated}")
    print(f"Average score:   {summary.average_score:.1f}")
    print(f"Highest score:   {summary.highest_score}")
    print(f"Lowest score:    {summary.lowest_score}")
    print(f"Avg brightness:  {summary.average_brightness:.1f}")
    print(f"Avg contrast:    {summary.average_contrast:.1f}")
    print(f"Avg sharpness:   {summary.average_sharpness:.1f}")
