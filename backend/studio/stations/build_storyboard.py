from __future__ import annotations

import argparse
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.studio.production import Production
from backend.studio.studio_config import IMAGE_SECONDS


SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"'])"
)


def save_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(path)


def normalize_story_text(text: str) -> str:
    """
    Normalize database story text while preserving paragraph breaks.

    Removes harmless generator preambles without changing the database.
    """
    cleaned = text.strip()

    preambles = (
        "Here's the narration text:",
        "Here’s the narration text:",
        "Narration text:",
    )

    for preamble in preambles:
        if cleaned.lower().startswith(preamble.lower()):
            cleaned = cleaned[len(preamble):].lstrip()
            break

    paragraphs: list[str] = []

    for raw_paragraph in re.split(r"\n\s*\n", cleaned):
        paragraph = " ".join(raw_paragraph.split())

        if paragraph:
            paragraphs.append(paragraph)

    return "\n\n".join(paragraphs)


def split_sentences(text: str) -> list[str]:
    """
    Split story text at likely sentence boundaries.

    Paragraph boundaries are treated as hard sentence boundaries.
    """
    sentences: list[str] = []

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        parts = SENTENCE_BOUNDARY.split(paragraph)

        for part in parts:
            sentence = part.strip()

            if sentence:
                sentences.append(sentence)

    return sentences


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE))


def split_long_sentence(
    sentence: str,
    *,
    target_words: int = 20,
    max_words: int = 28,
    min_words: int = 10,
) -> list[str]:
    """
    Split a long sentence at natural punctuation or conjunction boundaries.

    The original words and punctuation are preserved.
    """
    if word_count(sentence) <= max_words:
        return [sentence.strip()]

    pieces: list[str] = []
    remaining = sentence.strip()

    while word_count(remaining) > max_words:
        candidates: list[int] = []

        # Strong punctuation can safely divide visual ideas.
        for match in re.finditer(r"[;:—–]\s+", remaining):
            candidates.append(match.end())

        # Split at a comma only when the next clause begins with a
        # strong connector. Avoid ordinary descriptive commas.
        for match in re.finditer(
            r",\s+(?=(?:but|while|after|before|because|although|"
            r"whereas|yet)\b)",
            remaining,
            flags=re.IGNORECASE,
        ):
            candidates.append(match.end())

        valid: list[tuple[int, int]] = []

        for position in candidates:
            left = remaining[:position].strip()
            right = remaining[position:].strip()
            left_words = word_count(left)
            right_words = word_count(right)

            if (
                min_words <= left_words <= max_words
                and right_words >= min_words
            ):
                valid.append(
                    (
                        abs(left_words - target_words),
                        position,
                    )
                )

        if not valid:
            break

        _, best_position = min(valid)
        pieces.append(remaining[:best_position].strip())
        remaining = remaining[best_position:].strip()

    if remaining:
        pieces.append(remaining)

    return pieces


def split_story_units(text: str) -> list[str]:
    """
    Split the story into visual units.

    First use complete sentences. Long sentences are then divided only at
    natural clause boundaries so scenes remain understandable.
    """
    units: list[str] = []

    for sentence in split_sentences(text):
        units.extend(split_long_sentence(sentence))

    return [unit for unit in units if unit.strip()]


