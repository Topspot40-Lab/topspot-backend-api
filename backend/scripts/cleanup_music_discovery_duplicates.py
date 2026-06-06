from __future__ import annotations

from sqlmodel import Session
from sqlalchemy import text

from backend.database import engine


DELETE_IDS = [
    39, 86, 632, 657, 684,
    17, 37,
    52, 116,
    429, 505, 529,
    432, 484, 509,
    480, 504,
    520, 544,
    455, 507,
    242, 289,
    158, 231, 693,
    162, 241,
    174, 219,
    630, 652, 677,
    100, 628, 654, 678,
    638, 688,
    648, 692,
    660, 695,
    669, 719,
    633, 653,
]


def main() -> None:
    print(f"Records to delete: {len(DELETE_IDS)}")

    with Session(engine) as session:

        rows = session.execute(
            text("""
                SELECT id, category, topic, title
                FROM music_discovery
                WHERE id = ANY(:ids)
                ORDER BY id
            """),
            {"ids": DELETE_IDS},
        ).fetchall()

        print("\nPreview:")
        for row in rows:
            print(
                f"{row.id:4} | "
                f"{row.category:20} | "
                f"{row.topic}"
            )

        confirm = input("\nDelete these records? (yes/no): ")

        if confirm.lower() != "yes":
            print("Cancelled.")
            return

        session.execute(
            text("""
                DELETE FROM music_discovery
                WHERE id = ANY(:ids)
            """),
            {"ids": DELETE_IDS},
        )

        session.commit()

    print(f"\nDeleted {len(DELETE_IDS)} records.")


if __name__ == "__main__":
    main()