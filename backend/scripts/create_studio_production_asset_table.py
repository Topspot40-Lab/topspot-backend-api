from __future__ import annotations

from sqlalchemy import inspect
from sqlmodel import SQLModel

from backend.database import engine
from backend.models.studio_models import (
    StudioProductionAsset,
)


def main() -> None:
    table_name = (
        StudioProductionAsset.__tablename__
    )
    inspector = inspect(engine)

    if inspector.has_table(table_name):
        print(
            f"Table already exists: {table_name}"
        )
    else:
        SQLModel.metadata.create_all(
            engine,
            tables=[
                StudioProductionAsset.__table__
            ],
        )
        print(f"Created table: {table_name}")

    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)

    print()
    print("COLUMNS")
    print("=" * 60)

    for column in columns:
        print(
            f"{column['name']:24} "
            f"{column['type']}"
        )


if __name__ == "__main__":
    main()
