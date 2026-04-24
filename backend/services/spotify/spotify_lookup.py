from typing import Optional, Dict, Any
import logging

from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

logger = logging.getLogger("SPOTIFY_LOOKUP")

sp = Spotify(auth_manager=SpotifyClientCredentials())


def get_spotify_track_data(track_name: str, artist_name: str) -> Optional[Dict[str, Any]]:
    """
    Search Spotify and return normalized metadata for TopSpot40.
    """
    try:
        logger.info(f"🔎 Spotify lookup: {track_name} - {artist_name}")

        results = sp.search(
            q=f"track:{track_name} artist:{artist_name}",
            type="track",
            limit=1,
        )

        items = results.get("tracks", {}).get("items", [])

        if not items:
            logger.warning(f"❌ No match: {track_name} - {artist_name}")
            return None

        track = items[0]
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