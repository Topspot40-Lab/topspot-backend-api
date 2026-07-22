from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection
from backend.scripts.catalogs.generate_collection_catalog_html import generate_collection_page


def main() -> None:
    with Session(engine) as session:
        collections = session.exec(
            select(Collection)
            .order_by(Collection.name)
        ).all()

    for collection in collections:
        print(f"Generating {collection.slug}...")
        generate_collection_page(collection.slug)

    print()
    print(f"Done. Generated {len(collections)} catalog page(s).")


if __name__ == "__main__":
    main()