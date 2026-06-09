from __future__ import annotations

import argparse
from datetime import datetime, UTC

from sqlalchemy import text
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, ArtistStory
from backend.services.xai_client import ask_xai


def clean_story(value: str) -> str:
    value = value.strip().strip('"').strip()
    lines = value.splitlines()

    while lines and (
        not lines[0].strip()
        or lines[0].strip().startswith("**")
        or lines[0].strip().lower().endswith(" story")
        or lines[0].strip().lower().endswith("história")
    ):
        lines.pop(0)

    return "\n".join(lines).strip()


def normalize_language(value: str) -> str:
    if value.lower() in ("pt", "pt-br", "ptbr"):
        return "pt-BR"
    return value.lower()


def build_english_prompt(artist_name: str, track_count: int, story_type: str) -> str:
    return f"""
Create a TopSpot Artist Story for {artist_name}.

Audience:
- Music lovers age 50+
- People who enjoy nostalgia, music history, and personal stories

Target:
- story_type: {story_type}
- If feature: 10 to 15 minutes of spoken narration
- If standard: 7 to 10 minutes of spoken narration
- If short: 4 to 6 minutes of spoken narration

Style:
- Warm, conversational, engaging
- Sounds good when spoken aloud
- Like a friendly music historian or radio storyteller
- Tell a story, not a biography
- Include interesting anecdotes, funny stories, personality, struggles, turning points, and legacy
- Include 2 to 3 memorable stories or little-known facts when available
- Focus on memorable stories and human moments
- Listeners should remember at least 3 stories about the artist after hearing the program
- Prefer stories over chronology
- Make the listener want to hear the artist's music afterward
- End with a warm reflection on why the artist still matters today

Avoid:
- Dry encyclopedia style
- Long award lists
- Excessive chart statistics
- Bullet points
- Markdown headings
- Song lyrics
- Excessive dates and timelines
- Repeating the artist's full name excessively
- Do not include titles, headings, or markdown formatting
- Do not begin with phrases such as:
  "Here's the story"
  "Let me tell you"
  "Today we're going to"
  or similar introductions
- Begin naturally and immediately

Artist:
{artist_name}

TopSpot track count:
{track_count}

Return only the story text.
""".strip()


def build_locale_prompt(
    artist_name: str,
    story_type: str,
    language: str,
    source_story: str,
) -> str:
    if language == "pt-BR":
        language_name = "Brazilian Portuguese"
        style_note = "natural Brazilian Portuguese"
        avoid_starters = '"Hoje vamos", "Aqui está", "Vamos falar sobre"'
    elif language == "es":
        language_name = "Spanish"
        style_note = "natural Mexican Spanish"
        avoid_starters = '"Hoy vamos", "Aquí está", "Vamos a hablar de"'
    else:
        raise ValueError(f"Unsupported locale language: {language}")

    return f"""
Create a TopSpot Artist Story in {language_name} for {artist_name}.

Use this English story as the source material, but do NOT translate word-for-word.
Rewrite it naturally in {style_note}.

Target:
- story_type: {story_type}
- Warm spoken narration
- Sounds natural when read aloud
- Keep the same emotional arc and major stories
- Preserve artist names and song titles
- Prefer storytelling over chronology
- End with a warm reflection on why the artist still matters today

Avoid:
- Literal translation
- Dry encyclopedia style
- Bullet points
- Markdown headings
- Song lyrics
- Excessive dates and timelines
- Titles or headings
- Starting with {avoid_starters}, or similar setup phrases
- Repeating the artist's full name excessively

English source story:
{source_story}

Return only the {language_name} story text.
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--story-type", default="feature", choices=["short", "standard", "feature"])
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    language = normalize_language(args.language)

    if language not in ("en", "es", "pt-BR"):
        raise SystemExit(f"Unsupported language: {language}")

    with Session(engine) as session:
        artist = session.exec(
            select(Artist).where(Artist.artist_name.ilike(args.artist))
        ).first()

        if not artist:
            raise SystemExit(f"Artist not found: {args.artist}")

        existing = session.exec(
            select(ArtistStory)
            .where(ArtistStory.artist_id == artist.id)
            .where(ArtistStory.language_code == language)
        ).first()

        if existing and not args.overwrite:
            print(f"Skipping existing story: {artist.artist_name} [{language}]")
            return

        track_count = session.exec(
            text("""
                SELECT COUNT(*)
                FROM track
                WHERE artist_id = :artist_id
            """).bindparams(artist_id=artist.id)
        ).one()[0]

        if language == "en":
            prompt = build_english_prompt(
                artist_name=artist.artist_name,
                track_count=track_count,
                story_type=args.story_type,
            )
            system_prompt = "You are a warm, accurate music historian and radio storyteller."
            title = f"The Story of {artist.artist_name.title()}"
        else:
            source = session.exec(
                select(ArtistStory)
                .where(ArtistStory.artist_id == artist.id)
                .where(ArtistStory.language_code == "en")
            ).first()

            if not source:
                raise SystemExit(
                    f"English source story not found for {artist.artist_name}. Generate EN first."
                )

            prompt = build_locale_prompt(
                artist_name=artist.artist_name,
                story_type=args.story_type,
                language=language,
                source_story=source.story_text,
            )
            system_prompt = "You are a warm, accurate music historian and natural multilingual radio storyteller."
            title = source.title

        print(f"Generating Artist Story: {artist.artist_name}")
        print(f"Language: {language}")
        print(f"Story type: {args.story_type}")
        print(f"Track count: {track_count}")
        print(f"Save mode: {args.save}")
        print(f"Overwrite: {args.overwrite}")
        print()

        story_text = clean_story(
            ask_xai(
                system_prompt=system_prompt,
                user_prompt=prompt,
                temperature=0.8,
            )
        )

        print("=" * 80)
        print(title)
        print("=" * 80)
        print(story_text)
        print()

        if not args.save:
            print("Preview only. Re-run with --save to write to database.")
            return

        now = datetime.now(UTC)

        if existing:
            existing.title = title
            existing.story_text = story_text
            existing.story_type = args.story_type
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
                    story_type=args.story_type,
                    created_at=now,
                    updated_at=now,
                )
            )

        session.commit()
        print("Saved Artist Story to database.")


if __name__ == "__main__":
    main()