def build_scene_chunks(
    sentences: list[str],
    *,
    desired_scene_count: int,
) -> list[str]:
    """
    Group complete sentences into approximately equal-sized scenes.

    The algorithm never intentionally cuts a sentence in half.
    """
    if not sentences:
        raise ValueError("The documentary story contains no sentences.")

    total_words = sum(word_count(sentence) for sentence in sentences)

    if total_words <= 0:
        raise ValueError("The documentary story contains no words.")

    desired_scene_count = max(
        1,
        min(desired_scene_count, len(sentences)),
    )

    target_words = max(
        1.0,
        total_words / desired_scene_count,
    )

    scenes: list[str] = []
    current_sentences: list[str] = []
    current_words = 0

    for index, sentence in enumerate(sentences):
        sentence_words = word_count(sentence)
        sentences_remaining = len(sentences) - index
        scenes_remaining = desired_scene_count - len(scenes)

        should_close_before = (
            current_sentences
            and current_words >= target_words * 0.75
            and scenes_remaining > 1
            and sentences_remaining >= scenes_remaining
        )

        if should_close_before:
            scenes.append(" ".join(current_sentences))
            current_sentences = []
            current_words = 0

        current_sentences.append(sentence)
        current_words += sentence_words

        should_close_after = (
            current_words >= target_words * 1.20
            and len(scenes) < desired_scene_count - 1
        )

        if should_close_after:
            scenes.append(" ".join(current_sentences))
            current_sentences = []
            current_words = 0

    if current_sentences:
        scenes.append(" ".join(current_sentences))

    return scenes


def build_visual_intent_placeholder(
    narration: str,
) -> str:
    """
    Give the later prompt-generation station a concise starting reference.

    This is not the final AI image prompt.
    """
    first_sentence = SENTENCE_BOUNDARY.split(narration.strip(), maxsplit=1)[0]

    if len(first_sentence) <= 180:
        return first_sentence

    shortened = first_sentence[:177].rsplit(" ", 1)[0]
    return shortened + "..."


def build_storyboard_payload(
    production: Production,
) -> dict[str, Any]:
    documentary = production.documentary
    english = documentary.language("en")

    story_text = normalize_story_text(english.story_text)
    sentences = split_story_units(story_text)

    narration_seconds = float(
        english.duration_seconds
        or max(1, round(word_count(story_text) / 2.4))
    )

    desired_scene_count = max(
        1,
        round(narration_seconds / IMAGE_SECONDS),
    )

    chunks = build_scene_chunks(
        sentences,
        desired_scene_count=desired_scene_count,
    )

    scene_word_counts = [
        word_count(chunk)
        for chunk in chunks
    ]
    total_scene_words = sum(scene_word_counts)

    if total_scene_words <= 0:
        raise ValueError("Storyboard scene text contains no words.")

    scenes: list[dict[str, Any]] = []
    elapsed = 0.0
    visual_shot_number = 0

    for index, (chunk, scene_words) in enumerate(
        zip(chunks, scene_word_counts),
        start=1,
    ):
        if index == len(chunks):
            estimated_seconds = max(
                0.1,
                narration_seconds - elapsed,
            )
        else:
            estimated_seconds = (
                narration_seconds
                * scene_words
                / total_scene_words
            )

        start_seconds = elapsed
        end_seconds = min(
            narration_seconds,
            start_seconds + estimated_seconds,
        )
        elapsed = end_seconds

        scene_duration = end_seconds - start_seconds

        # A narration scene is one complete thought, but it may use
        # several visual shots to keep the documentary moving.
        shot_count = max(
            1,
            round(scene_duration / IMAGE_SECONDS),
        )

        shot_duration = scene_duration / shot_count
        visual_shots: list[dict[str, Any]] = []

        for scene_shot_number in range(1, shot_count + 1):
            visual_shot_number += 1

            shot_start = (
                start_seconds
                + ((scene_shot_number - 1) * shot_duration)
            )

            if scene_shot_number == shot_count:
                shot_end = end_seconds
            else:
                shot_end = shot_start + shot_duration

            visual_shots.append(
                {
                    "shot_number": visual_shot_number,
                    "scene_shot_number": scene_shot_number,
                    "filename": f"{visual_shot_number:03d}.png",
                    "start_seconds": round(shot_start, 3),
                    "end_seconds": round(shot_end, 3),
                    "estimated_seconds": round(
                        shot_end - shot_start,
                        3,
                    ),
                    "visual_intent": (
                        build_visual_intent_placeholder(chunk)
                    ),
                    "source": "ai",
                    "historical_asset": None,
                    "prompt": None,
                    "status": "needs_prompt",
                    "approved": False,
                    "review_notes": "",
                }
            )

        scenes.append(
            {
                "scene_number": index,
                "narration": chunk,
                "word_count": scene_words,
                "start_seconds": round(start_seconds, 3),
                "end_seconds": round(end_seconds, 3),
                "estimated_seconds": round(
                    scene_duration,
                    3,
                ),
                "visual_intent": build_visual_intent_placeholder(
                    chunk
                ),
                "visual_shot_count": shot_count,
                "visual_shots": visual_shots,
                "review_notes": "",
            }
        )

    return {
        "version": 1,
        "production_slug": production.slug,
        "source": {
            "type": documentary.source_type,
            "id": documentary.source_id,
            "language_code": "en",
            "locale_id": english.locale_id,
        },
        "title": documentary.title,
        "subtitle": documentary.subtitle,
        "narration_duration_seconds": narration_seconds,
        "target_image_seconds": IMAGE_SECONDS,
        "scene_count": len(scenes),
        "visual_shot_count": visual_shot_number,
        "created_at": datetime.now(UTC).isoformat(),
        "scenes": scenes,
    }


