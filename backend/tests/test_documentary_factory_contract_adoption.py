from __future__ import annotations

from pathlib import Path

from backend.studio.factory import ProductionSession


def test_session_explicitly_adopts_canonical_contract_without_rewrites(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        '{"version": 1, "languages": [{"language_code": "en"}]}\n',
        encoding="utf-8",
    )
    session = ProductionSession(
        production_slug="ed_sullivan",
        work_root=tmp_path / "work",
    )
    manifest_before = manifest_path.read_bytes()
    session_before = session.session_path.read_bytes()

    contract = session.adopt_documentary_production_contract()

    assert session.adopt_documentary_production_contract() is contract
    assert manifest_path.read_bytes() == manifest_before
    assert session.session_path.read_bytes() == session_before
    assert "documentary_production_contract" not in session.payload


def test_adopted_contract_has_canonical_multilingual_deliveries(
    tmp_path: Path,
) -> None:
    session = ProductionSession(
        production_slug="ed_sullivan",
        work_root=tmp_path,
    )

    contract = session.adopt_documentary_production_contract()

    assert tuple(edition.language_code for edition in contract.editions) == (
        "en",
        "es",
        "pt-BR",
    )
    for edition in contract.editions:
        assert edition.delivery.paths == (
            f"delivery/{edition.language_code}/documentary.mp4",
            f"delivery/{edition.language_code}/narration/hook.mp3",
            f"delivery/{edition.language_code}/narration/intro.mp3",
            f"delivery/{edition.language_code}/narration/story.mp3",
            f"delivery/{edition.language_code}/narration/outro.mp3",
        )
        assert edition.delivery.narration.hook == (
            f"delivery/{edition.language_code}/narration/hook.mp3"
        )


def test_adopted_contract_reuses_one_shared_visual_program(
    tmp_path: Path,
) -> None:
    session = ProductionSession(
        production_slug="ed_sullivan",
        work_root=tmp_path,
    )

    contract = session.adopt_documentary_production_contract()

    assert contract.shared_paths == (
        "shared/visual_plan.json",
        "shared/visual_research.json",
        "shared/visual_master.mp4",
        "shared/hook_visual.png",
        "shared/historical_photo_provenance.json",
        "shared/visual_qc.json",
    )
    assert all(
        not hasattr(edition, "shared_assets")
        for edition in contract.editions
    )
    assert contract.youtube_multilingual.preparation_enabled is True
    assert contract.youtube_multilingual.publishing_enabled is False
