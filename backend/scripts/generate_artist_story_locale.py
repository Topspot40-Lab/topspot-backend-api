from __future__ import annotations

import argparse
from datetime import datetime, UTC

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, ArtistStory
from backend.services.xai_client import ask_xai


SUPPORTED_LANGS = ("es", "pt-BR")


def normalize_language(value: str) -> str:
    value = value.strip()
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
        or lines[0].strip().lower().endswith("historia")
        or lines[0].strip().lower().endswith("história")
    ):
        lines.pop(0)

    return "\n".join(lines).strip()


def localized_title(artist_name: str, language: str) -> str:
    if language == "es":
        return f"La Historia de {artist_name.title()}"
    if language == "pt-BR":
        return f"A História de {artist_name.title()}"
    raise ValueError(f"Unsupported language: {language}")


def build_prompt(
    *,
    artist_name: str,
    language: str,
    story_type: str,
    english_story: str,
) -> str:
    if language == "es":
        language_name = "Spanish"
        style_note = "natural Mexican Spanish"
        avoid_openers = '"Hoy vamos", "Aquí está", "Vamos a hablar de", "Déjame contarte"'
    elif language == "pt-BR":
        language_name = "Brazilian Portuguese"
        style_note = "natural Brazilian Portuguese"
        avoid_openers = '"Hoje vamos", "Aqui está", "Vamos falar sobre", "Deixe-me contar"'
    else:
        raise ValueError(f"Unsupported language: {language}")

    return f"""
Create a TopSpot Artist Story in {language_name} for {artist_name}.

Use the English story below as source material, but do NOT translate word-for-word.
Rewrite it naturally in {style_note}, as if a warm radio storyteller were speaking directly to music lovers.

Audience:
- Music lovers age 50+
- People who enjoy nostalgia, music history, and personal stories

Target:
- story_type: {story_type}
- Warm spoken narration
- Sounds natural when read aloud
- Keep the emotional arc and major stories from the English source
- Preserve artist names and song titles
- Prefer memorable stories and human moments over chronology
- Make the listener want to hear the artist's music afterward
- End with a warm reflection on why the artist still matters today

Avoid:
- Literal translation
- Dry encyclopedia style
- Long award lists
- Excessive chart statistics
- Bullet points
- Markdown headings
- Song lyrics
- Excessive dates and timelines
- Repeating the artist's full name excessively
- Titles or headings
- Starting with {avoid_openers}, or similar setup phrases
- English filler phrases

English source story:
{english_story}

Return only the {language_name} story text.
""".strip()


def generate_one(
    *,
    session: Session,
    artist: Artist,
    language: str,
    overwrite: bool,
    save: bool,
) -> bool:
    english_story = session.exec(
        select(ArtistStory)
        .where(ArtistStory.artist_id == artist.id)
        .where(ArtistStory.language_code == "en")
    ).first()

    if not english_story:
        print(f"Skipping {artist.artist_name}: no English story found.")
        return False

    existing = session.exec(
        select(ArtistStory)
        .where(ArtistStory.artist_id == artist.id)
        .where(ArtistStory.language_code == language)
    ).first()

    if existing and not overwrite:
        print(f"Skipping existing: {artist.artist_name} [{language}]")
        return False

    prompt = build_prompt(
        artist_name=artist.artist_name,
        language=language,
        story_type=english_story.story_type or "feature",
        english_story=english_story.story_text,
    )

    print("=" * 80)
    print(f"Generating Artist Story Locale")
    print(f"Artist:    {artist.artist_name}")
    print(f"Language:  {language}")
    print(f"Story ID:  {english_story.id}")
    print(f"Save mode: {save}")
    print(f"Overwrite: {overwrite}")
    print()

    story_text = clean_story(
        ask_xai(
            system_prompt="You are a warm, accurate music historian and natural multilingual radio storyteller.",
            user_prompt=prompt,
            temperature=0.8,
        )
    )

    title = localized_title(artist.artist_name, language)

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
        existing.story_type = english_story.story_type
        existing.tts_bucket = None
        existing.tts_key = None
        existing.duration_seconds = None
        existing.updated_at = now
        session.add(existing)
    else:
        session.add(
            ArtistStory(
                artist_id=artist.id,
                language_code=language,
                title=title,
                story_text=story_text,
                story_type=english_story.story_type,
                created_at=now,
                updated_at=now,
            )
        )

    session.commit()
    print(f"Saved {language} Artist Story to database.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--language", required=True)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    language = normalize_language(args.language)

    if language not in SUPPORTED_LANGS:
        raise SystemExit(f"Unsupported language: {language}. Use es or pt-BR.")

    if args.all and args.artist:
        raise SystemExit("Use either --artist or --all, not both.")

    if not args.all and not args.artist:
        raise SystemExit('Use --artist "name" or --all.')

    generated = 0
    skipped = 0

    with Session(engine) as session:
        if args.all:
            rows = session.exec(
                select(Artist)
                .join(ArtistStory, ArtistStory.artist_id == Artist.id)
                .where(ArtistStory.language_code == "en")
                .order_by(Artist.artist_name)
            ).all()

            print(f"Locale batch generation")
            print(f"Language:  {language}")
            print(f"Artists:   {len(rows)}")
            print(f"Save mode: {args.save}")
            print(f"Overwrite: {args.overwrite}")
            print()

            for artist in rows:
                did_generate = generate_one(
                    session=session,
                    artist=artist,
                    language=language,
                    overwrite=args.overwrite,
                    save=args.save,
                )

                if did_generate:
                    generated += 1
                else:
                    skipped += 1

        else:
            artist = session.exec(
                select(Artist).where(Artist.artist_name.ilike(args.artist))
            ).first()

            if not artist:
                raise SystemExit(f"Artist not found: {args.artist}")

            did_generate = generate_one(
                session=session,
                artist=artist,
                language=language,
                overwrite=args.overwrite,
                save=args.save,
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