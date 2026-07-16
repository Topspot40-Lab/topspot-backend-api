from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    Artist,
    ArtistStory,
    MusicDocuseries,
    MusicDocuseriesLocale,
)


LANGUAGE_ORDER = {
    "en": 0,
    "es": 1,
    "pt-BR": 2,
}


def slugify(value: str) -> str:
    """
    Convert a display name such as "Johnny Cash" into "johnny_cash".
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text)
    return cleaned.strip("_").lower()


@dataclass(frozen=True)
class DocumentaryLanguage:
    """
    One localized version of documentary source material.
    """

    language_code: str
    locale_id: int
    story_text: str
    duration_seconds: int | None
    tts_bucket: str | None
    tts_key: str | None

    @property
    def youtube_key(self) -> str | None:
        """
        Return a possible legacy YouTube-audio key.

        Raw narration remains the source of truth. This property exists
        only for manifest compatibility and legacy asset discovery.
        """
        if not self.tts_key:
            return None

        replacements = {
            "music-docuseries/": "music-docuseries-youtube/",
            "artist-story/": "artist-story-youtube/",
        }

        for source_prefix, youtube_prefix in replacements.items():
            if self.tts_key.startswith(source_prefix):
                filename = self.tts_key[len(source_prefix):]
                return f"{youtube_prefix}{filename}"

        return self.tts_key

    @property
    def local_audio_name(self) -> str:
        return f"{self.language_code}_{self.locale_id}.mp3"


@dataclass(frozen=True)
class Documentary:
    """
    Read-only documentary content loaded from a TopSpot40 database source.

    Supported source types:
        music_docuseries
        artist_story
    """

    source_type: str
    source_id: int
    slug: str
    title: str
    subtitle: str
    artwork_url: str | None
    languages: tuple[DocumentaryLanguage, ...]

    @classmethod
    def load(
        cls,
        *,
        source_type: str,
        source_id: int,
    ) -> Documentary:
        normalized = source_type.strip().lower()

        if normalized == "music_docuseries":
            return cls.from_docuseries(source_id)

        if normalized in {"artist", "artist_story", "premium_artist"}:
            return cls.from_artist(source_id)

        raise ValueError(
            f"Unsupported documentary source type: {source_type}"
        )

    @classmethod
    def from_docuseries(cls, docuseries_id: int) -> Documentary:
        with Session(engine) as db:
            item = db.exec(
                select(MusicDocuseries).where(
                    MusicDocuseries.id == docuseries_id
                )
            ).first()

            if item is None:
                raise LookupError(
                    f"Music docuseries ID not found: {docuseries_id}"
                )

            locale_rows = list(
                db.exec(
                    select(MusicDocuseriesLocale).where(
                        MusicDocuseriesLocale.docuseries_id
                        == docuseries_id
                    )
                ).all()
            )

        if not locale_rows:
            raise LookupError(
                "No locale records found for music docuseries "
                f"ID {docuseries_id}"
            )

        locale_rows.sort(
            key=lambda row: LANGUAGE_ORDER.get(
                row.language_code,
                99,
            )
        )

        title, subtitle_from_title = cls._split_title(item.title)

        subtitle = (
            item.short_description
            or subtitle_from_title
            or ""
        )

        languages = tuple(
            DocumentaryLanguage(
                language_code=row.language_code,
                locale_id=int(row.id),
                story_text=row.story_text,
                duration_seconds=row.duration_seconds,
                tts_bucket=row.tts_bucket,
                tts_key=row.tts_key,
            )
            for row in locale_rows
            if row.id is not None
        )

        return cls(
            source_type="music_docuseries",
            source_id=int(item.id),
            slug=item.slug,
            title=title,
            subtitle=subtitle,
            artwork_url=item.artwork_url,
            languages=languages,
        )

    @classmethod
    def from_artist(cls, artist_id: int) -> Documentary:
        with Session(engine) as db:
            artist = db.get(Artist, artist_id)

            if artist is None:
                raise LookupError(
                    f"Artist ID not found: {artist_id}"
                )

            story_rows = list(
                db.exec(
                    select(ArtistStory).where(
                        ArtistStory.artist_id == artist_id
                    )
                ).all()
            )

        if not story_rows:
            raise LookupError(
                f"No ArtistStory records found for artist ID {artist_id}"
            )

        story_rows.sort(
            key=lambda row: LANGUAGE_ORDER.get(
                row.language_code,
                99,
            )
        )

        english_story = next(
            (
                row
                for row in story_rows
                if row.language_code == "en"
            ),
            story_rows[0],
        )

        artist_name = artist.artist_name.strip()
        subtitle = (
            english_story.title.strip()
            if english_story.title
            else f"The Story of {artist_name}"
        )

        languages = tuple(
            DocumentaryLanguage(
                language_code=row.language_code,
                locale_id=int(row.id),
                story_text=row.story_text,
                duration_seconds=row.duration_seconds,
                tts_bucket=row.tts_bucket,
                tts_key=row.tts_key,
            )
            for row in story_rows
            if row.id is not None
        )

        return cls(
            source_type="artist_story",
            source_id=int(artist.id),
            slug=slugify(artist_name),
            title=artist_name,
            subtitle=subtitle,
            artwork_url=artist.artist_artwork,
            languages=languages,
        )

    @staticmethod
    def _split_title(full_title: str) -> tuple[str, str]:
        title, separator, subtitle = full_title.partition(":")

        if not separator:
            return full_title.strip(), ""

        return title.strip(), subtitle.strip()

    def language(
        self,
        language_code: str,
    ) -> DocumentaryLanguage:
        for entry in self.languages:
            if entry.language_code == language_code:
                return entry

        raise KeyError(
            f"Documentary language not found: {language_code}"
        )

    def story(self, language_code: str) -> str:
        return self.language(language_code).story_text

    def language_codes(self) -> list[str]:
        return [
            entry.language_code
            for entry in self.languages
        ]

    def available_audio(
        self,
    ) -> Iterable[DocumentaryLanguage]:
        return (
            entry
            for entry in self.languages
            if entry.tts_bucket and entry.tts_key
        )
