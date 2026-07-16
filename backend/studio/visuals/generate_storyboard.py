from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseries,
    MusicDocuseriesLocale,
)
from backend.services.xai_client import ask_xai
from backend.studio.production import Production


def split_sentences(text: str) -> list[str]:
    """
    Split narration into readable sentences while preserving the
    original wording used by the audio narration.
    """
    cleaned = re.sub(r"\s+", " ", text.strip())

    sentences = re.split(
        r"(?<=[.!?])\s+(?=[A-Z0-9“\"'])",
        cleaned,
    )

    return [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]


def get_audio_duration(audio_path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )

    return float(result.stdout.strip())


def load_story(
    slug: str,
    language: str,
) -> tuple[MusicDocuseries, MusicDocuseriesLocale]:
    with Session(engine) as db:
        result = db.exec(
            select(MusicDocuseries, MusicDocuseriesLocale)
            .join(
                MusicDocuseriesLocale,
                MusicDocuseriesLocale.docuseries_id
                == MusicDocuseries.id,
            )
            .where(MusicDocuseries.slug == slug)
            .where(
                MusicDocuseriesLocale.language_code == language
            )
        ).first()

        if not result:
            raise RuntimeError(
                f"No story found for slug={slug!r}, "
                f"language={language!r}"
            )

        return result


def clean_json_response(raw: str) -> Any:
    cleaned = raw.strip()

    cleaned = cleaned.removeprefix("```json")
    cleaned = cleaned.removeprefix("```")
    cleaned = cleaned.removesuffix("```")
    cleaned = cleaned.strip()

    return json.loads(cleaned)


def generate_scene_plan(
    *,
    title: str,
    sentences: list[str],
) -> list[dict[str, Any]]:
    numbered_text = "\n".join(
        f"{index}. {sentence}"
        for index, sentence in enumerate(sentences, start=1)
    )

    prompt = f"""
Create a visual storyboard for a TopSpot40 music documentary.

DOCUMENTARY TITLE:
{title}

The narration has been divided into numbered sentences.

Group the sentences into approximately 36 to 42 story-driven scenes.

Timing guidance:
- Most scenes should contain enough narration for about 10 to 20 seconds.
- Avoid scenes shorter than roughly 7 seconds.
- Avoid scenes longer than roughly 24 seconds.
- Do not isolate a very short sentence as its own scene.
- Split long introductions or long topic sections at a natural sentence boundary.

Rules:
- Every sentence must be included exactly once.
- Keep all sentence ranges continuous and in order.
- Scene 1 must begin with sentence 1.
- The last scene must end with sentence {len(sentences)}.
- Do not skip or repeat any sentence.
- Each scene should represent one clear visual idea.
- Prefer historically grounded documentary visuals.
- Do not request copyrighted logos, captions, or written text.
- Keep visual_prompt concise and suitable for image generation.
- Return valid JSON only.
- No markdown and no commentary.

JSON format:
[
  {{
    "title": "Short scene title",
    "first_sentence": 1,
    "last_sentence": 3,
    "visual_prompt": "Historically grounded documentary image description"
  }}
]

NUMBERED NARRATION:
{numbered_text}
""".strip()

    raw = ask_xai(
        "You create simple, historically grounded visual storyboards "
        "for music documentaries.",
        prompt,
        temperature=0.3,
    )

    data = clean_json_response(raw)

    if not isinstance(data, list):
        raise RuntimeError("XAI response was not a JSON list.")

    return data


def validate_scene_plan(
    scenes: list[dict[str, Any]],
    sentence_count: int,
) -> None:
    expected_first = 1

    for index, scene in enumerate(scenes, start=1):
        first_sentence = int(scene["first_sentence"])
        last_sentence = int(scene["last_sentence"])

        if first_sentence != expected_first:
            raise RuntimeError(
                f"Scene {index} begins with sentence "
                f"{first_sentence}; expected {expected_first}."
            )

        if last_sentence < first_sentence:
            raise RuntimeError(
                f"Scene {index} has an invalid sentence range."
            )

        expected_first = last_sentence + 1

    if expected_first != sentence_count + 1:
        raise RuntimeError(
            "Storyboard does not include every narration sentence. "
            f"Expected final sentence {sentence_count}."
        )



