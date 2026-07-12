from __future__ import annotations

import argparse
from datetime import datetime, UTC

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import MusicDocuseries, MusicDocuseriesLocale
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


def clean_story(value: str) -> str:
    value = value.strip()

    if value.startswith("```"):
        lines = value.splitlines()

        if lines and lines[0].strip().startswith("```"):
            lines.pop(0)

        if lines and lines[-1].strip() == "```":
            lines.pop()

        value = "\n".join(lines).strip()

    value = value.replace("**", "").strip()

    lines = value.splitlines()

    while lines and (
        not lines[0].strip()
        or lines[0].strip().lower().startswith("aquí")
        or lines[0].strip().lower().startswith("aqui")
        or lines[0].strip().lower().startswith("a tradução")
        or lines[0].strip().lower().startswith("a traducao")
        or lines[0].strip().lower().startswith("here is")
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
Translate and adapt this music documentary narration into {target}.

RULES:
- Preserve the historical meaning, warmth, pacing, storytelling flow, and emotional tone.
- Make it sound natural when spoken aloud by a documentary narrator.
- Do not make it sound like a literal translation.
- Preserve artist names, song titles, record labels, television programs, places, and historical facts.
- Keep song titles in their original language unless a commonly accepted translated title is needed for clarity.
- Use warm, conversational language suitable for music lovers age 50+, libraries, and assisted-living audiences.
- Preserve the paragraph structure.
- Do not shorten or summarize the story.
- Do not add new historical claims.
- Do not add headings, bullet points, labels, notes, or markdown.
- Do not include the title.
- Do not say "Here is the translation."
- Verify important historical claims and avoid repeating popular myths as settled fact
- Bob Dylan rehearsed for The Ed Sullivan Show but did not appear after a dispute over his song choice
- Describe Elvis Presley’s camera restrictions carefully; do not claim all three appearances were filmed only from the waist up
- Return only the finished narration text.

DOCUMENTARY TITLE:
{title}

ENGLISH SOURCE STORY:
{source_story}
""".strip()


def generate_one(
    *,
    session: Session,
    item: MusicDocuseries,
    source_locale: MusicDocuseriesLocale,
    language: str,
    save: bool,
    overwrite: bool,
) -> bool:
    existing = session.exec(
        select(MusicDocuseriesLocale)
        .where(MusicDocuseriesLocale.docuseries_id == item.id)
        .where(MusicDocuseriesLocale.language_code == language)
    ).first()

    if existing and existing.story_text and not overwrite:
        print(f"Skipping existing {language} Music Docuseries: {item.slug}")
        return False

    print("=" * 80)
    print("Generating Music Docuseries Locale")
    print(f"Title:      {item.title}")
    print(f"Slug:       {item.slug}")
    print(f"Language:   {language}")
    print(f"Source ID:  {source_locale.id}")
    print(f"Source words: {len((source_locale.story_text or '').split())}")
    print(f"Save mode:  {save}")
    print(f"Overwrite:  {overwrite}")
    print()

    prompt = build_prompt(
        title=item.title,
        source_story=source_locale.story_text,
        target_language=language,
    )

    story_text = clean_story(
        ask_xai(
            system_prompt=(
                "You are a warm, accurate multilingual music-documentary "
                "translator and narrator."
            ),
            user_prompt=prompt,
            temperature=0.5,
        )
    )

    if not story_text:
        raise RuntimeError("XAI returned empty Music Docuseries text.")

    print(story_text)
    print()
    print("-" * 80)
    print(f"Words: {len(story_text.split())}")

    if not save:
        print("Preview only. Re-run with --save to write to database.")
        return False

    now = datetime.now(UTC)

    if existing:
        existing.story_text = story_text
        existing.duration_seconds = None
        existing.tts_bucket = None
        existing.tts_key = None

        if hasattr(existing, "updated_at"):
            existing.updated_at = now

        session.add(existing)
    else:
        values = {
            "docuseries_id": item.id,
            "language_code": language,
            "story_text": story_text,
        }

        locale = MusicDocuseriesLocale(**values)

        if hasattr(locale, "created_at"):
            locale.created_at = now

        if hasattr(locale, "updated_at"):
            locale.updated_at = now

        session.add(locale)

    session.commit()
    print(f"Saved {language} Music Docuseries locale.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default=None, help="Music Docuseries slug")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--language", required=True)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    language = normalize_language(args.language)

    if language not in SUPPORTED_LANGS:
        raise SystemExit(f"Unsupported locale language: {language}")

    if not args.slug and not args.all:
        raise SystemExit('Use --slug "fabulous_fifties" or --all')

    if args.slug and args.all:
        raise SystemExit("Use either --slug or --all, not both")

    generated = 0
    skipped = 0

    with Session(engine) as session:
        if args.all:
            items = session.exec(
                select(MusicDocuseries)
                .where(MusicDocuseries.is_active == True)
                .order_by(MusicDocuseries.sort_order)
            ).all()
        else:
            item = session.exec(
                select(MusicDocuseries)
                .where(MusicDocuseries.slug == args.slug)
            ).first()

            if not item:
                raise SystemExit(f"Music Docuseries item not found: {args.slug}")

            items = [item]

        for item in items:
            source_locale = session.exec(
                select(MusicDocuseriesLocale)
                .where(MusicDocuseriesLocale.docuseries_id == item.id)
                .where(MusicDocuseriesLocale.language_code == "en")
            ).first()

            if not source_locale or not source_locale.story_text:
                print(f"Skipping {item.slug}: English source story not found")
                skipped += 1
                continue

            did_generate = generate_one(
                session=session,
                item=item,
                source_locale=source_locale,
                language=language,
                save=args.save,
                overwrite=args.overwrite,
            )

            if did_generate:
                generated += 1
            else:
                skipped += 1

    print("=" * 80)
    print("Done.")
    print(f"Generated: {generated}")
    print(f"Skipped:   {skipped}")


if __name__ == "__main__":
    main()
