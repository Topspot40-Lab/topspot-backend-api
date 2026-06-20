from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseriesCollection,
    MusicDocuseries,
    MusicDocuseriesLocale,
)

from sqlmodel import SQLModel


def main():
    SQLModel.metadata.create_all(
        engine,
        tables=[
            MusicDocuseriesCollection.__table__,
            MusicDocuseries.__table__,
            MusicDocuseriesLocale.__table__,
        ],
    )

    print("✅ Music Docuseries tables created or already exist.")


if __name__ == "__main__":
    main()