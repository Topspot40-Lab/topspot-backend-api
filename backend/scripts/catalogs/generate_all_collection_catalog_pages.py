from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection, CollectionCategory


def main() -> None:
    with Session(engine) as session:
        rows = session.exec(
            select(
                CollectionCategory.sort_order,
                CollectionCategory.name,
                Collection.slug,
                Collection.name,
            )
            .join(Collection, Collection.category_id == CollectionCategory.id)
            .order_by(
                CollectionCategory.sort_order,
                CollectionCategory.name,
                Collection.name,
            )
        ).all()

    current_group = None

    for sort_order, group_name, collection_slug, collection_name in rows:
        if group_name != current_group:
            current_group = group_name
            print()
            print("=" * 72)
            print(group_name.upper())
            print("=" * 72)

        print(f"{collection_slug:35} {collection_name}")


if __name__ == "__main__":
    main()