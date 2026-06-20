from sqlalchemy import text
from backend.database import engine

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT
            LOWER(a.artist_name) AS normalized_name,
            COUNT(*) AS artist_rows,
            STRING_AGG(a.id::text, ', ' ORDER BY a.id) AS artist_ids,
            COUNT(t.id) AS total_tracks
        FROM artist a
        LEFT JOIN track t ON t.artist_id = a.id
        GROUP BY LOWER(a.artist_name)
        HAVING COUNT(*) > 1
        ORDER BY total_tracks DESC, normalized_name
    """)).all()

for row in rows:
    print(f"{row.normalized_name:35} rows={row.artist_rows} ids={row.artist_ids:15} tracks={row.total_tracks}")
