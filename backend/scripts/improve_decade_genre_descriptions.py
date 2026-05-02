from __future__ import annotations

from sqlalchemy import text
from sqlmodel import select

from backend.database import get_db
from backend.models.dbmodels import DecadeGenre


DECADE_WORDS = {
    "1950s": "the nineteen fifties",
    "1960s": "the nineteen sixties",
    "1970s": "the nineteen seventies",
    "1980s": "the nineteen eighties",
    "1990s": "the nineteen nineties",
    "2000s": "the two thousands",
    "2010s": "the twenty tens",
    "2020s": "the twenty twenties",
}

GENRE_PHRASES = {
    "country": "country music brought heartfelt storytelling, memorable melodies, and a sound built for the radio",
    "pop": "pop music delivered bright hooks, polished production, and songs that stayed with you",
    "rock": "rock music carried grit, energy, and a sound that could fill the room",
    "tv_themes": "TV themes brought back familiar memories from the shows people loved",
    "blues_jazz": "blues and jazz carried soul, swing, and timeless musical feeling",
    "rnb_soul": "R&B and soul blended smooth vocals, deep grooves, and heartfelt emotion",
    "folk_acoustic": "folk and acoustic music kept things honest with warm stories and simple, memorable sounds",
    "latin_global": "Latin and global music brought rhythm, color, and a lively spirit to the airwaves",
}

GENRE_LABELS = {
    "country": "country",
    "pop": "pop",
    "rock": "rock",
    "tv_themes": "TV themes",
    "blues_jazz": "blues and jazz",
    "rnb_soul": "R&B and soul",
    "folk_acoustic": "folk and acoustic",
    "latin_global": "Latin and global",
}

TRANSITIONS = [
    "And now… {genre_label} from {decade_words}.",
    "Up next… {genre_label} from {decade_words}.",
    "Here we go… {genre_label} from {decade_words}.",
    "Coming your way… {genre_label} from {decade_words}.",
    "Now spinning… {genre_label} from {decade_words}.",
]


def genre_label(genre_slug: str) -> str:
    return GENRE_LABELS.get(genre_slug, genre_slug.replace("_", " "))




def build_description(slug: str, index: int) -> str:
    decade_slug, genre_slug = slug.split("-", 1)

    decade_words = DECADE_WORDS.get(decade_slug, decade_slug)
    label = genre_label(genre_slug)

    phrase = GENRE_PHRASES.get(
        genre_slug,
        f"{label} brought its own sound and spirit to the music scene",
    )

    transition = TRANSITIONS[index % len(TRANSITIONS)].format(
        genre_label=label,
        decade_words=decade_words,
    )

    return " ".join(f"In {decade_words}, {phrase}. {transition}".split())


def main() -> None:
    db = next(get_db())

    rows = db.exec(select(DecadeGenre).order_by(DecadeGenre.id)).all()

    updated_count = 0

    for index, row in enumerate(rows):
        if not row.slug:
            continue

        raw_description = build_description(row.slug, index)

        print("RAW:", raw_description)  # 👈 ADD THIS LINE

        new_description = raw_description

        db.exec(
            text("""
                UPDATE public.decade_genre
                SET description = :description
                WHERE id = :id
            """).bindparams(
                description=new_description,
                id=row.id,
            )
        )

        updated_count += 1
        print(f"✅ {row.slug}: {new_description}")

    db.commit()
    print(f"\n🎉 Updated {updated_count} decade_genre descriptions.")


if __name__ == "__main__":
    main()