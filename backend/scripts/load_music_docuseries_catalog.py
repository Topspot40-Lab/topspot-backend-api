from __future__ import annotations

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseriesCollection,
    MusicDocuseries,
)


CATALOG = [
    {
        "slug": "history_eras",
        "name": "History & Eras",
        "description": "Docuseries about musical decades and eras.",
        "items": [
            ("fabulous_fifties", "The Fabulous Fifties", "feature"),
            ("swinging_sixties", "The Swinging Sixties", "feature"),
            ("seventies_decade_of_change", "The Seventies: A Decade of Change", "feature"),
            ("mtv_and_the_eighties", "MTV and the Eighties", "feature"),
            ("alternative_nation_nineties", "Alternative Nation: The Nineties", "standard"),
            ("music_in_the_new_millennium", "Music in the New Millennium", "standard"),
        ],
    },
    {
        "slug": "movements_revolutions",
        "name": "Movements & Revolutions",
        "description": "Docuseries about musical movements that changed culture.",
        "items": [
            ("birth_of_rock_and_roll", "The Birth of Rock & Roll", "feature"),
            ("british_invasion", "The British Invasion", "standard"),
            ("rise_of_motown", "The Rise of Motown", "standard"),
            ("birth_of_hip_hop", "The Birth of Hip-Hop", "feature"),
            ("napster_changes_music_forever", "Napster Changes Music Forever", "standard"),
            ("mtv_revolution", "The MTV Revolution", "standard"),
            ("story_of_mariachi", "The Story of Mariachi", "standard"),
            ("birth_of_bossa_nova", "The Birth of Bossa Nova", "standard"),
            ("story_of_samba", "The Story of Samba", "standard"),
            ("story_of_tango", "The Story of Tango", "standard"),
            ("story_of_flamenco", "The Story of Flamenco", "standard"),
        ],
    },
    {
        "slug": "legends_rivalries",
        "name": "Legends & Rivalries",
        "description": "Docuseries about famous debates, rivalries, and musical legends.",
        "items": [
            ("beatles_vs_stones", "Beatles vs. Stones", "standard"),
            ("elvis_vs_sinatra", "Elvis vs. Sinatra", "standard"),
            ("country_traditionalists_vs_country_pop", "Country Traditionalists vs. Country Pop", "short"),
            ("ranchera_vs_norteno", "Ranchera vs. Norteño", "standard"),
            ("vicente_fernandez_vs_antonio_aguilar", "Vicente Fernández vs. Antonio Aguilar", "standard"),
            ("bossa_nova_vs_samba", "Bossa Nova vs. Samba", "standard"),
        ],
    },
    {
        "slug": "songs_stories",
        "name": "Songs & Stories",
        "description": "Docuseries about songs, lyrics, and the stories behind them.",
        "items": [
            ("story_behind_american_pie", "The Story Behind American Pie", "standard"),
            ("one_hit_wonders", "One-Hit Wonders", "short"),
            ("songs_banned_from_radio", "Songs Banned from Radio", "short"),
        ],
    },
    {
        "slug": "mysteries_tragedies",
        "name": "Mysteries & Tragedies",
        "description": "Docuseries about mysteries, losses, legends, and tragic moments in music.",
        "items": [
            ("day_the_music_died", "The Day the Music Died", "short"),
            ("the_27_club", "The 27 Club", "short"),
            ("lost_recordings_music_mysteries", "Lost Recordings and Music Mysteries", "short"),
            ("mystery_legacy_pedro_infante", "The Mystery and Legacy of Pedro Infante", "standard"),
            ("tragic_story_mamonas_assassinas", "The Tragic Story of Mamonas Assassinas", "standard"),
        ],
    },
    {
        "slug": "landmark_events",
        "name": "Landmark Events",
        "description": "Docuseries about concerts, festivals, and historic music events.",
        "items": [
            ("woodstock", "Woodstock", "feature"),
        ],
    },
    {
        "slug": "people_behind_the_music",
        "name": "The People Behind the Music",
        "description": (
            "Meet the broadcasters, producers, executives, managers, engineers, "
            "inventors, and visionaries who shaped popular music behind the scenes."
        ),
        "items": [
            (
                "ed_sullivan",
                "Ed Sullivan: The Man Who Introduced America to Rock & Roll",
                "standard",
            ),
            (
                "dick_clark",
                "Dick Clark: America's Oldest Teenager",
                "standard",
            ),
            (
                "don_cornelius",
                "Don Cornelius: The Soul Train Revolution",
                "standard",
            ),
            (
                "casey_kasem",
                "Casey Kasem: The Voice of America's Top 40",
                "standard",
            ),
            (
                "alan_freed",
                "Alan Freed: The DJ Who Named Rock & Roll",
                "standard",
            ),
            (
                "sam_phillips",
                "Sam Phillips: The Man Who Discovered Elvis",
                "standard",
            ),
            (
                "berry_gordy",
                "Berry Gordy: Building the Motown Sound",
                "standard",
            ),
            (
                "george_martin",
                "George Martin: The Fifth Beatle",
                "standard",
            ),
            (
                "quincy_jones",
                "Quincy Jones: The Producer Who Changed Pop Music",
                "standard",
            ),
            (
                "phil_spector",
                "Phil Spector: The Wall of Sound",
                "standard",
            ),
            (
                "tom_dowd",
                "Tom Dowd: The Engineer Who Changed Recording Forever",
                "standard",
            ),
            (
                "ahmet_ertegun",
                "Ahmet Ertegun: The Atlantic Records Story",
                "standard",
            ),
            (
                "clive_davis",
                "Clive Davis: The Executive with the Golden Ear",
                "standard",
            ),
            (
                "brian_epstein",
                "Brian Epstein: The Man Who Managed the Beatles",
                "standard",
            ),
            (
                "colonel_tom_parker",
                "Colonel Tom Parker: The Business of Elvis Presley",
                "standard",
            ),
            (
                "les_paul",
                "Les Paul: The Inventor Who Changed Recording Forever",
                "standard",
            ),
        ],
    },
]


