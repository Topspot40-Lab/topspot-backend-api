from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import DecadeGenre
from backend.scripts.catalogs.generate_decade_genre_catalog_html import (
    generate_decade_genre_page,
)


def main() -> None:
    with Session(engine) as session:
        rows = session.exec(
            select(DecadeGenre.slug)
            .where(DecadeGenre.slug.is_not(None))
            .order_by(DecadeGenre.slug)
        ).all()

    generated = 0

    for slug in rows:
        print(f"Generating {slug}...")
        generate_decade_genre_page(slug)
        generated += 1

    print()
    print(f"Done. Generated {generated} nostalgia catalog page(s).")


if __name__ == "__main__":
    main()