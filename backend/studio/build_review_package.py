from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.studio.production import Production
from backend.studio.studio_config import PRODUCTIONS_DIR


_ACTIVE_PRODUCTION: Production | None = None


def run_module(
    module: str,
    *arguments: str,
) -> None:
    """
    Run one factory station as a Python module.

    The subprocess inherits the current environment, including credentials
    loaded through python-dotenv.
    """
    command = [
        sys.executable,
        "-m",
        module,
        *arguments,
    ]

    print()
    print("=" * 80)
    print(f"Running: {' '.join(command)}")
    print("=" * 80)
    print()

    subprocess.run(
        command,
        check=True,
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def production_exists(slug: str) -> bool:
    return (
        PRODUCTIONS_DIR
        / slug
        / "manifest.json"
    ).exists()


def resolve_documentary(
    *,
    source_type: str,
    source_id: int,
):
    from backend.studio.documentary import Documentary

    return Documentary.load(
        source_type=source_type,
        source_id=source_id,
    )


def create_production_if_needed(
    *,
    source_type: str,
    source_id: int,
    slug: str,
) -> None:
    if production_exists(slug):
        print(f"✓ Production already exists: {slug}")
        return

    arguments = [
        "--source-type",
        source_type,
        "--source-id",
        str(source_id),
    ]

    run_module(
        "backend.studio.stations.create_production",
        *arguments,
    )


def prepare_source_assets_if_needed(
    production: Production,
) -> None:
    status = production.manifest.get("status", {})

    if (
        status.get("audio_ready")
        and status.get("story_ready")
    ):
        print("✓ Source assets already ready")
        return

    run_module(
        "backend.studio.stations.prepare_source_assets",
        "--slug",
        production.slug,
    )


def build_storyboard_if_needed(
    production: Production,
) -> None:
    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )

    if storyboard_path.exists():
        storyboard = load_json(storyboard_path)

        if storyboard.get("scenes"):
            print(
                "✓ Storyboard already ready: "
                f"{len(storyboard['scenes'])} narration scenes"
            )
            return

    run_module(
        "backend.studio.stations.build_storyboard",
        "--slug",
        production.slug,
    )


def generate_visual_plan_if_needed(
    production: Production,
) -> None:
    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    shots = [
        shot
        for scene in storyboard.get("scenes", [])
        for shot in scene.get("visual_shots", [])
    ]

    all_ready = bool(shots) and all(
        shot.get("status") in {
            "prompt_ready",
            "image_ready",
            "approved",
        }
        and shot.get("prompt")
        for shot in shots
    )

    if all_ready:
        print(f"✓ Visual plan already ready: {len(shots)} shots")
        return

    run_module(
        "backend.studio.stations.generate_visual_plan",
        "--slug",
        production.slug,
    )


def historical_candidate_search_if_needed(
    production: Production,
) -> None:
    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    shots = [
        shot
        for scene in storyboard.get("scenes", [])
        for shot in scene.get("visual_shots", [])
    ]

    searchable_shots = [
        shot
        for shot in shots
        if str(
            shot.get("historical_search") or ""
        ).strip()
    ]

    if not searchable_shots:
        print(
            "✓ Historical candidate search skipped: "
            "no searchable historical shots"
        )
        return

    candidates_root = (
        production.work_root
        / "historical_candidates"
    )

    existing_candidates = sum(
        1
        for shot in searchable_shots
        if (
            candidates_root
            / f"{int(shot['shot_number']):03d}"
            / "candidate.json"
        ).exists()
    )

    approved_count = sum(
        1
        for shot in searchable_shots
        if shot.get("historical_asset")
    )

    covered_count = sum(
        1
        for shot in searchable_shots
        if (
            shot.get("historical_asset")
            or (
                candidates_root
                / f"{int(shot['shot_number']):03d}"
                / "candidate.json"
            ).exists()
        )
    )

    remaining = (
        len(searchable_shots)
        - covered_count
    )

    if remaining <= 0:
        print(
            "✓ Historical candidates already ready: "
            f"{existing_candidates} downloaded, "
            f"{approved_count} approved"
        )
        return

    print(
        "Historical candidate search: "
        f"{remaining} shot(s) still need candidates"
    )

    run_module(
        "backend.studio.stations.review_all_historical_images",
        "--slug",
        production.slug,
    )


def generate_images_if_needed(
    production: Production,
) -> None:
    run_module(
        "backend.studio.stations.generate_images",
        "--slug",
        production.slug,
        "--all",
    )


def build_cards(
    production: Production,
) -> None:
    run_module(
        "backend.studio.stations.build_opening_cards",
        "--slug",
        production.slug,
    )


def download_if_missing(
    *,
    bucket: str,
    key: str,
    destination: Path,
) -> None:
    # Import only when an actual storage download is required.
    from backend.services.supabase_client import supabase

    if destination.exists() and destination.stat().st_size > 0:
        print(
            f"✓ Using existing audio: {destination} "
            f"({destination.stat().st_size:,} bytes)"
        )
        return

    print(f"Downloading: {bucket}/{key}")

    data = supabase.storage.from_(bucket).download(key)

    if not data:
        raise RuntimeError(
            f"Downloaded audio was empty: {bucket}/{key}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    print(
        f"✓ Downloaded: {destination} "
        f"({destination.stat().st_size:,} bytes)"
    )


