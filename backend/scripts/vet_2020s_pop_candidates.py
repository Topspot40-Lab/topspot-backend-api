"""Read-only Spotify and database checks for new 2020s Pop selections.

    python -m backend.scripts.vet_2020s_pop_candidates --output 2020s-pop-candidates.json
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy import text


CANDIDATES = (
    (6, "As It Was", "Harry Styles"),
    (7, "Anti-Hero", "Taylor Swift"),
    (8, "Flowers", "Miley Cyrus"),
    (9, "Kill Bill", "SZA"),
    (10, "Espresso", "Sabrina Carpenter"),
    (11, "BIRDS OF A FEATHER", "Billie Eilish"),
    (12, "APT.", "ROSÉ"),
    (28, "Pink Pony Club", "Chappell Roan"),
    (44, "Ordinary", "Alex Warren"),
    (45, "I Just Might", "Bruno Mars"),
)


def normalize(s: str) -> str:
    plain = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "", plain)


def inspect(connection, spotify):
    entries=[]
    for rank, title, artist in CANDIDATES:
        result=spotify.search(q=f"{title} {artist}", type="track", market="US", limit=15)
        options=[]
        for track in result["tracks"]["items"]:
            if normalize(track["name"]) != normalize(title):
                continue
            if not any(normalize(a["name"]) == normalize(artist) for a in track["artists"]):
                continue
            album=track["album"]
            existing=connection.execute(text("""
                SELECT id, track_name, detail IS NOT NULL AS has_detail, duration_ms
                  FROM track WHERE spotify_track_id=:spotify_id
            """), {"spotify_id":track["id"]}).mappings().all()
            options.append({"spotify_track_id":track["id"],"spotify_url":track["external_urls"]["spotify"],
                            "spotify_title":track["name"],"artists":[{"name":a["name"],"id":a["id"]} for a in track["artists"]],
                            "album_name":album["name"],"album_type":album["album_type"],
                            "release_date":album["release_date"],"duration_ms":track["duration_ms"],
                            "explicit":track["explicit"],"popularity":track.get("popularity"),
                            "album_artwork":album["images"][0]["url"] if album["images"] else None,
                            "database_tracks":[dict(r) for r in existing]})
            if len(options) == 5:
                break
        entries.append({"rank":rank,"title":title,"artist":artist,"options":options})
        print(f"#{rank}: {title} — {artist}: {len(options)} exact Spotify options", flush=True)
    return {"source":"Spotify Web API track search, US market; verify recording before apply",
            "candidates":entries}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    from backend.services.spotify.spotify_lookup import sp
    from backend.database import engine
    with engine.connect() as connection:
        report=inspect(connection,sp)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"Saved {args.output}")


if __name__=="__main__":
    main()
