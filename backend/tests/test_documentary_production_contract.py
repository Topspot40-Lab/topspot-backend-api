from __future__ import annotations

from dataclasses import replace

import pytest

from backend.studio.factory.production_contract import (
    DocumentaryProductionContract,
    DeliveryFiles,
    LanguageEdition,
    NarrationFiles,
    PublishingAssets,
    SharedProductionAssets,
    YouTubeMultilingualPolicy,
)


def _edition(code: str) -> LanguageEdition:
    safe_code = code.replace("-", "_")
    return LanguageEdition(
        language_code=code,  # type: ignore[arg-type]
        delivery=DeliveryFiles(
            video_mp4=f"delivery/{safe_code}/documentary.mp4",
            narration=NarrationFiles(
                hook=f"delivery/{safe_code}/hook.mp3",
                intro=f"delivery/{safe_code}/intro.mp3",
                story=f"delivery/{safe_code}/story.mp3",
                outro=f"delivery/{safe_code}/outro.mp3",
            ),
        ),
        publishing=PublishingAssets(
            complete_audio_master=(
                f"publishing/{safe_code}/complete_audio.mp3"
            ),
            captions=f"publishing/{safe_code}/captions.vtt",
            thumbnail=f"publishing/{safe_code}/thumbnail.png",
            youtube_metadata=f"publishing/{safe_code}/youtube.json",
            youtube_chapters=f"publishing/{safe_code}/chapters.txt",
        ),
    )


def _contract(*, editions: tuple[LanguageEdition, ...] | None = None) -> DocumentaryProductionContract:
    return DocumentaryProductionContract(
        slug="ed_sullivan",
        shared_assets=SharedProductionAssets(
            storyboard_and_scene_plan="shared/storyboard.json",
            approved_visuals="shared/approved_visuals.json",
            visual_master="shared/visual_master.mp4",
            opening_video="shared/opening.mp4",
            hook_visual="shared/hook.png",
            provenance_report="shared/provenance.json",
            quality_report="shared/quality.json",
        ),
        editions=editions or (_edition("en"), _edition("es"), _edition("pt-BR")),
    )


def test_contract_requires_all_three_language_editions() -> None:
    contract = _contract()

    assert [edition.language_code for edition in contract.editions] == [
        "en",
        "es",
        "pt-BR",
    ]


def test_contract_freezes_caller_supplied_editions_list() -> None:
    editions = [_edition("en"), _edition("es"), _edition("pt-BR")]
    contract = _contract(editions=editions)  # type: ignore[arg-type]

    editions.pop()
    editions.append(_edition("en"))

    assert isinstance(contract.editions, tuple)
    assert [edition.language_code for edition in contract.editions] == [
        "en",
        "es",
        "pt-BR",
    ]
    assert len(
        {
            path
            for edition in contract.editions
            for path in edition.delivery.paths
        }
    ) == 15

def test_each_edition_has_exactly_five_delivery_files() -> None:
    contract = _contract()

    for edition in contract.editions:
        assert len(edition.delivery.paths) == 5
        assert edition.delivery.paths[0].endswith(".mp4")
        assert edition.delivery.paths[1:] == edition.delivery.narration.paths


def test_shared_assets_are_singleton_and_not_repeated_per_language() -> None:
    contract = _contract()

    assert len(contract.shared_paths) == 6
    assert len(set(contract.shared_paths)) == 6
    assert not set(contract.shared_paths).intersection(
        path
        for edition in contract.editions
        for path in (*edition.delivery.paths, *edition.publishing.paths)
    )