def prepare_render_audio(
    production: Production,
    language_code: str,
) -> None:
    """
    Prepare the local filenames expected by build_story_video.py.
    """
    language = production.documentary.language(language_code)

    if not language.tts_bucket:
        raise RuntimeError(
            f"Missing audio bucket for language {language_code}"
        )

    safe_language = language_code.replace("/", "-").replace("\\", "-")
    audio_dir = production.work_root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    intro = audio_dir / f"intro_{safe_language}.mp3"
    outro = audio_dir / f"outro_{safe_language}.mp3"

    download_if_missing(
        bucket=language.tts_bucket,
        key="youtube/intro.mp3",
        destination=intro,
    )

    download_if_missing(
        bucket=language.tts_bucket,
        key="youtube/outro.mp3",
        destination=outro,
    )

    source_story = production.audio(language_code)

    if not source_story.exists():
        raise FileNotFoundError(
            f"Prepared source narration not found: {source_story}"
        )

    story_target = (
        audio_dir
        / f"story_{safe_language}_{language.locale_id}.mp3"
    )

    if (
        story_target.exists()
        and story_target.stat().st_size > 0
    ):
        print(
            f"✓ Using existing story audio: {story_target} "
            f"({story_target.stat().st_size:,} bytes)"
        )
    else:
        shutil.copy2(
            source_story,
            story_target,
        )

        print(
            f"✓ Prepared story audio: {story_target} "
            f"({story_target.stat().st_size:,} bytes)"
        )


def render_opening(production: Production) -> None:
    run_module(
        "backend.studio.render.build_opening",
        "--slug",
        production.slug,
    )


def render_image_sequence(production: Production) -> None:
    run_module(
        "backend.studio.render.build_image_sequence",
        "--slug",
        production.slug,
    )


def render_story_video(
    production: Production,
    language_code: str,
) -> Path:
    run_module(
        "backend.studio.render.build_story_video",
        "--slug",
        production.slug,
        "--language",
        language_code,
    )

    safe_language = language_code.replace("/", "-").replace("\\", "-")

    output = (
        production.work_root
        / "output"
        / f"{production.slug}_{safe_language}.mp4"
    )

    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(
            f"Review video was not created correctly: {output}"
        )

    return output


def create_review_package(
    production: Production,
    *,
    video_path: Path,
    language_code: str,
) -> Path:
    """
    Place the review copy and minimal review instructions in one predictable
    folder. YouTube metadata automation will be added as a later station.
    """
    package_dir = (
        production.work_root
        / "review_package"
    )
    package_dir.mkdir(parents=True, exist_ok=True)

    safe_language = language_code.replace("/", "-").replace("\\", "-")

    review_video = (
        package_dir
        / f"{production.slug}_{safe_language}_review.mp4"
    )

    shutil.copy2(
        video_path,
        review_video,
    )

    title_path = package_dir / "title.txt"
    title_path.write_text(
        (
            production.documentary.title
            + (
                f" — {production.documentary.subtitle}"
                if production.documentary.subtitle
                else ""
            )
            + "\n"
        ),
        encoding="utf-8",
    )

    notes_path = package_dir / "review_notes.md"
    notes_path.write_text(
        (
            f"# {production.documentary.title} — Review Notes\n\n"
            "## Reviewer\n\n"
            "Gary / Paty\n\n"
            "## Decision\n\n"
            "- [ ] Approved\n"
            "- [ ] Needs changes\n\n"
            "## Notes\n\n"
        ),
        encoding="utf-8",
    )

    return review_video


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the TopSpot Studio factory and produce a complete "
            "documentary MP4 ready for human review."
        )
    )

    source_group = parser.add_mutually_exclusive_group(
        required=True
    )

    source_group.add_argument(
        "--docuseries-id",
        type=int,
        help="Existing music_docuseries database ID.",
    )

    source_group.add_argument(
        "--artist-id",
        type=int,
        help="Existing premium artist database ID.",
    )

    parser.add_argument(
        "--language",
        default="en",
        help="Review-video language. Default: en.",
    )

    return parser.parse_args()


