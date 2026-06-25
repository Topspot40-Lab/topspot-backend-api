from typing import Optional, Dict, Any
import logging

from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

logger = logging.getLogger("SPOTIFY_LOOKUP")

sp = Spotify(auth_manager=SpotifyClientCredentials())


def clean_search_text(value: str) -> str:
    value = value or ""
    value = value.replace("’", "'")
    value = value.replace("&", "and")
    value = value.replace("'", "")
    value = " ".join(value.split())
    return value.strip()


def loose(value: str | None) -> str:
    value = clean_search_text(value or "").lower()
    return "".join(ch for ch in value if ch.isalnum())


def artist_matches(expected_artist: str, spotify_artists: list[dict]) -> bool:
    expected = loose(expected_artist)

    for artist in spotify_artists:
        found = loose(artist.get("name", ""))
        if expected and (expected in found or found in expected):
            return True

    return False


def normalize_track_result(track: dict) -> Optional[Dict[str, Any]]:
    album = track["album"]
    spotify_artist_id = track["artists"][0]["id"]

    release_date = album.get("release_date", "")
    year = int(release_date[:4]) if release_date else None

    artist_artwork = get_artist_artwork(spotify_artist_id)

    return {
        "spotify_track_id": track["id"],
        "spotify_artist_id": spotify_artist_id,
        "duration_ms": track.get("duration_ms"),
        "popularity": track.get("popularity"),
        "album_name": album.get("name"),
        "album_artwork": album["images"][0]["url"] if album.get("images") else None,
        "year_released": year,
        "artist_artwork": artist_artwork,
    }


def get_spotify_track_data(track_name: str, artist_name: str) -> Optional[Dict[str, Any]]:
    """
    Search Spotify and return normalized metadata for TopSpot40.
    Tries strict search first, then looser fallback searches.
    """
    try:
        logger.info(f"🔎 Spotify lookup: {track_name} - {artist_name}")

        cleaned_track = clean_search_text(track_name)
        cleaned_artist = clean_search_text(artist_name)

        queries = [
            f'track:"{cleaned_track}" artist:"{cleaned_artist}"',
            f'track:{cleaned_track} artist:{cleaned_artist}',
            f'"{cleaned_track}" "{cleaned_artist}"',
            f'{cleaned_track} {cleaned_artist}',
            f'track:"{cleaned_track}"',
        ]

        seen_queries = []

        for query in queries:
            if query in seen_queries:
                continue

            seen_queries.append(query)

            results = sp.search(
                q=query,
                type="track",
                limit=10,
            )

            items = results.get("tracks", {}).get("items", [])

            if not items:
                continue

            for track in items:
                spotify_title = track.get("name", "")
                title_ok = (
                    loose(track_name) in loose(spotify_title)
                    or loose(spotify_title) in loose(track_name)
                )
                artist_ok = artist_matches(artist_name, track.get("artists", []))

                if title_ok and artist_ok:
                    logger.info(f"✅ Spotify match via query: {query}")
                    return normalize_track_result(track)

            if query in queries[:2]:
                track = items[0]
                logger.info(f"✅ Spotify fallback first result via query: {query}")
                return normalize_track_result(track)

        logger.warning(f"❌ No match: {track_name} - {artist_name}")
        return None

    except Exception:
        logger.exception(f"🔥 Spotify lookup failed: {track_name} - {artist_name}")
        return None


def get_artist_artwork(artist_id: str) -> Optional[str]:
    try:
        artist_data = sp.artist(artist_id)
        return artist_data["images"][0]["url"] if artist_data.get("images") else None
    except Exception:
        logger.exception(f"⚠️ Artwork fetch failed for artist {artist_id}")
        return None


def get_spotify_artist_data(artist_name: str) -> Optional[Dict[str, Any]]:
    """
    Search Spotify for an artist and return normalized metadata.
    """
    try:
        logger.info(f"🔎 Spotify artist lookup: {artist_name}")

        results = sp.search(
            q=f"artist:{artist_name}",
            type="artist",
            limit=5,
        )

        items = results.get("artists", {}).get("items", [])

        if not items:
            logger.warning(f"❌ No artist match: {artist_name}")
            return None

        artist = None
        for item in items:
            if item["name"].strip().lower() == artist_name.strip().lower():
                artist = item
                break

        if artist is None:
            artist = items[0]

        return {
            "spotify_artist_id": artist["id"],
            "artist_name": artist["name"],
            "artist_artwork": (
                artist["images"][0]["url"]
                if artist.get("images")
                else None
            ),
            "genres": artist.get("genres", []),
            "followers": artist.get("followers", {}).get("total", 0),
        }

    except Exception:
        logger.exception(f"🔥 Spotify artist lookup failed: {artist_name}")
        return None


def get_spotify_artist_candidates(artist_name: str, limit: int = 5) -> list[dict]:
    try:
        results = sp.search(
            q=f"artist:{artist_name}",
            type="artist",
            limit=limit,
        )

        items = results.get("artists", {}).get("items", [])

        candidates = []
        for artist in items:
            candidates.append({
                "spotify_artist_id": artist["id"],
                "artist_name": artist["name"],
                "artist_artwork": (
                    artist["images"][0]["url"]
                    if artist.get("images")
                    else None
                ),
                "genres": artist.get("genres", []),
                "followers": artist.get("followers", {}).get("total", 0),
            })

        return candidates

    except Exception:
        logger.exception(f"🔥 Spotify artist candidate lookup failed: {artist_name}")
        return []