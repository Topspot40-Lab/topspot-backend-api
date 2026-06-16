from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import CollectionCategory


DESCRIPTIONS = {
    "american_heritage_favorites": "Songs that tell stories of American memory, patriotism, travel, working life, folk heroes, railroads, western life, and shared national experience.",
    "traditional_favorites": "Timeless favorites rooted in familiar traditions, including hymns, gospel, bluegrass, cowboy songs, crooners, and classic American standards.",
    "world_heritage_favorites": "Music that celebrates cultural roots and global traditions, including Mexican, Brazilian, Celtic, Italian, German, and African-American heritage favorites.",
    "stage_and_screen": "Memorable songs and themes from movies, Broadway, Disney, television, and video games.",
    "classical_music": "Curated classical selections organized by major musical periods, including Baroque, Classical, and Romantic era favorites.",
    "music_trends": "Popular music movements, styles, and cultural moments, including Motown, disco, dance anthems, power ballads, protest songs, and one-hit wonders.",
    "music_legends": "Featured collections built around legendary artists and performers across major TopSpot genres.",
    "specialty_mixes": "Specially curated mixes built around themes, missing favorites, holidays, duets, novelty songs, and crossovers.",
    "soft_rock_70s_90s": "Soft rock favorites from the 1970s through the 1990s, including road trip songs, singer-songwriters, yacht rock, easy listening, and love songs.",
}


def main() -> None:
    with Session(engine) as session:
        categories = session.exec(select(CollectionCategory)).all()

        updated = 0

        for category in categories:
            description = DESCRIPTIONS.get(category.slug)

            if not description:
                print(f"SKIP: {category.slug} — no description defined")
                continue

            category.intro = description
            session.add(category)
            updated += 1
            print(f"UPDATED: {category.name}")

        session.commit()

    print()
    print(f"Done. Updated {updated} collection category description(s).")


if __name__ == "__main__":
    main()