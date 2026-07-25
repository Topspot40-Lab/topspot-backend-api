from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import DecadeGenre
from backend.scripts.catalogs.generate_nostalgia_qa_page import main as generate_one


def main() -> None:
    with Session(engine) as session:
        programs = session.exec(
            select(DecadeGenre)
            .order_by(DecadeGenre.slug)
        ).all()

    print(f"Generating QA pages for {len(programs)} nostalgia programs...")

    for program in programs:
        print(f"QA: {program.slug}")
        import sys
        old_argv = sys.argv
        try:
            sys.argv = [
                "generate_nostalgia_qa_page",
                "--slug",
                program.slug,
            ]
            generate_one()
        finally:
            sys.argv = old_argv

    print("Done.")


if __name__ == "__main__":
    main()