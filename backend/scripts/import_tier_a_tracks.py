"""Safely import approved Tier A tracks without modifying rankings."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, Track
from backend.services.spotify.spotify_lookup import get_spotify_track_data

DEFAULT_MANIFEST = Path("backend/data/tier_a_track_expansion.csv")
DEFAULT_AUDIT = Path("backend/studio/work/tier_a_track_import_audit.csv")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import approved Tier A tracks without changing rankings."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument(
        "--save",
        action="store_true",
        help="Actually insert verified missing tracks. Default is dry-run.",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    required = {
        "cohort",
        "artist_id",
        "artist_name",
        "track_name",
        "historical_year",
        "accepted_spotify_artist_id",
    }

    if not rows:
        raise ValueError("Tier A manifest is empty")

    missing = required.difference(rows[0])
    if missing:
        raise ValueError(f"Manifest is missing columns: {sorted(missing)}")

    return rows


def write_audit(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "cohort",
        "artist_id",
        "artist_name",
        "track_name",
        "historical_year",
        "status",
        "spotify_track_id",
        "details",
    ]

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    manifest_rows = load_manifest(args.manifest)
    audit_rows: list[dict[str, str]] = []

    counts = {
        "would_create": 0,
        "created": 0,
        "existing_title": 0,
        "existing_spotify_id": 0,
        "wrong_artist": 0,
        "missing_artist": 0,
        "spotify_not_found": 0,
        "conflict": 0,
    }

    with Session(engine) as session:
        all_tracks = list(session.exec(select(Track)).all())

        for number, row in enumerate(manifest_rows, start=1):
            artist_id = int(row["artist_id"])
            artist_name = row["artist_name"].strip()
            track_name = row["track_name"].strip()
            historical_year = int(row["historical_year"])

            status = ""
            spotify_track_id = ""
            details = ""

            artist = session.get(Artist, artist_id)

            if artist is None:
                status = "missing_artist"
                details = f"Artist ID {artist_id} does not exist"
            else:
                accepted_spotify_artist_ids = {
                    artist.spotify_artist_id
                }

                authorized_alias = row.get(
                    "accepted_spotify_artist_id",
                    "",
                ).strip()

                if authorized_alias:
                    accepted_spotify_artist_ids.add(authorized_alias)

                existing_title = next(
                    (
                        track
                        for track in all_tracks
                        if track.artist_id == artist_id
                        and normalize(track.track_name) == normalize(track_name)
                    ),
                    None,
                )

                if existing_title is not None:
                    status = "existing_title"
                    spotify_track_id = existing_title.spotify_track_id
                    details = f"Existing track_id={existing_title.id}"
                else:
                    spotify = get_spotify_track_data(track_name, artist_name)

                    if spotify is None:
                        status = "spotify_not_found"
                        details = "Spotify returned no track"
                    elif (
                        spotify.get("spotify_artist_id")
                        not in accepted_spotify_artist_ids
                    ):
                        status = "wrong_artist"
                        details = (
                            f"Expected one of {sorted(accepted_spotify_artist_ids)!r}; "
                            f"returned {spotify.get('spotify_artist_id')!r}"
                        )
                    else:
                        spotify_track_id = str(spotify["spotify_track_id"])

                        existing_spotify = next(
                            (
                                track
                                for track in all_tracks
                                if track.spotify_track_id == spotify_track_id
                            ),
                            None,
                        )

                        if existing_spotify is not None:
                            if existing_spotify.artist_id == artist_id:
                                status = "existing_spotify_id"
                                details = (
                                    f"Existing track_id={existing_spotify.id}"
                                )
                            else:
                                status = "conflict"
                                details = (
                                    f"Spotify track belongs to existing "
                                    f"track_id={existing_spotify.id}, "
                                    f"artist_id={existing_spotify.artist_id}"
                                )
                        elif args.save:
                            track = Track(
                                track_name=track_name,
                                album_name=spotify.get("album_name"),
                                artist_display_name=artist.artist_name,
                                spotify_track_id=spotify_track_id,
                                duration_ms=spotify.get("duration_ms"),
                                popularity=spotify.get("popularity"),
                                album_artwork=spotify.get("album_artwork"),
                                year_released=historical_year,
                                artist_id=artist_id,
                                language="en",
                                version_notes="Gary-approved Tier A expansion",
                            )
                            session.add(track)
                            session.flush()
                            all_tracks.append(track)

                            status = "created"
                            details = f"Created track_id={track.id}"
                        else:
                            status = "would_create"
                            details = "Verified; dry-run only"

            counts[status] += 1

            print(
                f"{status.upper():20} {number:02d}/{len(manifest_rows)} | "
                f"{artist_name} | {track_name}"
            )

            audit_rows.append(
                {
                    "cohort": row["cohort"],
                    "artist_id": str(artist_id),
                    "artist_name": artist_name,
                    "track_name": track_name,
                    "historical_year": str(historical_year),
                    "status": status,
                    "spotify_track_id": spotify_track_id,
                    "details": details,
                }
            )

        if args.save:
            session.commit()
        else:
            session.rollback()

    write_audit(args.audit, audit_rows)

    print("\nTIER A IMPORT SUMMARY")
    print("=" * 70)
    print(f"Mode: {'SAVE' if args.save else 'DRY RUN'}")
    print(f"Manifest rows: {len(manifest_rows)}")

    for status, count in counts.items():
        if count:
            print(f"{status}: {count}")

    print(f"Audit: {args.audit}")

    if not args.save:
        print("No database changes were made.")


if __name__ == "__main__":
    main()