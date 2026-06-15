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
    ):
        lines.pop(0)

    return "\n".join(lines).strip()


def build_prompt(artist_name: str, track_count: int, story_type: str) -> str:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist", default=None)
    parser.add_argument("--min-tracks", type=int, default=4)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--story-type",
        default="standard",
        choices=["short", "standard", "feature"]
    )
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    with Session(engine) as session:
        if args.artist:
            rows = session.exec(
                text("""
                    select
                        a.id,
                        a.artist_name,
                        count(t.id) as track_count
                    from artist a
                    left join track t on t.artist_id = a.id
                    where a.artist_name ilike :artist_name
                    group by a.id, a.artist_name
                    limit 1
                """).bindparams(artist_name=args.artist)
            ).mappings().all()
        else:
            rows = session.exec(
                text("""
                    select
                        a.id,
                        a.artist_name,
                        count(t.id) as track_count
                    from artist a
                    join track t on t.artist_id = a.id
                    left join artist_story s
                        on s.artist_id = a.id
                       and s.language_code = 'en'
                    where s.id is null
                    group by a.id, a.artist_name
                    having count(t.id) >= :min_tracks
                    order by count(t.id) desc, a.artist_name
                    limit :limit
                """).bindparams(
                    min_tracks=args.min_tracks,
                    limit=args.limit,
                )
            ).mappings().all()

        if not rows:
            print("No artists found needing stories.")
            return

        print("=" * 80)
        print("Generate Missing Artist Stories")
        print(f"Artist:     {args.artist}")
        print(f"Min tracks: {args.min_tracks}")
        print(f"Limit:      {args.limit}")
        print(f"Story type: {args.story_type}")
        print(f"Save mode:  {args.save}")
        print(f"Found:      {len(rows)}")
        print("=" * 80)

        saved = 0

        for row in rows:
            artist_id = row["id"]
            artist_name = row["artist_name"]
            track_count = row["track_count"]

            prompt = build_prompt(
                artist_name=artist_name,
                track_count=track_count,
                story_type=args.story_type,
            )

            print()
            print("=" * 80)
            print(f"Generating Artist Story: {artist_name}")
            print(f"Artist ID:  {artist_id}")
            print(f"Story type: {args.story_type}")
            print(f"Track count: {track_count}")
            print("=" * 80)

            story_text = clean_story(
                ask_xai(
                    system_prompt="You are a warm, accurate music historian and radio storyteller.",
                    user_prompt=prompt,
                    temperature=0.8,
                )
            )

            title = f"The Story of {artist_name.title()}"

            print(title)
            print("-" * 80)
            print(story_text)
            print()

            if not args.save:
                continue

            now = datetime.now(UTC)

            existing = session.exec(
                select(ArtistStory)
                .where(ArtistStory.artist_id == artist_id)
                .where(ArtistStory.language_code == "en")
            ).first()

            if existing:
                existing.title = title
                existing.story_text = story_text
                existing.story_type = args.story_type
                existing.updated_at = now
                session.add(existing)
            else:
                session.add(
                    ArtistStory(
                        artist_id=artist_id,
                        language_code="en",
                        title=title,
                        story_text=story_text,
                        story_type=args.story_type,
                        created_at=now,
                        updated_at=now,
                    )
                )

            session.commit()
            saved += 1
            print(f"Saved Artist Story: {artist_name}")

        print("=" * 80)
        print(f"Saved: {saved}")
        print("=" * 80)


if __name__ == "__main__":
    main()
