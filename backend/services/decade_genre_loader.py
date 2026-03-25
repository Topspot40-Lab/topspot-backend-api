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
    genre: str,
    start_rank: int,
    end_rank: int | None = None,
):
    """
    Query all tracks for (decade, genre).
    If end_rank is provided, limit to [start_rank, end_rank].
    Otherwise return full range from start_rank upward.
    """

    with get_db_session() as db:
        filters = [
            Decade.slug == decade,
            Genre.slug == genre,
            TrackRanking.ranking >= start_rank,
        ]

        if end_rank is not None:
            filters.append(TrackRanking.ranking <= end_rank)

        q = (
            select(Track, Artist, TrackRanking, Decade, Genre)
            .join(Artist, Artist.id == Track.artist_id)
            .join(TrackRanking, TrackRanking.track_id == Track.id)
            .join(DecadeGenre, DecadeGenre.id == TrackRanking.decade_genre_id)
            .join(Decade, Decade.id == DecadeGenre.decade_id)
            .join(Genre, Genre.id == DecadeGenre.genre_id)
            .where(*filters)
            .order_by(TrackRanking.ranking)
        )

        rows = db.exec(q).all()

        # 🔍 helpful debug
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

        # 🔥 add summary log (like collections)
        logger.info(
            "🎶 DG '%s/%s': returning %d tracks (range %s-%s)",
            decade,
            genre,
            len(rows),
            start_rank,
            end_rank if end_rank else "ALL"
        )

        return rows
