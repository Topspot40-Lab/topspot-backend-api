from __future__ import annotations

import re

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection


def clean_intro(text: str | None) -> str | None:
    if not text:
        return text

    value = text.strip()

    value = re.sub(
        r"^Welcome to TopSpot40 Collections Radio\.\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^This set is from the .*? collection group\.\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^From the .*? collection group,\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^featuring\s+.*?,\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^Featuring\s+.*?,\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(r"\s+", " ", value).strip()

    if value:
        value = value[0].upper() + value[1:]

    return value


def main() -> None:
    with Session(engine) as session:
        rows = session.exec(
            select(Collection).order_by(Collection.name)
        ).all()

        changed = 0

        for collection in rows:
            old = collection.intro
            new = clean_intro(old)

            if old != new:
                print()
                print(collection.name)
                print("OLD:", old)
                print("NEW:", new)

                collection.intro = new
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
            print("Rolled back.")


if __name__ == "__main__":
    main()