def get_or_create_collection(session: Session, data: dict, sort_order: int) -> MusicDocuseriesCollection:
    collection = session.exec(
        select(MusicDocuseriesCollection).where(
            MusicDocuseriesCollection.slug == data["slug"]
        )
    ).first()

    if collection:
        collection.name = data["name"]
        collection.description = data["description"]
        collection.sort_order = sort_order
        collection.is_active = True
        return collection

    collection = MusicDocuseriesCollection(
        slug=data["slug"],
        name=data["name"],
        description=data["description"],
        sort_order=sort_order,
        is_active=True,
    )
    session.add(collection)
    session.flush()
    return collection


def upsert_docuseries(
    session: Session,
    collection: MusicDocuseriesCollection,
    slug: str,
    title: str,
    target_length: str,
    sort_order: int,
) -> MusicDocuseries:
    item = session.exec(
        select(MusicDocuseries).where(MusicDocuseries.slug == slug)
    ).first()

    if item:
        item.collection_id = collection.id
        item.title = title
        item.target_length = target_length
        item.sort_order = sort_order
        item.is_active = True
        return item

    item = MusicDocuseries(
        collection_id=collection.id,
        slug=slug,
        title=title,
        target_length=target_length,
        sort_order=sort_order,
        is_active=True,
    )
    session.add(item)
    return item


def main() -> None:
    with Session(engine) as session:
        for collection_index, collection_data in enumerate(CATALOG, start=1):
            collection = get_or_create_collection(
                session=session,
                data=collection_data,
                sort_order=collection_index,
            )

            for item_index, (slug, title, target_length) in enumerate(
                collection_data["items"],
                start=1,
            ):
                upsert_docuseries(
                    session=session,
                    collection=collection,
                    slug=slug,
                    title=title,
                    target_length=target_length,
                    sort_order=item_index,
                )

        session.commit()

    print("✅ Music Docuseries catalog loaded.")


if __name__ == "__main__":
    main()