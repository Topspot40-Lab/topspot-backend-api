from __future__ import annotations

import argparse
import json
import re

from sqlalchemy import text
from sqlmodel import Session

from backend.database import engine
from backend.services.xai_client import ask_xai

CATEGORIES = {
    "artist_stories": 150,
    "song_stories": 150,
    "music_history": 125,
    "musical_connections": 125,
    "world_music": 100,
    "classical_music": 100,
    "genre_origins": 100,
    "instruments": 50,
    "recording_technology": 50,
    "music_milestones": 50,
}


def clean_text(value: str) -> str:
    value = re.sub(r"\*\*", "", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" \n\t\"")


def category_guidance(category: str) -> str:
    guidance = {
        "music_history": """
CATEGORY-SPECIFIC GUIDANCE:
- Prefer historical events, inventions, cultural developments, technologies, traditions, and firsts
- Avoid artist biographies unless directly tied to a major historical development
- Good examples: early recording devices, radio history, vinyl records, jukeboxes, Motown, mariachi history, samba history, early electronic instruments
""",
        "artist_stories": """
CATEGORY-SPECIFIC GUIDANCE:
- Focus on surprising artist stories, habits, breakthroughs, unusual achievements, or creative methods
- Avoid generic summaries like "this artist was influential"
""",
        "song_stories": """
CATEGORY-SPECIFIC GUIDANCE:
- Focus on surprising origins, recording stories, lyrical inspirations, unusual rhythms, cultural journeys, or unexpected popularity
- Avoid simply saying a song was popular
""",
        "musical_connections": """
CATEGORY-SPECIFIC GUIDANCE:
- Focus on how one musical tradition, artist, instrument, culture, or genre influenced another
- Highlight connections between countries, cultures, genres, or historical periods
- Prefer cross-cultural musical journeys and surprising influence paths
- Avoid standalone artist facts unless they demonstrate a significant musical connection
- Avoid general music history that does not illustrate a connection
- Good examples: West African music and Delta blues, Indian sitar and rock music, gospel and soul, bossa nova and jazz, oud and guitar, mariachi and European string traditions
""",

    "classical_music": """
CATEGORY-SPECIFIC GUIDANCE:
- Focus on fascinating stories, innovations, unusual compositions, instruments, premieres, and listening insights from classical music
- Cover composers from many countries and eras
- Avoid generic composer biographies
- Prefer discoveries that help listeners appreciate classical music
- Good examples: Beethoven's hearing loss, Mozart's musical games, Vivaldi's orphan orchestra, Stradivarius violins, Tchaikovsky's 1812 Overture, Debussy and gamelan influences
""",
        "genre_origins": """
    CATEGORY-SPECIFIC GUIDANCE:
    - Focus on how musical genres began and evolved
    - Explain the cultural, geographic, and musical roots of each genre
    - Highlight surprising influences and historical developments
    - Avoid artist biographies unless central to the birth of a genre
    - Good examples: blues, rock and roll, bluegrass, mariachi, reggae, disco, samba, jazz, soul, gospel, bossa nova, country, flamenco
    """,

    "instruments": """
    CATEGORY-SPECIFIC GUIDANCE:
    - Focus on fascinating musical instruments from around the world
    - Highlight unusual construction, sounds, playing techniques, and cultural significance
    - Prefer surprising facts and discoveries
    - Avoid artist biographies
    - Good examples: theremin, kora, sitar, didgeridoo, shakuhachi, steelpan, oud, balalaika, hurdy-gurdy, glass armonica
    - Do not repeat common examples already used in this category
- Prefer lesser-known instruments after the most famous examples are covered
- Avoid theremin, didgeridoo, kora, sitar, oud, steelpan, shakuhachi, hurdy-gurdy, glass armonica, and balalaika unless specifically needed
    """,
        "recording_technology": """
        CATEGORY-SPECIFIC GUIDANCE:
        - Focus on inventions and technologies that changed how music is recorded, produced, distributed, or heard
        - Highlight surprising technical breakthroughs and innovations
        - Explain how the technology changed the music experience for musicians or listeners
        - Avoid artist biographies unless directly tied to a technological invention
        - Avoid general music history that is not technology-focused
        - Prefer technologies that had widespread impact on the music industry
        - Good examples: phonograph, radio, jukebox, LP records, stereo sound, magnetic tape, multitrack recording, synthesizers, cassette tapes, compact discs, MP3, streaming audio, Auto-Tune, drum machines
        """,

        "music_milestones": """
    CATEGORY-SPECIFIC GUIDANCE:
    - Focus on landmark moments that changed the course of music history
    - Highlight firsts, breakthroughs, record-setting achievements, and historic events
    - Prefer moments that had lasting worldwide impact
    - Avoid instrument descriptions unless the invention changed music globally
    - Avoid general music history that does not represent a major turning point
    - Good examples: first recorded sound, invention of music notation, first electric guitar, multitrack recording, Voyager Golden Record, first radio broadcast, Woodstock, MTV launch
    """

    }

    return guidance.get(category, "")


