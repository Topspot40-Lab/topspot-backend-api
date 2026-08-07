"""Canonical, forward-looking contract for documentary productions.

This model deliberately does not parse or modify the version-1 production
manifests.  It defines the artifact boundary that future factory stations can
produce while those manifests continue to be supported unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Final, Literal


LanguageCode = Literal["en", "es", "pt-BR"]
SUPPORTED_LANGUAGE_CODES: Final[tuple[LanguageCode, ...]] = (
    "en",
    "es",
    "pt-BR",
)

_PRODUCTION_SLUG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*\Z")
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "con", "prn", "aux", "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_WINDOWS_ILLEGAL_CHARACTERS = frozenset('<>:"|?*')


def require_safe_relative_path(path: str, *, field: str) -> None:
    """Reject artifact paths that can escape a production work directory."""
    if not path or path.strip() != path:
        raise ValueError(f"{field} must be a safe relative path: {path!r}")

    windows_path = PureWindowsPath(path)
    posix_path = PurePosixPath(path)
    normalized_parts = path.replace("\\", "/").split("/")

    if (
        windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in normalized_parts)
    ):
        raise ValueError(f"{field} must be a safe relative path: {path!r}")

    for component in normalized_parts:
        device_name = component.split(".", maxsplit=1)[0].casefold()
        if (
            component.endswith((" ", "."))
            or device_name in _WINDOWS_RESERVED_NAMES
            or any(
                ord(character) < 32
                or character in _WINDOWS_ILLEGAL_CHARACTERS
                for character in component
            )
        ):
            raise ValueError(f"{field} must be a safe relative path: {path!r}")


def canonical_artifact_path(path: str) -> str:
    """Return the portable POSIX spelling exposed by the contract."""
    return path.replace("\\", "/")


def artifact_identity(path: str) -> str:
    """Return the case-insensitive Windows identity of an artifact path."""
    return canonical_artifact_path(path).casefold()


@dataclass(frozen=True, slots=True)
class SharedProductionAssets:
    """Artifacts researched or created once for every language edition."""

    storyboard_and_scene_plan: str
    approved_visuals: str
    visual_master: str
    opening_video: str
    provenance_report: str
    quality_report: str

    def __post_init__(self) -> None:
        paths = (
            self.storyboard_and_scene_plan,
            self.approved_visuals,
            self.visual_master,
            self.opening_video,
            self.provenance_report,
            self.quality_report,
        )
        for field, path in zip(
            (
                "storyboard_and_scene_plan",
                "approved_visuals",
                "visual_master",
                "opening_video",
                "provenance_report",
                "quality_report",
            ),
            paths,
            strict=True,
        ):
            require_safe_relative_path(path, field=field)
            object.__setattr__(
                self,
                field,
                canonical_artifact_path(path),
            )

        if len({artifact_identity(path) for path in paths}) != len(paths):
            raise ValueError("Shared asset paths must be unique")


@dataclass(frozen=True, slots=True)
class NarrationFiles:
    """The three delivered narration tracks; the hook belongs in ``intro``."""

    intro: str
    story: str
    outro: str
    hook_in_intro: Literal[True] = True

    def __post_init__(self) -> None:
        if self.hook_in_intro is not True:
            raise ValueError("The hook must be included in intro narration")

        for field, path in zip(
            ("intro", "story", "outro"),
            self.paths,
            strict=True,
        ):
            require_safe_relative_path(path, field=field)
            object.__setattr__(
                self,
                field,
                canonical_artifact_path(path),
            )

        if len({artifact_identity(path) for path in self.paths}) != len(self.paths):
            raise ValueError("Narration paths must be unique")

    @property
    def paths(self) -> tuple[str, str, str]:
        """Exactly the three required narration deliveries; no hook file."""
        return (self.intro, self.story, self.outro)


@dataclass(frozen=True, slots=True)
class DeliveryFiles:
    """Files delivered for one localized documentary edition."""

    video_mp4: str
    narration: NarrationFiles

    def __post_init__(self) -> None:
        require_safe_relative_path(self.video_mp4, field="video_mp4")
        object.__setattr__(
            self,
            "video_mp4",
            canonical_artifact_path(self.video_mp4),
        )
        if not self.video_mp4.lower().endswith(".mp4"):
            raise ValueError("video_mp4 must end with .mp4")
        if artifact_identity(self.video_mp4) in {
            artifact_identity(path)
            for path in self.narration.paths
        }:
            raise ValueError("Video and narration paths must be unique")

    @property
    def paths(self) -> tuple[str, str, str, str]:
        """The required four-file delivery set for an edition."""
        return (self.video_mp4, *self.narration.paths)


@dataclass(frozen=True, slots=True)
class PublishingAssets:
    """Prepared, localized assets for a future YouTube publishing step."""

    complete_audio_master: str
    captions: str
    thumbnail: str
    youtube_metadata: str
    youtube_chapters: str

    def __post_init__(self) -> None:
        for field, path in zip(
            (
                "complete_audio_master",
                "captions",
                "thumbnail",
                "youtube_metadata",
                "youtube_chapters",
            ),
            self.paths,
            strict=True,
        ):
            require_safe_relative_path(path, field=field)
            object.__setattr__(
                self,
                field,
                canonical_artifact_path(path),
            )

        if len({artifact_identity(path) for path in self.paths}) != len(self.paths):
            raise ValueError("Publishing asset paths must be unique")

    @property
    def paths(self) -> tuple[str, str, str, str, str]:
        return (
            self.complete_audio_master,
            self.captions,
            self.thumbnail,
            self.youtube_metadata,
            self.youtube_chapters,
        )


@dataclass(frozen=True, slots=True)
class LanguageEdition:
    language_code: LanguageCode
    delivery: DeliveryFiles
    publishing: PublishingAssets


@dataclass(frozen=True, slots=True)
class YouTubeMultilingualPolicy:
    """Preparation is mandatory; channel publishing awaits explicit approval."""

    preparation_enabled: Literal[True] = True
    publishing_enabled: Literal[False] = False

    def __post_init__(self) -> None:
        if self.preparation_enabled is not True:
            raise ValueError("YouTube multilingual preparation must be enabled")
        if self.publishing_enabled is not False:
            raise ValueError(
                "YouTube multilingual publishing requires channel approval"
            )


@dataclass(frozen=True, slots=True)
class DocumentaryProductionContract:
    """Complete canonical contract for one future documentary production."""

    slug: str
    shared_assets: SharedProductionAssets
    editions: tuple[LanguageEdition, ...]
    youtube_multilingual: YouTubeMultilingualPolicy = (
        YouTubeMultilingualPolicy()
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "editions", tuple(self.editions))

        if not _PRODUCTION_SLUG.fullmatch(self.slug):
            raise ValueError(f"Invalid production slug: {self.slug!r}")

        codes = tuple(edition.language_code for edition in self.editions)
        duplicates = sorted(
            code for code in set(codes) if codes.count(code) > 1
        )
        unexpected = sorted(
            code for code in codes if code not in SUPPORTED_LANGUAGE_CODES
        )
        missing = sorted(set(SUPPORTED_LANGUAGE_CODES) - set(codes))

        if duplicates:
            raise ValueError(
                "Duplicate language codes: " + ", ".join(duplicates)
            )
        if unexpected:
            raise ValueError(
                "Unexpected language codes: " + ", ".join(unexpected)
            )
        if missing:
            raise ValueError(
                "Missing language codes: " + ", ".join(missing)
            )

        all_paths = [
            *self.shared_paths,
            *(path for edition in self.editions for path in edition.delivery.paths),
            *(path for edition in self.editions for path in edition.publishing.paths),
        ]
        if (
            len({artifact_identity(path) for path in all_paths})
            != len(all_paths)
        ):
            raise ValueError("Artifact paths must not be reused across the contract")

    @property
    def shared_paths(self) -> tuple[str, str, str, str, str]:
        assets = self.shared_assets
        return (
            assets.storyboard_and_scene_plan,
            assets.approved_visuals,
            assets.visual_master,
            assets.provenance_report,
            assets.quality_report,
        )


def create_documentary_production_contract(
    production_slug: str,
) -> DocumentaryProductionContract:
    """Create the canonical artifact contract for a factory session.

    Every path is relative to ``work/<slug>/factory``. The function is
    intentionally independent of legacy production manifests so adoption
    cannot migrate or rewrite them as a side effect.
    """
    shared_assets = SharedProductionAssets(
        storyboard_and_scene_plan="shared/visual_plan.json",
        approved_visuals="shared/visual_research.json",
        visual_master="shared/visual_master.mp4",
        opening_video="shared/opening.mp4",
        provenance_report="shared/historical_photo_provenance.json",
        quality_report="shared/visual_qc.json",
    )

    editions = tuple(
        LanguageEdition(
            language_code=language_code,
            delivery=DeliveryFiles(
                video_mp4=f"delivery/{language_code}/documentary.mp4",
                narration=NarrationFiles(
                    intro=(
                        f"delivery/{language_code}/narration/intro.mp3"
                    ),
                    story=(
                        f"delivery/{language_code}/narration/story.mp3"
                    ),
                    outro=(
                        f"delivery/{language_code}/narration/outro.mp3"
                    ),
                ),
            ),
            publishing=PublishingAssets(
                complete_audio_master=(
                    f"publishing/{language_code}/complete_audio.mp3"
                ),
                captions=f"publishing/{language_code}/captions.vtt",
                thumbnail=f"publishing/{language_code}/thumbnail.png",
                youtube_metadata=(
                    f"publishing/{language_code}/youtube.json"
                ),
                youtube_chapters=(
                    f"publishing/{language_code}/chapters.txt"
                ),
            ),
        )
        for language_code in SUPPORTED_LANGUAGE_CODES
    )

    return DocumentaryProductionContract(
        slug=production_slug,
        shared_assets=shared_assets,
        editions=editions,
    )
