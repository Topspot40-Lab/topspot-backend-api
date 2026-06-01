import csv
from pathlib import Path

from sqlalchemy import text

from backend.database import engine


BASE_DIR = Path(__file__).resolve().parents[2]

CSV_FILE = (
    BASE_DIR
    / "backend"
    / "data"
    / "heritage_collections"
    / "heritage_collection_intros.csv"
)


def main() -> None:
    with CSV_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    with engine.begin() as conn:
        for row in rows:
            collection_slug = row["collection_slug"].strip()

            collection_id = conn.execute(
                text("""
                    SELECT id
                    FROM collection
                    WHERE slug = :slug
                """),
                {"slug": collection_slug},
            ).scalar_one()

            conn.execute(
                text("""
                    UPDATE collection
                    SET intro = :intro,
                        updated_at = NOW()
                    WHERE id = :collection_id
                """),
                {
                    "collection_id": collection_id,
                    "intro": row["intro_en"].strip(),
                },
            )

            for language_code, column_name in (
                ("es", "intro_es"),
                ("ptbr", "intro_ptbr"),
            ):
                conn.execute(
                    text("""
                        INSERT INTO collection_locale (
                            collection_id,
                            language_code,
                            intro,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :collection_id,
                            :language_code,
                            :intro,
                            NOW(),
                            NOW()
                        )
                        ON CONFLICT (collection_id, language_code)
                        DO UPDATE
                        SET intro = EXCLUDED.intro,
                            updated_at = NOW()
                    """),
                    {
                        "collection_id": collection_id,
                        "language_code": language_code,
                        "intro": row[column_name].strip(),
                    },
                )

            print(f"Loaded intros for {collection_slug}")

    print(f"\nLoaded {len(rows)} Heritage collection intros.")


if __name__ == "__main__":
    main()