def main() -> None:
    global _ACTIVE_PRODUCTION

    args = parse_args()

    if args.docuseries_id is not None:
        source_type = "music_docuseries"
        source_id = args.docuseries_id
    else:
        source_type = "artist_story"
        source_id = args.artist_id

    documentary = resolve_documentary(
        source_type=source_type,
        source_id=source_id,
    )
    slug = documentary.slug

    print()
    print("#" * 80)
    print("TopSpot Studio — Build Documentary Package")
    print(f"Source type: {source_type}")
    print(f"Source ID:   {source_id}")
    print(f"Title:       {documentary.title}")
    print(f"Slug:        {slug}")
    print(f"Language:    {args.language}")
    print("#" * 80)

    create_production_if_needed(
        source_type=source_type,
        source_id=source_id,
        slug=slug,
    )

    production = Production(slug)
    _ACTIVE_PRODUCTION = production
    production.session.start_production()

    production.session.metric(
        "source_type",
        source_type,
    )
    production.session.metric(
        "source_id",
        source_id,
    )
    production.session.metric(
        "requested_language",
        args.language,
    )

    prepare_source_assets_if_needed(production)

    # Reload after any station that may update manifest.json.
    production = Production(slug)

    build_storyboard_if_needed(production)

    production = Production(slug)

    generate_visual_plan_if_needed(production)

    production = Production(slug)

    historical_candidate_search_if_needed(
        production
    )

    production = Production(slug)

    generate_images_if_needed(production)

    production = Production(slug)

    build_cards(production)

    production = Production(slug)

    language_codes = production.documentary.language_codes()

    print()
    print("=" * 80)
    print("Preparing multilingual render audio")
    print("=" * 80)
    print(
        "Languages: "
        + ", ".join(language_codes)
    )

    for language_code in language_codes:
        print()
        print(f"Preparing {language_code} audio...")
        prepare_render_audio(
            production,
            language_code,
        )

    # The opening cards and image sequence are shared by every language.
    render_opening(production)
    render_image_sequence(production)

    final_videos: dict[str, Path] = {}
    review_videos: dict[str, Path] = {}

    for language_code in language_codes:
        print()
        print("=" * 80)
        print(
            f"Rendering complete {language_code} documentary"
        )
        print("=" * 80)

        final_video = render_story_video(
            production,
            language_code,
        )

        review_video = create_review_package(
            production,
            video_path=final_video,
            language_code=language_code,
        )

        final_videos[language_code] = final_video
        review_videos[language_code] = review_video

    run_module(
        "backend.studio.audio.build_language_masters",
        "--slug",
        production.slug,
    )

    run_module(
        "backend.studio.render.build_youtube_master",
        "--slug",
        production.slug,
    )

    youtube_dir = (
        production.work_root
        / "output"
        / "youtube"
    )

    required_outputs = [
        *final_videos.values(),
        youtube_dir / f"{production.slug}.mp4",
        *[
            youtube_dir
            / f"{production.slug}_{language_code}.mp3"
            for language_code in language_codes
        ],
    ]

    missing_outputs = [
        output
        for output in required_outputs
        if not output.exists() or output.stat().st_size == 0
    ]

    if missing_outputs:
        formatted = "\n".join(
            f"  - {output}"
            for output in missing_outputs
        )
        raise RuntimeError(
            "Documentary build finished with missing outputs:\n"
            f"{formatted}"
        )

    print()
    print("#" * 80)
    print("✅ MULTILINGUAL DOCUMENTARY PACKAGE COMPLETE")
    print("#" * 80)
    print()

    print("Complete language videos:")

    for language_code in language_codes:
        print(
            f"  {language_code}: "
            f"{final_videos[language_code]}"
        )

    print()
    print("YouTube / audio package:")
    print(f"  {youtube_dir / f'{production.slug}.mp4'}")

    for language_code in language_codes:
        print(
            "  "
            + str(
                youtube_dir
                / f"{production.slug}_{language_code}.mp3"
            )
        )

    print()
    print("Review copies:")

    for language_code in language_codes:
        print(
            f"  {language_code}: "
            f"{review_videos[language_code]}"
        )

    production.session.metric(
        "language_count",
        len(language_codes),
    )
    production.session.metric(
        "languages",
        language_codes,
    )
    production.session.metric(
        "final_video_count",
        len(final_videos),
    )
    production.session.metric(
        "review_video_count",
        len(review_videos),
    )

    for language_code, final_video in final_videos.items():
        production.session.artifact(
            f"final_video_{language_code}",
            final_video,
        )

    for language_code, review_video in review_videos.items():
        production.session.artifact(
            f"review_video_{language_code}",
            review_video,
        )

    youtube_video = (
        youtube_dir / f"{production.slug}.mp4"
    )

    production.session.artifact(
        "youtube_video",
        youtube_video,
    )

    for language_code in language_codes:
        production.session.artifact(
            f"youtube_audio_{language_code}",
            (
                youtube_dir
                / f"{production.slug}_{language_code}.mp3"
            ),
        )

    production.session.finish_production(
        success=True,
    )

    print()
    print("Ready for Gary or Paty to review.")


def record_factory_failure(
    exc: BaseException,
) -> None:
    production = _ACTIVE_PRODUCTION

    if production is None:
        return

    try:
        production.session.error(
            f"{type(exc).__name__}: {exc}"
        )
        production.session.finish_production(
            success=False,
        )
    except Exception as session_exc:
        print(
            "⚠ Could not update ProductionSession after "
            f"factory failure: {session_exc}"
        )


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        record_factory_failure(exc)
        raise
