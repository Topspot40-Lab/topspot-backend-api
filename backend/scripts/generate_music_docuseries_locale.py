from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import re

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseries,
    MusicDocuseriesLocale,
)
from backend.services.xai_client import ask_xai


SUPPORTED_LANGS = ("es", "pt-BR")


def normalize_language(value: str) -> str:
    if value.lower() in ("pt", "pt-br", "ptbr"):
        return "pt-BR"

    return value.lower()


def language_name(language: str) -> str:
    if language == "es":
        return "natural Mexican Spanish"

    if language == "pt-BR":
        return "natural Brazilian Portuguese"

    return language


def normalize_heading(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        value.casefold(),
    )


def clean_story(
    value: str,
    *,
    title: str,
) -> str:
    value = value.strip()

    if value.startswith("```"):
        lines = value.splitlines()

        if (
            lines
            and lines[0].strip().startswith("```")
        ):
            lines.pop(0)

        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines.pop()

        value = "\n".join(lines).strip()

    value = value.replace("**", "").strip()
    lines = value.splitlines()

    while lines and (
        not lines[0].strip()
        or lines[0].strip().lower().startswith("aquí")
        or lines[0].strip().lower().startswith("aqui")
        or lines[0].strip().lower().startswith(
            "a tradução"
        )
        or lines[0].strip().lower().startswith(
            "a traducao"
        )
        or lines[0].strip().lower().startswith(
            "here is"
        )
    ):
        lines.pop(0)

    if (
        lines
        and normalize_heading(lines[0])
        == normalize_heading(title)
    ):
        lines.pop(0)

    return "\n".join(lines).strip()


def build_prompt(
    *,
    title: str,
    source_story: str,
    target_language: str,
) -> str:
    target = language_name(target_language)

    return f"""
Translate and adapt this music documentary narration
into {target}.

RULES:
- Preserve the historical meaning, warmth, pacing,
  storytelling flow, and emotional tone
- Make it sound natural when spoken aloud by a
  documentary narrator
- Do not make it sound like a literal translation
- Preserve names, song titles, record labels,
  programs, places, dates, and historical facts
- Keep song titles in their original language unless
  a commonly accepted translation helps clarity
- Use warm conversational language suitable for
  older music fans, libraries, and assisted living
- Preserve the paragraph structure
- Do not shorten or summarize the documentary
- Do not add quotations, anecdotes, examples,
  people, dates, statistics, or historical claims
- Preserve expressions of uncertainty and disputed
  history from the English source
- Do not turn legends into established facts
- Do not add headings, bullet points, labels,
  notes, or markdown
- Do not include the documentary title
- Do not say that this is a translation
- Return only the finished narration text

DOCUMENTARY TITLE:
{title}

ENGLISH SOURCE STORY:
{source_story}
""".strip()


def print_story(
    *,
    title: str,
    language: str,
    story_text: str,
    source: str,
) -> None:
    print("=" * 80)
    print(title)
    print(f"Language: {language}")
    print("=" * 80)
    print(story_text)
    print("=" * 80)
    print(f"Words:  {len(story_text.split())}")
    print(f"Chars:  {len(story_text)}")
    print(f"Source: {source}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--slug",
        required=True,
        help="Music Docuseries slug",
    )
    parser.add_argument(
        "--language",
        required=True,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the generated preview to this file.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Read reviewed translation from this file.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save reviewed --input text.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output or database text.",
    )
    args = parser.parse_args()

    language = normalize_language(args.language)

    if language not in SUPPORTED_LANGS:
        raise SystemExit(
            f"Unsupported locale language: {language}"
        )

    if args.input and args.output:
        raise SystemExit(
            "Use --input or --output, not both."
        )

    if args.save and not args.input:
        raise SystemExit(
            "--save requires --input so only reviewed "
            "text can be written to the database."
        )

    with Session(engine) as session:
        item = session.exec(
            select(MusicDocuseries).where(
                MusicDocuseries.slug == args.slug
            )
        ).first()

        if not item:
            raise SystemExit(
                "Music Docuseries item not found: "
                f"{args.slug}"
            )

        source_locale = session.exec(
            select(MusicDocuseriesLocale)
            .where(
                MusicDocuseriesLocale.docuseries_id
                == item.id
            )
            .where(
                MusicDocuseriesLocale.language_code
                == "en"
            )
        ).first()

        if (
            not source_locale
            or not source_locale.story_text
        ):
            raise SystemExit(
                "English source story not found: "
                f"{item.slug}"
            )

        existing = session.exec(
            select(MusicDocuseriesLocale)
            .where(
                MusicDocuseriesLocale.docuseries_id
                == item.id
            )
            .where(
                MusicDocuseriesLocale.language_code
                == language
            )
        ).first()

        if (
            existing
            and existing.story_text
            and not args.overwrite
        ):
            raise SystemExit(
                f"Existing {language} story found. "
                "Use --overwrite to replace it."
            )

        if args.input:
            if not args.input.exists():
                raise SystemExit(
                    f"Input file not found: {args.input}"
                )

            story_text = clean_story(
                args.input.read_text(
                    encoding="utf-8"
                ),
                title=item.title,
            )
            source = str(args.input)
        else:
            prompt = build_prompt(
                title=item.title,
                source_story=source_locale.story_text,
                target_language=language,
            )

            translated_text = ask_xai(
                system_prompt=(
                    "You are a warm, accurate multilingual "
                    "music-documentary translator and narrator."
                ),
                user_prompt=prompt,
                temperature=0.2,
            )

            story_text = clean_story(
                translated_text,
                title=item.title,
            )
            source = "XAI preview"

        if not story_text:
            raise SystemExit(
                "Translated story text is empty."
            )

        print_story(
            title=item.title,
            language=language,
            story_text=story_text,
            source=source,
        )

        if args.output:
            if (
                args.output.exists()
                and not args.overwrite
            ):
                raise SystemExit(
                    f"Output already exists: "
                    f"{args.output}. "
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
            print(
                "Preview only. No database changes made."
            )
            return

        now = datetime.now(UTC)

        if existing:
            existing.story_text = story_text
            existing.duration_seconds = None
            existing.tts_bucket = None
            existing.tts_key = None

            if hasattr(existing, "updated_at"):
                existing.updated_at = now

            locale = existing
        else:
            locale = MusicDocuseriesLocale(
                docuseries_id=item.id,
                language_code=language,
                story_text=story_text,
            )

            if hasattr(locale, "created_at"):
                locale.created_at = now

            if hasattr(locale, "updated_at"):
                locale.updated_at = now

        session.add(locale)
        session.commit()

        print(
            f"Music Docuseries {language} reviewed "
            "text saved."
        )


if __name__ == "__main__":
    main()