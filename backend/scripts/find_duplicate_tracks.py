from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import text

from backend.database import engine


def norm(value: str | None) -> str:
    value = (value or "").lower().strip()
    value = value.replace("&", "and")
    value = value.replace("'", "")
    value = value.replace("’", "")
    value = "".join(ch for ch in value if ch.isalnum() or ch.isspace())
    return " ".join(value.split())


def title_similarity(a: str | None, b: str | None) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def main() -> None:
    sql = text("""
        select
            t.id as track_id,
            t.track_name,
            t.spotify_track_id,
            a.id as artist_id,
            a.artist_name
        from track t
        join artist a on a.id = t.artist_id
        order by a.artist_name, t.track_name, t.id
    """)

    with engine.begin() as conn:
        rows = conn.execute(sql).mappings().all()

    candidates = []

    for i, left in enumerate(rows):
        for right in rows[i + 1:]:
            if left["artist_id"] != right["artist_id"]:
                continue

            score = title_similarity(left["track_name"], right["track_name"])

            if score < 0.72:
                continue

            # Prefer the one with Spotify ID as KEEP
            if left["spotify_track_id"] and not right["spotify_track_id"]:
                keep, merge = left, right
            elif right["spotify_track_id"] and not left["spotify_track_id"]:
                keep, merge = right, left
            else:
                keep, merge = left, right

            candidates.append((score, keep, merge))

    candidates.sort(key=lambda x: x[0], reverse=True)

    print("=" * 80)
    print("POSSIBLE DUPLICATE TRACKS")
    print("=" * 80)

    for score, keep, merge in candidates[:200]:
        print()
        print("=" * 80)
        print(f"Similarity: {score:.2%}")
        print(f"Artist:     {keep['artist_name']}  (artist_id={keep['artist_id']})")
        print()
        print(f"KEEP:  {keep['track_id']} | {keep['track_name']} | {keep['spotify_track_id']}")
        print(f"MERGE: {merge['track_id']} | {merge['track_name']} | {merge['spotify_track_id']}")

        if keep["spotify_track_id"] and not merge["spotify_track_id"]:
            print("Recommendation: merge/remap collection rankings to KEEP if same recording.")


if __name__ == "__main__":
    main()