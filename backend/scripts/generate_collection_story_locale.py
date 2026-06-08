from __future__ import annotations

import argparse
from datetime import datetime, UTC

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Collection, CollectionStory
from backend.services.xai_client import ask_xai


SUPPORTED_LANGS = ("es", "pt-BR")


def normalize_language(value: str) -> str:
    if value.lower() in ("pt", "pt-br", "ptbr"):
        return "pt-BR"
    return value.lower()


def clean_story(value: str) -> str:
    value = value.strip().strip('"').strip()
    lines = value.splitlines()

    while lines and (
        not lines[0].strip()
        or lines[0].strip().startswith("**")
        or lines[0].strip().lower().endswith("story")
        or lines[0].strip().lower().startswith("la historia")
        or lines[0].strip().lower().startswith("a história")
    ):
        lines.pop(0)

    return "\n".join(lines).strip()


def language_name(language: str) -> str:
    if language == "es":
        return "natural Mexican Spanish"
    if language == "pt-BR":
        return "natural Brazilian Portuguese"
    return language


def build_prompt(
    *,
    collection_name: str,
    source_title: str | None,
    source_story: str,
    target_language: str,
) -> str:
    target = language_name(target_language)

    return f"""
Translate and adapt this TopSpot Collection Story into {target}.

Rules:
- Preserve the meaning, warmth, storytelling flow, and emotional tone.
- Make it sound natural when spoken aloud.
- Do NOT make it sound like a literal translation.
- Keep artist names and song titles in their original form unless a title is commonly translated.
- Use warm, conversational language for music lovers age 50+.
- Avoid markdown headings, bullet points, or labels.
- Do not add a title.
- Do not include phrases like "Here is the translation."
- Return only the finished story text.

Collection:
{collection_name}

Source title:
{source_title or ""}

English story:
{source_story}
""".strip()


def get_collection_name(collection: Collection) -> str:
    return (
        getattr(collection, "name", None)
        or getattr(collection, "title", None)
        or collection.slug.replace("_", " ").title()
    )


def generate_one(
    *,
    session: Session,
    source_story: CollectionStory,
    collection: Collection,
    language: str,
    save: bool,
    overwrite: bool,
) -> bool:
    existing = session.exec(
        select(CollectionStory)
        .where(CollectionStory.collection_id == collection.id)
        .where(CollectionStory.language_code == language)
    ).first()

    if existing and not overwrite:
        print(f"Skipping existing {language} Collection Story: {collection.slug}")
        return False

    collection_name = get_collection_name(collection)

    print("=" * 80)
    print("Generating Collection Story Locale")
    print(f"Collection: {collection_name}")
    print(f"Slug:       {collection.slug}")
    print(f"Language:   {language}")
    print(f"Source ID:  {source_story.id}")
    print(f"Save mode:  {save}")
    print(f"Overwrite:  {overwrite}")
    print()

    prompt = build_prompt(
        collection_name=collection_name,
        source_title=source_story.title,
        source_story=source_story.story_text,
        target_language=language,
    )

    story_text = clean_story(
        ask_xai(
            system_prompt="You are a warm, accurate multilingual radio storyteller.",
            user_prompt=prompt,
            temperature=0.7,
        )
    )

    if language == "es":
        title = f"La Historia de {collection_name}"
    elif language == "pt-BR":
        title = f"A História de {collection_name}"
    else:
        title = source_story.title

    print(title)
    print("-" * 80)
    print(story_text)
    print()

    if not save:
        print("Preview only. Re-run with --save to write to database.")
        return False

    now = datetime.now(UTC)

    if existing:
        existing.title = title
        existing.story_text = story_text
        existing.story_type = source_story.story_type
        existing.duration_seconds = None
        existing.tts_bucket = None
        existing.tts_key = None
        existing.updated_at = now
        session.add(existing)
    else:
        session.add(
            CollectionStory(
                collection_id=collection.id,
                language_code=language,
                title=title,
                story_text=story_text,
                story_type=source_story.story_type,
                created_at=now,
                updated_at=now,
            )
        )

    session.commit()
    print(f"Saved {language} Collection Story to database.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default=None, help="Collection slug")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--language", required=True)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    language = normalize_language(args.language)

    if language not in SUPPORTED_LANGS:
        raise SystemExit(f"Unsupported locale language: {language}")

    if not args.collection and not args.all:
        raise SystemExit('Use --collection "slug" or --all')

    if args.collection and args.all:
        raise SystemExit("Use either --collection or --all, not both")

    generated = 0
    skipped = 0

    with Session(engine) as session:
        if args.all:
            source_stories = session.exec(
                select(CollectionStory)
                .where(CollectionStory.language_code == "en")
                .order_by(CollectionStory.id)
            ).all()

            if not source_stories:
                raise SystemExit("No English collection stories found.")

            for source_story in source_stories:
                collection = session.get(Collection, source_story.collection_id)

                if not collection:
                    print(f"Skipping source story {source_story.id}: collection not found")
                    skipped += 1
                    continue

                did_generate = generate_one(
                    session=session,
                    source_story=source_story,
                    collection=collection,
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
            return

        collection = session.exec(
            select(Collection).where(Collection.slug == args.collection)
        ).first()

        if not collection:
            raise SystemExit(f"Collection not found: {args.collection}")

        source_story = session.exec(
            select(CollectionStory)
            .where(CollectionStory.collection_id == collection.id)
            .where(CollectionStory.language_code == "en")
        ).first()

        if not source_story:
            raise SystemExit(
                f"English collection story not found: collection={collection.slug}"
            )

        did_generate = generate_one(
            session=session,
            source_story=source_story,
            collection=collection,
            language=language,
            save=args.save,
            overwrite=args.overwrite,
        )

        print("=" * 80)
        print("Done.")
        print(f"Generated: {1 if did_generate else 0}")
        print(f"Skipped:   {0 if did_generate else 1}")


if __name__ == "__main__":
    main()