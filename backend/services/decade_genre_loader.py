# backend/services/decade_genre_loader.py

import logging
from sqlmodel import select

from backend.database import get_db_session
from backend.models.dbmodels import (
    Track,
    Artist,
    TrackRanking,
    DecadeGenre,
    Decade,
    Genre,
)

logger = logging.getLogger(__name__)


def load_decade_genre_rows(
    *,
    decade: str,
    genre: str | None,
    start_rank: int,
    end_rank: int,
):

    """
    Query all tracks for (decade, genre) in [start_rank, end_rank].

    Returns a list of tuples:
      (Track, Artist, TrackRanking, Decade, Genre)
    """

    logger.info(
        "🧪 load_decade_genre_rows: decade=%s genre=%s ranks=%s–%s",
        decade,
        genre,
        start_rank,
        end_rank,
    )

    with get_db_session() as db:
        conditions = [
            Decade.slug == decade,
            TrackRanking.ranking >= start_rank,
            TrackRanking.ranking <= end_rank,
        ]

        # Only filter by genre if one was provided
        if genre is not None:
            conditions.append(Genre.slug == genre)

        q = (
            select(Track, Artist, TrackRanking, Decade, Genre)
            .join(Artist, Artist.id == Track.artist_id)
            .join(TrackRanking, TrackRanking.track_id == Track.id)
            .join(DecadeGenre, DecadeGenre.id == TrackRanking.decade_genre_id)
            .join(Decade, Decade.id == DecadeGenre.decade_id)
            .join(Genre, Genre.id == DecadeGenre.genre_id)
            .where(*conditions)
            .order_by(TrackRanking.ranking)
        )

        rows = db.exec(q).all()

        logger.info("🧪 load_decade_genre_rows → %d rows", len(rows))

        if rows:
            track, artist, tr_rank, dec, gen = rows[0]
            logger.debug(
                "   SAMPLE → track=%s artist=%s rank=%s decade=%s genre=%s",
                track.track_name,
                artist.artist_name,
                tr_rank.ranking,
                dec.decade_name,
                gen.genre_name,
            )

        return rows
