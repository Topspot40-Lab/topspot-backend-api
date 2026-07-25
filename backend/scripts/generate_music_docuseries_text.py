from __future__ import annotations

import argparse
from pathlib import Path
import re

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseries,
    MusicDocuseriesLocale,
)
from backend.services.xai_client import ask_xai


def normalize_heading(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        value.casefold(),
    )


def clean_story_text(
    value: str,
    *,
    title: str,
) -> str:
    value = value.strip()
    value = (
        value
        .removeprefix("```text")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    value = value.replace("**", "")
    value = re.sub(
        r"\(Word count:.*?\)\s*$",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )

    lines = value.splitlines()

    while lines and not lines[0].strip():
        lines.pop(0)

    if (
        lines
        and normalize_heading(lines[0])
        == normalize_heading(title)
    ):
        lines.pop(0)

    return "\n".join(lines).strip()


def build_prompt(
    title: str,
    target_length: str,
) -> str:
    return f"""
Create a TopSpot Music Docuseries narration script.

TITLE:
{title}

TARGET LENGTH:
{target_length}

RULES:
- English only
- Warm, engaging, audio-first storytelling
- Write like a music documentary narrator
- Do not sound like Wikipedia
- Include cultural context and memorable verified examples
- Remain historically accurate
- Do not invent quotations, scenes, people, statistics, or anecdotes
- Distinguish documented history from legend or disputed accounts
- Acknowledge uncertainty when historical accounts conflict
- Avoid unsupported claims about recent events
- Avoid sweeping statements presented as established fact
- Make it suitable for older listeners, music fans, libraries,
  and assisted-living audiences
- Use natural paragraphs
- End with a satisfying closing thought
- Do not include markdown
- Do not include headings
- Do not include bullet points
- Do not include the documentary title
- Do not mention TopSpot
- Do not include a word count
- Do not include notes to the editor
- Return only the narration text

Approximate length:
- short: 700-900 words
- standard: 1200-1400 words
- feature: 1800-2200 words
""".strip()


def print_story(
    *,
    title: str,
    story_text: str,
    source: str,
) -> None:
    print("=" * 80)
    print(title)
    print("=" * 80)
    print(story_text)
    print("=" * 80)
    print(f"Words:  {len(story_text.split())}")
    print(f"Chars:  {len(story_text)}")
    print(f"Source: {source}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the generated preview to this text file.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Read reviewed text from this file.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save reviewed --input text to the database.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output or database text.",
    )
    args = parser.parse_args()

    if args.language != "en":
        raise SystemExit(
            "This script generates English only. "
            "Use generate_music_docuseries_locale "
            "for translations."
        )

    if args.input and args.output:
        raise SystemExit(
            "Use --input or --output, not both."
        )

    if args.save and not args.input:
        raise SystemExit(
            "--save requires --input so only reviewed text "
            "can be written to the database."
        )

    with Session(engine) as session:
        item = session.exec(
            select(MusicDocuseries).where(
                MusicDocuseries.slug == args.slug
            )
        ).first()

        if not item:
            raise SystemExit(
                f"Docuseries item not found: {args.slug}"
            )

        locale = session.exec(
            select(MusicDocuseriesLocale)
            .where(
                MusicDocuseriesLocale.docuseries_id
                == item.id
            )
            .where(
                MusicDocuseriesLocale.language_code
                == args.language
            )
        ).first()

        if (
            locale
            and locale.story_text
            and not args.overwrite
        ):
            raise SystemExit(
                "Existing story text found. "
                "Use --overwrite to replace it."
            )

        if args.input:
            if not args.input.exists():
                raise SystemExit(
                    f"Input file not found: {args.input}"
                )

            story_text = clean_story_text(
                args.input.read_text(encoding="utf-8"),
                title=item.title,
            )
            source = str(args.input)
        else:
            prompt = build_prompt(
                item.title,
                item.target_length or "standard",
            )

            generated_text = ask_xai(
                (
                    "You create warm, engaging, carefully "
                    "researched, factual music documentary "
                    "narration scripts for TopSpot."
                ),
                prompt,
                temperature=0.3,
            )

            story_text = clean_story_text(
                generated_text,
                title=item.title,
            )
            source = "XAI preview"

        if not story_text:
            raise SystemExit("Story text is empty.")

        word_count = len(story_text.split())

        print_story(
            title=item.title,
            story_text=story_text,
            source=source,
        )

        if (
            item.target_length == "standard"
            and not 1200 <= word_count <= 1400
        ):
            print(
                "WARNING: Standard stories should contain "
                "approximately 1,200-1,400 words."
            )

        if args.output:
            if (
                args.output.exists()
                and not args.overwrite
            ):
                raise SystemExit(
                    f"Output already exists: {args.output}. "
                    "Use --overwrite to replace it."
                )

            args.output.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            args.output.write_text(
                story_text + "\n",
                encoding="utf-8",
            )
            print(
                f"Preview written: {args.output}"
            )
            print(
                "Review this exact file, then use "
                "--input with --save."
            )
            return

        if not args.save:
            print("Preview only. No database changes made.")
            return

        if not locale:
            locale = MusicDocuseriesLocale(
                docuseries_id=item.id,
                language_code=args.language,
                story_text=story_text,
            )
        else:
            locale.story_text = story_text
            locale.duration_seconds = None
            locale.tts_bucket = None
            locale.tts_key = None

        session.add(locale)
        session.commit()

        print(
            "Music Docuseries reviewed story text saved."
        )


if __name__ == "__main__":
    main()