def rebalance_scene_plan(
    *,
    scene_plan: list[dict[str, Any]],
    sentences: list[str],
    audio_duration: float,
    min_seconds: float = 7.0,
    max_seconds: float = 24.0,
) -> list[dict[str, Any]]:
    """
    Automatically split overly long scenes and merge overly short scenes.

    Durations are estimated from each scene's share of the narration words.
    Sentence order and complete narration coverage are preserved.
    """
    sentence_word_counts = [
        len(sentence.split())
        for sentence in sentences
    ]

    total_words = sum(sentence_word_counts)

    if total_words == 0:
        raise RuntimeError("Narration contains no words.")

    def duration(scene: dict[str, Any]) -> float:
        first_index = int(scene["first_sentence"]) - 1
        last_index = int(scene["last_sentence"])

        word_count = sum(
            sentence_word_counts[first_index:last_index]
        )

        return audio_duration * word_count / total_words

    def copy_scene(scene: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": str(scene["title"]).strip(),
            "first_sentence": int(scene["first_sentence"]),
            "last_sentence": int(scene["last_sentence"]),
            "visual_prompt": str(scene["visual_prompt"]).strip(),
        }

    scenes = [
        copy_scene(scene)
        for scene in scene_plan
    ]

    # Split scenes that are too long.
    split_scenes: list[dict[str, Any]] = []

    for scene in scenes:
        pending = [scene]

        while pending:
            current = pending.pop(0)

            first_sentence = int(current["first_sentence"])
            last_sentence = int(current["last_sentence"])

            if (
                duration(current) <= max_seconds
                or first_sentence == last_sentence
            ):
                split_scenes.append(current)
                continue

            best_split: int | None = None
            best_score: float | None = None

            for split_after in range(
                first_sentence,
                last_sentence,
            ):
                left = {
                    **current,
                    "last_sentence": split_after,
                }

                right = {
                    **current,
                    "first_sentence": split_after + 1,
                }

                left_duration = duration(left)
                right_duration = duration(right)

                score = abs(left_duration - right_duration)

                # Prefer splits where neither half is extremely short.
                if (
                    left_duration < min_seconds
                    or right_duration < min_seconds
                ):
                    score += 1000.0

                if best_score is None or score < best_score:
                    best_score = score
                    best_split = split_after

            if best_split is None:
                split_scenes.append(current)
                continue

            title = str(current["title"]).strip()

            left = {
                **current,
                "title": f"{title} — Part 1",
                "last_sentence": best_split,
            }

            right = {
                **current,
                "title": f"{title} — Part 2",
                "first_sentence": best_split + 1,
            }

            pending.insert(0, right)
            pending.insert(0, left)

    scenes = split_scenes

    # Merge scenes that are too short.
    index = 0

    while index < len(scenes):
        if len(scenes) == 1:
            break

        current = scenes[index]

        if duration(current) >= min_seconds:
            index += 1
            continue

        candidates: list[tuple[float, str]] = []

        if index > 0:
            previous = scenes[index - 1]
            combined_previous = {
                **previous,
                "last_sentence": current["last_sentence"],
            }
            candidates.append(
                (duration(combined_previous), "previous")
            )

        if index < len(scenes) - 1:
            following = scenes[index + 1]
            combined_following = {
                **following,
                "first_sentence": current["first_sentence"],
            }
            candidates.append(
                (duration(combined_following), "following")
            )

        _, direction = min(
            candidates,
            key=lambda candidate: candidate[0],
        )

        if direction == "previous":
            scenes[index - 1]["last_sentence"] = (
                current["last_sentence"]
            )
            scenes.pop(index)
            index = max(0, index - 1)
        else:
            scenes[index + 1]["first_sentence"] = (
                current["first_sentence"]
            )
            scenes.pop(index)

    # Final safety pass: merging short scenes can recreate a long scene.
    final_scenes: list[dict[str, Any]] = []

    for scene in scenes:
        pending = [scene]

        while pending:
            current = pending.pop(0)

            first_sentence = int(current["first_sentence"])
            last_sentence = int(current["last_sentence"])

            if (
                duration(current) <= max_seconds
                or first_sentence == last_sentence
            ):
                final_scenes.append(current)
                continue

            best_split: int | None = None
            best_score: float | None = None

            for split_after in range(
                first_sentence,
                last_sentence,
            ):
                left = {
                    **current,
                    "last_sentence": split_after,
                }

                right = {
                    **current,
                    "first_sentence": split_after + 1,
                }

                left_duration = duration(left)
                right_duration = duration(right)

                score = abs(left_duration - right_duration)

                if (
                    left_duration < min_seconds
                    or right_duration < min_seconds
                ):
                    score += 1000.0

                if best_score is None or score < best_score:
                    best_score = score
                    best_split = split_after

            if best_split is None:
                final_scenes.append(current)
                continue

            title = str(current["title"]).strip()

            pending.insert(
                0,
                {
                    **current,
                    "title": f"{title} — Part 2",
                    "first_sentence": best_split + 1,
                },
            )

            pending.insert(
                0,
                {
                    **current,
                    "title": f"{title} — Part 1",
                    "last_sentence": best_split,
                },
            )

    return final_scenes

