from __future__ import annotations

import argparse
import re
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import MusicDocuseries, MusicDocuseriesLocale
from backend.services.xai_client import ask_xai

def clean_story_text(value: str) -> str:
    value = value.strip()
    value = value.removeprefix("```text").removeprefix("```").removesuffix("```").strip()
    value = value.replace("**", "")
    value = re.sub(r"\(Word count:.*?\)\s*$", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"^The British Invasion\s*", "", value).strip()
    return value


def build_prompt(title: str, target_length: str) -> str:
    return f"""
Create a TopSpot Music Docuseries narration script.

TITLE:
{title}

TARGET LENGTH:
{target_length}

RULES:
- English only
- Warm, engaging, audio-first storytelling
- Do not sound like Wikipedia
- Write like a music documentary narrator
- Include vivid context, memorable examples, and cultural impact
- Avoid markdown headings
- Avoid bullet points
- Do not mention TopSpot
- Make it suitable for older listeners, music fans, libraries, and assisted living audiences
- End with a satisfying closing thought
- Do not include markdown
- Do not include a title
- Do not include word counts
- Do not include notes to the editor
- Return only the narration text

Approximate length:
- short: 700-900 words
- standard: 1200-1600 words
- feature: 1800-2400 words
""".strip()


def generate_one(
    *,
    session: Session,
    item: MusicDocuseries,
    language: str,
    save: bool,
    overwrite: bool,
) -> bool:
    locale = session.exec(
        select(MusicDocuseriesLocale)
        .where(MusicDocuseriesLocale.docuseries_id == item.id)
        .where(MusicDocuseriesLocale.language_code == language)
    ).first()

    if locale and locale.story_text and not overwrite:
        print(f"Skipping existing English story: {item.slug}")
        return False

    prompt = build_prompt(
        item.title,
        item.target_length or "standard",
    )

    story_text = ask_xai(
        "You create warm, engaging, factual music documentary narration scripts for TopSpot.",
        prompt,
        temperature=0.5,
    )

    story_text = clean_story_text(story_text)

    if not story_text:
        raise RuntimeError(
            f"Empty story returned for: {item.slug}"
        )

    print("=" * 80)
    print(item.title)
    print("=" * 80)
    print(story_text)
    print("=" * 80)
    print(f"Words: {len(story_text.split())}")
    print(f"Save mode: {save}")

    if not save:
        print("Preview only. Re-run with --save to write to database.")
        return False

    if not locale:
        locale = MusicDocuseriesLocale(
            docuseries_id=item.id,
            language_code=language,
            story_text=story_text,
        )
        session.add(locale)
    else:
        locale.story_text = story_text
        locale.duration_seconds = None
        locale.tts_bucket = None
        locale.tts_key = None
        session.add(locale)

    session.commit()
    print("✅ Music Docuseries story text saved.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--language", default="en")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.language != "en":
        raise SystemExit(
            "This script generates English only. "
            "Use generate_music_docuseries_locale for translations."
        )

    if not args.slug and not args.all:
        raise SystemExit('Use --slug "ed_sullivan" or --all')

    if args.slug and args.all:
        raise SystemExit("Use either --slug or --all, not both")

    generated = 0
    skipped = 0
    failed = 0

    with Session(engine) as session:
        if args.all:
            items = session.exec(
                select(MusicDocuseries)
                .where(MusicDocuseries.is_active == True)
                .order_by(
                    MusicDocuseries.collection_id,
                    MusicDocuseries.sort_order,
                )
            ).all()
        else:
            item = session.exec(
                select(MusicDocuseries)
                .where(MusicDocuseries.slug == args.slug)
            ).first()

            if not item:
                raise SystemExit(
                    f"Docuseries item not found: {args.slug}"
                )

            items = [item]

        for item in items:
            try:
                did_generate = generate_one(
                    session=session,
                    item=item,
                    language=args.language,
                    save=args.save,
                    overwrite=args.overwrite,
                )

                if did_generate:
                    generated += 1
                else:
                    skipped += 1

            except Exception as exc:
                failed += 1
                session.rollback()
                print(
                    f"❌ Failed: {item.slug}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue

    print("=" * 80)
    print("Done.")
    print(f"Generated: {generated}")
    print(f"Skipped:   {skipped}")
    print(f"Failed:    {failed}")


if __name__ == "__main__":
    main()
