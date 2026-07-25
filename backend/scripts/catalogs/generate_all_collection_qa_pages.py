from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection
from backend.scripts.catalogs.generate_collection_qa_page import main as generate_one


def main() -> None:
    with Session(engine) as session:
        collections = session.exec(
            select(Collection)
            .order_by(Collection.name)
        ).all()

    print(f"Generating QA pages for {len(collections)} collections...")

    for collection in collections:
        print(f"QA: {collection.slug}")
        # temporary simple call style
        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                "generate_collection_qa_page",
                "--slug",
                collection.slug,
            ]
            generate_one()
        finally:
            sys.argv = old_argv

    print("Done.")


if __name__ == "__main__":
    main()