def build_storyboard(
    *,
    scene_plan: list[dict[str, Any]],
    sentences: list[str],
    audio_duration: float,
) -> list[dict[str, Any]]:
    scene_word_counts: list[int] = []

    for scene in scene_plan:
        first_index = int(scene["first_sentence"]) - 1
        last_index = int(scene["last_sentence"])

        narration = " ".join(
            sentences[first_index:last_index]
        )

        scene_word_counts.append(len(narration.split()))

    total_words = sum(scene_word_counts)

    if total_words == 0:
        raise RuntimeError("Narration contains no words.")

    storyboard: list[dict[str, Any]] = []
    current_start = 0.0

    for scene_number, (scene, word_count) in enumerate(
        zip(scene_plan, scene_word_counts),
        start=1,
    ):
        first_index = int(scene["first_sentence"]) - 1
        last_index = int(scene["last_sentence"])

        narration = " ".join(
            sentences[first_index:last_index]
        )

        duration = audio_duration * word_count / total_words

        storyboard.append(
            {
                "scene": scene_number,
                "title": str(scene["title"]).strip(),
                "start_seconds": round(current_start, 3),
                "duration_seconds": round(duration, 3),
                "end_seconds": round(current_start + duration, 3),
                "narration": narration,
                "visual_prompt": str(
                    scene["visual_prompt"]
                ).strip(),
                "image_file": f"{scene_number:03d}.png",
            }
        )

        current_start += duration

    # Make the final scene end exactly at the audio duration.
    storyboard[-1]["end_seconds"] = round(audio_duration, 3)
    storyboard[-1]["duration_seconds"] = round(
        audio_duration - storyboard[-1]["start_seconds"],
        3,
    )

    return storyboard


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    production = Production(args.slug)
    production.ensure_work_dirs()

    item, locale = load_story(
        args.slug,
        args.language,
    )

    story_text = locale.story_text.strip()
    sentences = split_sentences(story_text)

    audio_path = production.audio(args.language)

    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")

    audio_duration = get_audio_duration(audio_path)

    print("🎬 TopSpot40 Studio")
    print(f"Production: {item.title}")
    print(f"Language: {args.language}")
    print(f"Narration sentences: {len(sentences)}")
    print(f"Audio duration: {audio_duration:.3f} seconds")
    print()
    print("Creating automatic story-driven storyboard...")

    scene_plan = generate_scene_plan(
        title=item.title,
        sentences=sentences,
    )

    scene_plan = rebalance_scene_plan(
        scene_plan=scene_plan,
        sentences=sentences,
        audio_duration=audio_duration,
    )

    validate_scene_plan(
        scene_plan,
        len(sentences),
    )

    storyboard = build_storyboard(
        scene_plan=scene_plan,
        sentences=sentences,
        audio_duration=audio_duration,
    )

    output = production.work_root / "storyboard.json"

    payload = {
        "version": 1,
        "slug": args.slug,
        "title": item.title,
        "language_code": args.language,
        "audio_file": str(audio_path),
        "audio_duration_seconds": round(audio_duration, 3),
        "scene_count": len(storyboard),
        "scenes": storyboard,
    }

    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"✅ Storyboard created: {output}")
    print(f"Scenes: {len(storyboard)}")
    print(
        "Storyboard duration:",
        f"{storyboard[-1]['end_seconds']:.3f} seconds",
    )


if __name__ == "__main__":
    main()
