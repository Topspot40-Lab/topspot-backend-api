"""Final verification of canonical localized delivery packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.studio.factory.production_contract import (
    LanguageCode,
    SUPPORTED_LANGUAGE_CODES,
)
from backend.studio.factory.production_execution import ProductionExecution


@dataclass(frozen=True, slots=True)
class VerifiedDeliveryPackage:
    """The verified four-file package for one localized documentary."""

    language_code: LanguageCode
    documentary: Path
    hook: Path
    intro: Path
    story: Path
    outro: Path

    @property
    def paths(self) -> tuple[Path, Path, Path, Path, Path]:
        """Return the documentary followed by canonical narration segments."""
        return (self.documentary, self.hook, self.intro, self.story, self.outro)


@dataclass(frozen=True, slots=True)
class _RequiredArtifact:
    label: str
    station: str
    artifact_id: str


def _required_artifacts(language_code: LanguageCode) -> tuple[_RequiredArtifact, ...]:
    return (
        _RequiredArtifact("documentary.mp4", f"localized_delivery_{language_code}", f"delivery.{language_code}.video"),
        _RequiredArtifact("narration/hook.mp3", f"narration_{language_code}", f"delivery.{language_code}.narration.hook"),
        _RequiredArtifact("narration/intro.mp3", f"narration_{language_code}", f"delivery.{language_code}.narration.intro"),
        _RequiredArtifact("narration/story.mp3", f"narration_{language_code}", f"delivery.{language_code}.narration.story"),
        _RequiredArtifact("narration/outro.mp3", f"narration_{language_code}", f"delivery.{language_code}.narration.outro"),
    )


def verify_final_delivery_packages(execution: ProductionExecution) -> tuple[VerifiedDeliveryPackage, ...]:
    """Return every contract delivery package after verified-completion checks.

    ``ProductionExecution`` remains the sole verification authority for file
    presence, non-empty content, and recorded size/hash integrity.
    """
    packages: list[VerifiedDeliveryPackage] = []

    for language_code in SUPPORTED_LANGUAGE_CODES:
        paths: list[Path] = []
        for required in _required_artifacts(language_code):
            try:
                execution.require_verified_completed(
                    station=required.station,
                    artifact_id=required.artifact_id,
                )
                paths.append(execution.output_path(
                    station=required.station,
                    artifact_id=required.artifact_id,
                ))
            except RuntimeError as exc:
                raise RuntimeError(
                    "Final delivery package verification failed for "
                    f"{language_code} {required.label} "
                    f"({required.artifact_id}): {exc}"
                ) from exc

        documentary, hook, intro, story, outro = paths
        packages.append(VerifiedDeliveryPackage(
            language_code=language_code,
            documentary=documentary,
            hook=hook,
            intro=intro,
            story=story,
            outro=outro,
        ))

    return tuple(packages)
