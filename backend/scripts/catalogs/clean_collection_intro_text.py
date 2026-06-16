from __future__ import annotations

import re

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection


def clean_intro(value: str | None) -> str | None:
    if not value:
        return value

    text = value.strip()

    # Pattern 1:
    # Welcome to TopSpot40 Collections Radio. This set is from the X collection group. Featuring Y, ...
    text = re.sub(
        r"^Welcome to TopSpot40 Collections Radio\.\s*"
        r"This set is from the .*? collection group\.\s*"
        r"Featuring .*?,\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Pattern 2:
    # From the X collection group, featuring Y, ...
    text = re.sub(
        r"^From the .*? collection group,\s*featuring .*?,\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Capitalize remaining first letter if needed
    if text:
        text = text[0].upper() + text[1:]

    return text


def main() -> None:
    with Session(engine) as session:
        collections = session.exec(
            select(Collection).order_by(Collection.name)
        ).all()

        changed = 0

        for collection in collections:
            old_intro = collection.intro
            new_intro = clean_intro(old_intro)

            if old_intro != new_intro:
                print()
                print(f"UPDATED: {collection.name}")
                print(f"OLD: {old_intro}")
                print(f"NEW: {new_intro}")

                collection.intro = new_intro
                session.add(collection)
                changed += 1

        print()
        print(f"Ready to update {changed} collection intro(s).")
        answer = input("Save changes? Type YES: ").strip()

        if answer == "YES":
            session.commit()
            print("Saved.")
        else:
            session.rollback()
            print("Rolled back. No changes saved.")


if __name__ == "__main__":
    main()
