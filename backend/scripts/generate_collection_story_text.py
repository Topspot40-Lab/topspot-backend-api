from __future__ import annotations

import argparse
from datetime import datetime, UTC

from sqlalchemy import text
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Collection, CollectionStory
from backend.services.xai_client import ask_xai


def clean_story(value: str) -> str:
    value = value.strip().strip('"').strip()
    lines = value.splitlines()

    while lines and (
        not lines[0].strip()
        or lines[0].strip().startswith("**")
        or lines[0].strip().lower().endswith("story")
    ):
        lines.pop(0)

    return "\n".join(lines).strip()


def build_prompt(
    *,
    collection_name: str,
    collection_slug: str,
    track_count: int,
    track_list: str,
    story_type: str,
) -> str:
    return f"""
Create a TopSpot Collection Story for this music collection.

Collection:
{collection_name}

Slug:
{collection_slug}

Track count:
{track_count}

Representative tracks:
{track_list}

Audience:
- Music lovers age 50+
- People who enjoy nostalgia, music history, personal memories, and cultural stories
- Retirement communities, Winter Texans, and family listeners

Target:
- story_type: {story_type}
- If feature: 7 to 10 minutes of spoken narration
- If standard: 5 to 7 minutes of spoken narration
- If short: 3 to 5 minutes of spoken narration

Style:
- Warm, conversational, engaging
- Sounds good when spoken aloud
- Like a friendly music historian or radio storyteller
- Tell the story of the collection, not just a list of songs
- Explain why this kind of music mattered
- Include historical background, human stories, cultural meaning, and emotional memory
- Mention a few representative artists or songs naturally when helpful
- Make the listener excited to hear the songs afterward
- End with a warm reflection on why this collection still matters today

Avoid:
- Dry encyclopedia style
- Long award lists
- Bullet points
- Markdown headings
- Song lyrics
- Excessive dates and timelines
- Do not include titles, headings, or markdown formatting
- Do not begin with phrases such as:
  "Here's the story"
  "Let me tell you"
  "Today we're going to"
  or similar introductions
- Begin naturally and immediately

Return only the story text.
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", required=True, help="Collection slug")
    parser.add_argument(
        "--story-type",
        default="feature",
        choices=["short", "standard", "feature"],
    )
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    language = "en"

    with Session(engine) as session:
        collection = session.exec(
            select(Collection).where(Collection.slug == args.collection)
        ).first()

        if not collection:
            raise SystemExit(f"Collection not found: {args.collection}")

        existing = session.exec(
            select(CollectionStory)
            .where(CollectionStory.collection_id == collection.id)
            .where(CollectionStory.language_code == language)
        ).first()

        if existing and not args.overwrite:
            print(f"Skipping existing Collection Story: {collection.slug} [{language}]")
            return

        rows = session.exec(
            text("""
                SELECT
                    ctr.ranking,
                    t.track_name,
                    COALESCE(t.artist_display_name, a.artist_name) AS artist_name,
                    t.year_released
                FROM collection_track_ranking ctr
                JOIN track t ON t.id = ctr.track_id
                LEFT JOIN artist a ON a.id = t.artist_id
                WHERE ctr.collection_id = :collection_id
                ORDER BY ctr.ranking
                LIMIT 45
            """).bindparams(collection_id=collection.id)
        ).all()

        track_count = len(rows)

        if track_count == 0:
            raise SystemExit(f"No tracks found for collection: {collection.slug}")

        track_lines = []
        for row in rows[:25]:
            year = f" ({row.year_released})" if row.year_released else ""
            track_lines.append(
                f"{row.ranking}. {row.track_name} — {row.artist_name}{year}"
            )

        track_list = "\n".join(track_lines)

        collection_name = getattr(collection, "name", None) or getattr(
            collection, "title", None
        ) or collection.slug.replace("_", " ").title()

        prompt = build_prompt(
            collection_name=collection_name,
            collection_slug=collection.slug,
            track_count=track_count,
            track_list=track_list,
            story_type=args.story_type,
        )

        print(f"Generating Collection Story: {collection_name}")
        print(f"Slug: {collection.slug}")
        print(f"Story type: {args.story_type}")
        print(f"Track count: {track_count}")
        print(f"Save mode: {args.save}")
        print(f"Overwrite: {args.overwrite}")
        print()

        story_text = clean_story(
            ask_xai(
                system_prompt="You are a warm, accurate music historian and radio storyteller.",
                user_prompt=prompt,
                temperature=0.8,
            )
        )

        title = f"The Story of {collection_name}"

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
                CollectionStory(
                    collection_id=collection.id,
                    language_code=language,
                    title=title,
                    story_text=story_text,
                    story_type=args.story_type,
                    created_at=now,
                    updated_at=now,
                )
            )

        session.commit()
        print("Saved Collection Story to database.")


if __name__ == "__main__":
    main()