def generate_items(category: str, count: int) -> list[dict]:
    prompt = f"""
Generate {count} TopSpot Music Discovery Moments.

CATEGORY:
{category}

{category_guidance(category)}

RULES:
- English only
- Broad worldwide music coverage
- Include popular music, classical, folk, world music, recording history, instruments, and cultural context where appropriate
- Each item should be interesting to a casual older music listener
- Positive, educational, and curiosity-building
- Prefer surprising, memorable, or little-known facts
- Focus on stories, discoveries, innovations, connections, and unusual achievements
- Avoid generic artist biographies
- Make the listener think, "I didn't know that"
- No scandals, gossip, politics, or dark controversy
- No quiz wording
- Do NOT start discovery_text with "Did you know"
- Store clean content only; the phrase "Did you know? ..." will be added later during MP3 generation
- No markdown
- No numbering
- Each discovery_text should be 1 to 2 sentences
- Keep each item short enough for spoken radio, usually 20 to 45 words
- Prefer specific facts over general descriptions
- Avoid facts that most music fans already know
- Return valid JSON only

JSON format:
[
  {{
    "topic": "short_topic_slug",
    "title": "Short Title",
    "discovery_text": "Clean discovery text without the words Did you know."
  }}
]
""".strip()

    raw = ask_xai(
        "You create warm, factual, radio-friendly music discovery content for TopSpot.",
        prompt,
        temperature=0.5,
    )

    raw = raw.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError("XAI response was not a JSON list.")

    return data


def insert_items(category: str, items: list[dict], save: bool) -> None:
    with Session(engine) as session:
        for item in items:
            topic = clean_text(item.get("topic", ""))
            title = clean_text(item.get("title", ""))
            discovery_text = clean_text(item.get("discovery_text", ""))

            print("=" * 80)
            print(f"Category: {category}")
            print(f"Topic: {topic}")
            print(f"Title: {title}")
            print(discovery_text)

            if not save:
                continue

            result = session.exec(
                text("""
                    INSERT INTO music_discovery
                        (category, topic, title, review_status, is_active)
                    VALUES
                        (:category, :topic, :title, 'draft', true)
                    RETURNING id
                """).bindparams(
                    category=category,
                    topic=topic,
                    title=title,
                )
            ).first()

            discovery_id = result[0]

            session.exec(
                text("""
                    INSERT INTO music_discovery_locale
                        (music_discovery_id, language_code, discovery_text)
                    VALUES
                        (:music_discovery_id, 'en', :discovery_text)
                """).bindparams(
                    music_discovery_id=discovery_id,
                    discovery_text=discovery_text,
                )
            )

        if save:
            session.commit()


def main(category: str, count: int, save: bool) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"Unsupported category: {category}")

    items = generate_items(category, count)
    insert_items(category, items, save)

    print("\nDone.")
    print(f"Category: {category}")
    print(f"Generated: {len(items)}")
    print(f"Save mode: {save}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True, choices=CATEGORIES.keys())
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    main(args.category, args.count, args.save)