def update_production_record(
    production: Production,
    *,
    scene_count: int,
) -> None:
    manifest = dict(production.manifest)
    status = dict(manifest.get("status", {}))
    artifacts = dict(manifest.get("artifacts", {}))

    status.update(
        {
            "current_station": "storyboard_ready",
            "storyboard_ready": True,
            "images_ready": False,
            "image_review_complete": False,
        }
    )

    artifacts.update(
        {
            "storyboard": "storyboard.json",
            "storyboard_scene_count": scene_count,
        }
    )

    manifest["status"] = status
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = datetime.now(UTC).isoformat()

    temporary_path = production.manifest_path.with_suffix(
        ".json.tmp"
    )

    temporary_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(production.manifest_path)


def build_storyboard(
    *,
    slug: str,
    refresh: bool,
) -> Path:
    production = Production(slug)
    storyboard_path = (
        production.production_root / "storyboard.json"
    )

    if storyboard_path.exists() and not refresh:
        try:
            existing = json.loads(
                storyboard_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            existing = {}

        existing_scenes = existing.get("scenes", [])

        if existing_scenes:
            raise FileExistsError(
                f"Storyboard already contains "
                f"{len(existing_scenes)} scene(s): {storyboard_path}\n"
                "Use --refresh to rebuild it from the database story."
            )

    payload = build_storyboard_payload(production)

    save_json_atomic(
        storyboard_path,
        payload,
    )

    update_production_record(
        production,
        scene_count=payload["scene_count"],
    )

    return storyboard_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic scene storyboard from an "
            "existing TopSpot documentary story."
        )
    )

    parser.add_argument(
        "--slug",
        required=True,
        help="Existing production slug, such as casey_kasem.",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Replace an existing populated storyboard from the "
            "current database story."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        production = Production(args.slug)

        print()
        print("Factory Station 3 — Build Storyboard")
        print(f"Production: {production.documentary.title}")
        print(f"Slug:       {production.slug}")
        print(
            f"Target:     approximately one scene every "
            f"{IMAGE_SECONDS:g} seconds"
        )
        print()

        storyboard_path = build_storyboard(
            slug=args.slug,
            refresh=args.refresh,
        )

        payload = json.loads(
            storyboard_path.read_text(encoding="utf-8")
        )

    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        LookupError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SystemExit(f"❌ {exc}") from exc

    print(f"✓ Storyboard written: {storyboard_path}")
    print(
        f"✓ Scenes created: "
        f"{payload['scene_count']}"
    )
    print(
        f"✓ Narration duration: "
        f"{payload['narration_duration_seconds']:.1f} seconds"
    )
    print()
    print("✅ Factory Station 3 complete")
    print("   Current station: storyboard_ready")
    print("   No image prompts or images generated yet.")


if __name__ == "__main__":
    main()
