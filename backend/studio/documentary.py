from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import (
    MusicDocuseries,
    MusicDocuseriesLocale,
)


LANGUAGE_ORDER = {
    "en": 0,
    "es": 1,
    "pt-BR": 2,
}


@dataclass(frozen=True)
class DocumentaryLanguage:
    """
    One localized version of a documentary.

    This object describes source content stored in the database.
    It does not describe downloaded or generated production files.
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
        Return the expected YouTube narration key.

        Existing source:
            music-docuseries/100.mp3

        YouTube version:
            music-docuseries-youtube/100.mp3
        """
        if not self.tts_key:
            return None

        prefix = "music-docuseries/"

        if self.tts_key.startswith(prefix):
            filename = self.tts_key[len(prefix):]
            return f"music-docuseries-youtube/{filename}"

        return self.tts_key

    @property
    def local_audio_name(self) -> str:
        return f"{self.language_code}_{self.locale_id}.mp3"


@dataclass(frozen=True)
class Documentary:
    """
    Read-only documentary content loaded from the TopSpot40 database.

    The Documentary owns:
        - identity
        - title and subtitle
        - source story text
        - languages
        - source narration metadata

    It does not own:
        - production status
        - generated images
        - rendered video
        - review state
        - publishing state
    """

    source_type: str
    source_id: int
    slug: str
    title: str
    subtitle: str
    artwork_url: str | None
    languages: tuple[DocumentaryLanguage, ...]

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
