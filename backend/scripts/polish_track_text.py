# backend/scripts/polish_track_text.py

import re
from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Track, Artist
from backend.services.xai_client import ask_xai


DETAIL_POLISH_PROMPT = """
Rewrite the following track description to be:

- 3 to 4 sentences ONLY
- Clear, engaging, and natural
- Focused on story, meaning, or interesting insight
- NO repetition of track name, artist, album, or rank
- NO DJ filler like "stay tuned", "coming up", or "right here"

Keep it tight and suitable for audio playback before a song.

Text:
{detail}
"""

ARTIST_POLISH_PROMPT = """
Rewrite the following artist description to be:

- 2 to 3 sentences ONLY
- Clear, engaging, and natural
- Focus on who they are and why they matter
- NO long history lesson
- NO DJ filler

Keep it tight and suitable for audio narration.

Text:
{artist}
"""


def clean_text(text: str) -> str:
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def run(limit: int = 5):
    with Session(engine) as session:
        statement = select(Track).where(Track.detail.is_not(None)).limit(limit)
        tracks = session.exec(statement).all()

        for track in tracks:
            print(f"Polishing track: {track.track_name}")

            if track.detail:
                prompt = DETAIL_POLISH_PROMPT.format(detail=track.detail)

                response = ask_xai(
                    "You are a concise radio-script editor for a music app.",
                    prompt,
                )

                track.detail = clean_text(response)
                session.add(track)

            artist = session.get(Artist, track.artist_id)

            if artist and artist.artist_description:
                prompt = ARTIST_POLISH_PROMPT.format(
                    artist=artist.artist_description
                )

                response = ask_xai(
                    "You are a concise radio-script editor for a music app.",
                    prompt,
                )

                artist.artist_description = clean_text(response)
                session.add(artist)

        session.commit()


if __name__ == "__main__":
    run(limit=5)