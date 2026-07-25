from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection


UPDATES = {
    "easy_listening": "A relaxing collection of soft rock favorites featuring polished production, memorable melodies, and easygoing songs that became staples of radio throughout the 1970s, 1980s, and 1990s.",
    "road_trip": "A collection of driving songs, open-road favorites, and sing-along classics that capture the freedom, adventure, and memories of life on the highway.",
    "singer_songwriter": "A collection of personal, thoughtful songs from influential singer-songwriters whose storytelling, musicianship, and lyrics helped define an era.",
    "yacht_rock": "A collection of polished soft rock classics known for smooth vocals, sophisticated arrangements, and the laid-back sound that became known as Yacht Rock.",
    "country_duets": "A collection of memorable country music collaborations featuring legendary partnerships, timeless harmonies, and some of the genre's most beloved performances.",
    "pop_duets": "A collection of memorable pop collaborations featuring iconic vocal pairings, chart-topping hits, and unforgettable performances spanning multiple decades.",
    "video_game_themes": "A collection of iconic music from classic and modern video games, showcasing memorable themes and compositions that helped define generations of gaming experiences.",
    "legends_country": "A collection celebrating the most influential artists in country music history, featuring signature recordings from legendary performers whose songs shaped generations of listeners.",
    "legends_pop": "A collection celebrating the artists whose recordings defined popular music, influenced global culture, and became the soundtrack of their generations.",
    "legends_rock": "A collection honoring the pioneering artists, bands, and performers whose music helped shape the history and evolution of rock and roll.",
    "legends_rnb_soul": "A collection celebrating the artists whose powerful voices, innovative recordings, and lasting influence helped define R&B and soul music.",
    "legends_blues_jazz": "A collection honoring the legendary performers whose artistry, innovation, and influence helped shape the worlds of blues and jazz.",
    "legends_folk_acoustic": "A collection celebrating influential folk and acoustic artists whose storytelling, songwriting, and performances continue to inspire listeners.",
    "legends_latin_global": "A collection honoring internationally influential artists whose music helped showcase Latin and global sounds to audiences around the world.",
    "legends_tv_themes": "A collection celebrating the composers, performers, and themes that became unforgettable parts of television history.",
}


def main() -> None:
    with Session(engine) as session:
        rows = session.exec(select(Collection)).all()
        updated = 0

        for collection in rows:
            new_intro = UPDATES.get(collection.slug)

            if not new_intro:
                continue

            print()
            print(collection.name)
            print("OLD:", collection.intro)
            print("NEW:", new_intro)

            collection.intro = new_intro
            session.add(collection)
            updated += 1

        print()
        print(f"Ready to update {updated} collection(s).")

        answer = input("Save changes? Type YES: ").strip()

        if answer == "YES":
            session.commit()
            print("Saved.")
        else:
            session.rollback()
            print("Rolled back.")


if __name__ == "__main__":
    main()