"""Canonical Artist Spotlight featured-artist eligibility queries."""
from __future__ import annotations

from sqlalchemy import bindparam, text

from backend.database import engine


def build_featured_artist_eligibility_query(
    *,
    genres: list[str] | None = None,
    genre: str | None = None,
    min_tracks: int = 3,
    max_tracks: int | None = None,
    featured_only: bool = True,
    per_genre: bool = False,
):
    """Build Program Mode's ranked-primary-artist eligibility query.

    ``per_genre`` retains a row for every qualifying artist/genre membership,
    which is the form Artist Radio needs when more than one genre is selected.
    The non-per-genre form preserves the Program Mode ``all`` behavior.
    """
    del min_tracks, max_tracks, featured_only  # Values are bound by the caller.
    if per_genre:
        if not genres:
            raise ValueError("per-genre featured eligibility requires genres")
        genre_columns = """
                g.slug AS genre_slug,
                g.genre_name AS genre_name,"""
        genre_predicate = "g.slug IN :genres"
        count_group_by = "a.id, g.slug, g.genre_name"
        output_group_by = "gc.artist_id, gc.artist_name, gc.genre_slug, gc.genre_name, gc.genre_track_count"
        order_prefix = "gc.genre_slug,"
        collection_catalog_union = ""
    else:
        genre_columns = ""
        genre_predicate = "(:genre IS NULL OR :genre = 'all' OR g.slug = :genre)"
        count_group_by = "a.id"
        output_group_by = "gc.artist_id, gc.artist_name, gc.genre_track_count"
        order_prefix = ""
        collection_catalog_union = """
            UNION
            SELECT
                t.id AS track_id,
                t.artist_id,
                g.slug AS genre_slug
            FROM collection_track_ranking ctr
            JOIN track t
                ON ctr.track_id = t.id
            JOIN artist_genre ag
                ON ag.artist_id = t.artist_id
            JOIN genre g
                ON g.id = ag.genre_id
        """

    query = text(f"""
        WITH eligible_catalog_tracks AS (
            SELECT
                t.id AS track_id,
                t.artist_id,
                g.slug AS genre_slug
            FROM track_ranking tr
            JOIN decade_genre dg
                ON tr.decade_genre_id = dg.id
            JOIN genre g
                ON dg.genre_id = g.id
            JOIN track t
                ON tr.track_id = t.id
            {collection_catalog_union}
        ),
        genre_counts AS (
            SELECT
                a.id AS artist_id,
                a.artist_name,
                {genre_columns}
                COUNT(DISTINCT ect.track_id) AS genre_track_count
            FROM eligible_catalog_tracks ect
            JOIN track t
                ON ect.track_id = t.id
            JOIN artist a
                ON t.artist_id = a.id
            JOIN genre g
                ON g.slug = ect.genre_slug
            WHERE {genre_predicate}
            GROUP BY {count_group_by}
        ),
        collection_counts AS (
            SELECT
                a.id AS artist_id,
                COUNT(DISTINCT ctr.track_id) AS collection_track_count
            FROM collection_track_ranking ctr
            JOIN track t
                ON ctr.track_id = t.id
            JOIN artist a
                ON t.artist_id = a.id
            GROUP BY a.id
        )
        SELECT
            gc.artist_id,
            gc.artist_name,
            {"gc.genre_slug, gc.genre_name," if per_genre else ""}
            EXISTS (
                SELECT 1
                FROM artist_story s
                WHERE s.artist_id = gc.artist_id
                  AND s.language_code = 'en'
            ) AS has_story,
            gc.genre_track_count,
            (
                SELECT COUNT(DISTINCT t2.id)
                FROM track t2
                WHERE t2.artist_id = gc.artist_id
                  AND (
                      EXISTS (SELECT 1 FROM track_ranking tr2 WHERE tr2.track_id = t2.id)
                      OR EXISTS (SELECT 1 FROM collection_track_ranking ctr2 WHERE ctr2.track_id = t2.id)
                  )
            ) AS total_track_count
        FROM genre_counts gc
        LEFT JOIN collection_counts cc
            ON cc.artist_id = gc.artist_id
        WHERE gc.genre_track_count >= :min_tracks
          AND (:max_tracks IS NULL OR gc.genre_track_count <= :max_tracks)
          AND (
              :featured_only = false
              OR EXISTS (
                  SELECT 1
                  FROM artist_story s
                  WHERE s.artist_id = gc.artist_id
                    AND s.language_code = 'en'
              )
          )
        GROUP BY {output_group_by}
        ORDER BY {order_prefix}
            gc.genre_track_count DESC,
            total_track_count DESC,
            gc.artist_name
    """)
    return query.bindparams(bindparam("genres", expanding=True)) if per_genre else query


def featured_artist_eligibility_rows(
    *,
    genres: list[str] | None = None,
    genre: str | None = None,
    min_tracks: int = 3,
    max_tracks: int | None = None,
    featured_only: bool = True,
    per_genre: bool = False,
) -> list[dict]:
    """Return Artist Spotlight Program Mode base-eligible artists."""
    query = build_featured_artist_eligibility_query(
        genres=genres,
        genre=genre,
        min_tracks=min_tracks,
        max_tracks=max_tracks,
        featured_only=featured_only,
        per_genre=per_genre,
    )
    params = {
        "min_tracks": min_tracks,
        "max_tracks": max_tracks,
        "featured_only": featured_only,
    }
    if per_genre:
        params["genres"] = genres
    else:
        params["genre"] = genre
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(query, params).mappings().all()]