@pytest.mark.parametrize(
    ("editions", "message"),
    [
        ((_edition("en"), _edition("es")), "Missing language codes: pt-BR"),
        ((_edition("en"), _edition("en"), _edition("pt-BR")), "Duplicate language codes: en"),
        ((_edition("en"), _edition("es"), _edition("fr")), "Unexpected language codes: fr"),
    ],
)
def test_contract_rejects_missing_duplicate_or_unexpected_languages(
    editions: tuple[LanguageEdition, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _contract(editions=editions)


def test_missing_story_audio_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="story must be a safe relative path"):
        NarrationFiles(
            hook="delivery/en/hook.mp3",
            intro="delivery/en/intro.mp3",
            story="",
            outro="delivery/en/outro.mp3",
        )


@pytest.mark.parametrize("path", ["../escape.mp3", "/tmp/audio.mp3", "C:/audio.mp3", "delivery/en/intro.mp3.", "delivery/en/intro.mp3 ", "delivery/en/CON.mp3", "delivery/en/com1.txt", "delivery/en/bad:name.mp3", "delivery/en/bad\x01name.mp3"])
def test_unsafe_artifact_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValueError, match="safe relative path"):
        NarrationFiles(
            hook="delivery/en/hook.mp3",
            intro="delivery/en/intro.mp3",
            story=path,
            outro="delivery/en/outro.mp3",
        )



def test_mixed_path_separators_cannot_bypass_narration_uniqueness() -> None:
    with pytest.raises(ValueError, match="Narration paths must be unique"):
        NarrationFiles(
            hook="delivery/en/hook.mp3",
            intro="delivery\\en\\intro.mp3",
            story="delivery/en/intro.mp3",
            outro="delivery/en/outro.mp3",
        )


def test_public_artifact_paths_use_posix_separators() -> None:
    narration = NarrationFiles(
        hook="delivery/en/hook.mp3",
        intro="delivery\\en\\intro.mp3",
        story="delivery/en/story.mp3",
        outro="delivery/en/outro.mp3",
    )

    assert narration.intro == "delivery/en/intro.mp3"


def test_case_insensitive_paths_cannot_bypass_contract_uniqueness() -> None:
    english = _edition("en")
    conflicting_narration = replace(
        english.delivery.narration,
        intro="publishing/en/THUMBNAIL.png",
    )
    conflicting_edition = replace(
        english,
        delivery=replace(
            english.delivery,
            narration=conflicting_narration,
        ),
    )

    with pytest.raises(ValueError, match="Artifact paths must not be reused"):
        _contract(
            editions=(
                conflicting_edition,
                _edition("es"),
                _edition("pt-BR"),
            )
        )


def test_distinct_artifact_paths_remain_valid() -> None:
    contract = _contract()

    assert contract.editions[0].delivery.narration.intro != (
        contract.editions[0].publishing.thumbnail
    )

def test_mixed_path_separators_cannot_bypass_contract_uniqueness() -> None:
    english = _edition("en")
    conflicting_narration = replace(
        english.delivery.narration,
        intro="publishing\\en\\captions.vtt",
    )
    conflicting_edition = replace(
        english,
        delivery=replace(
            english.delivery,
            narration=conflicting_narration,
        ),
    )

    with pytest.raises(ValueError, match="Artifact paths must not be reused"):
        _contract(
            editions=(
                conflicting_edition,
                _edition("es"),
                _edition("pt-BR"),
            )
        )
@pytest.mark.parametrize("slug", ["Ed_Sullivan", "ed-sullivan", "../ed_sullivan", "ed__sullivan"])
def test_invalid_production_slugs_are_rejected(slug: str) -> None:
    with pytest.raises(ValueError, match="Invalid production slug"):
        replace(_contract(), slug=slug)


def test_hook_is_a_fourth_narration_file() -> None:
    narration = NarrationFiles(
        hook="delivery/en/hook.mp3",
        intro="delivery/en/intro.mp3",
        story="delivery/en/story.mp3",
        outro="delivery/en/outro.mp3",
    )
    assert narration.paths[0] == "delivery/en/hook.mp3"
    assert len(narration.paths) == 4

def test_multilingual_preparation_is_enabled_but_publishing_is_disabled() -> None:
    policy = _contract().youtube_multilingual

    assert policy.preparation_enabled is True
    assert policy.publishing_enabled is False

    with pytest.raises(ValueError, match="requires channel approval"):
        YouTubeMultilingualPolicy(
            preparation_enabled=True,
            publishing_enabled=True,  # type: ignore[arg-type]
        )
