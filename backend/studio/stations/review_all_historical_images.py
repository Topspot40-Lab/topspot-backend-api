from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.studio.historical.downloader import (
    download_candidate,
)
from backend.studio.historical.identity import (
    build_search_queries,
    identity_path,
    load_or_build_identity,
    strengthen_query,
)
from backend.studio.historical.ranking import (
    rank_candidates,
)
from backend.studio.historical.search import (
    search_query_variants,
)
from backend.studio.production import Production


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file: {path}") from exc


def save_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def all_shots(
    storyboard: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (scene, shot)
        for scene in storyboard.get("scenes", [])
        for shot in scene.get("visual_shots", [])
    ]


def run(
    *,
    slug: str,
    limit: int,
    delay_seconds: float,
    force: bool,
    start_shot: int | None,
    end_shot: int | None,
) -> None:
    production = Production(slug)
    production.ensure_work_dirs()

    station_name = "historical_candidate_search"
    production.session.start_station(station_name)

    identity = load_or_build_identity(
        production
    )

    print(
        "Identity:   "
        f"{identity.canonical_name}"
    )

    if identity.identity_terms:
        print(
            "Anchors:    "
            + ", ".join(identity.identity_terms)
        )

    storyboard_path = (
        production.production_root
        / "storyboard.json"
    )
    storyboard = load_json(storyboard_path)

    selected: list[
        tuple[dict[str, Any], dict[str, Any]]
    ] = []

    for scene, shot in all_shots(storyboard):
        shot_number = int(shot["shot_number"])

        if (
            start_shot is not None
            and shot_number < start_shot
        ):
            continue

        if (
            end_shot is not None
            and shot_number > end_shot
        ):
            continue

        selected.append((scene, shot))

    report: dict[str, Any] = {
        "version": 1,
        "production_slug": slug,
        "started_at": datetime.now(UTC).isoformat(),
        "limit_per_provider": limit,
        "results": [],
    }

    searched = 0
    downloaded = 0
    skipped_blank = 0
    skipped_existing = 0
    skipped_approved = 0
    no_candidate = 0
    failures = 0

    print("=" * 80)
    print("TOPSPOT STUDIO — BATCH HISTORICAL IMAGE REVIEW")
    print("=" * 80)
    print(f"Production: {storyboard.get('title')}")
    print(f"Slug:       {slug}")
    print(f"Shots:      {len(selected)}")
    print(f"Limit:      {limit} per provider")
    print()

    for scene, shot in selected:
        shot_number = int(shot["shot_number"])
        query = str(
            shot.get("historical_search") or ""
        ).strip()

        enhanced_query = (
            strengthen_query(
                query,
                identity,
            )
            if query
            else ""
        )

        result: dict[str, Any] = {
            "scene_number": int(scene["scene_number"]),
            "shot_number": shot_number,
            "historical_search": query,
            "enhanced_search": enhanced_query,
        }

        if not query:
            skipped_blank += 1
            result["status"] = "skipped_blank"
            report["results"].append(result)

            print(
                f"Shot {shot_number:03d}: "
                "blank search — AI fallback"
            )
            continue

        if shot.get("historical_asset") and not force:
            skipped_approved += 1
            result["status"] = "skipped_approved"
            report["results"].append(result)

            print(
                f"Shot {shot_number:03d}: "
                "already approved"
            )
            continue

        destination_directory = (
            production.work_root
            / "historical_candidates"
            / f"{shot_number:03d}"
        )
        metadata_path = (
            destination_directory
            / "candidate.json"
        )

        if metadata_path.exists() and not force:
            skipped_existing += 1
            result["status"] = "skipped_existing"
            report["results"].append(result)

            print(
                f"Shot {shot_number:03d}: "
                "candidate already downloaded"
            )
            continue

        print(
            f"Shot {shot_number:03d}: "
            f"searching {enhanced_query!r}"
        )

        searched += 1

        try:
            historical_plan = shot.get(
                "historical_plan",
                {},
            )

            if not isinstance(
                historical_plan,
                dict,
            ):
                historical_plan = {}

            planned_queries = [
                str(value).strip()
                for value in historical_plan.get(
                    "search_queries",
                    [],
                )
                if str(value).strip()
            ]

            fallback_queries = build_search_queries(
                query,
                identity,
            )

            search_queries: list[str] = []
            seen_queries: set[str] = set()

            for search_query in [
                *planned_queries,
                *fallback_queries,
            ]:
                key = search_query.casefold()

                if key not in seen_queries:
                    search_queries.append(
                        search_query
                    )
                    seen_queries.add(key)

            candidates = search_query_variants(
                search_queries,
                limit_per_provider=limit,
            )

            identity_names = [
                identity.canonical_name,
                *identity.aliases,
            ]

            normalized_original = query.casefold()

            require_exact_identity = any(
                name.casefold()
                in normalized_original
                for name in identity_names
                if name.strip()
            )

            ranked = rank_candidates(
                candidates,
                enhanced_query,
                identity=identity,
                require_exact_identity=(
                    require_exact_identity
                ),
                historical_plan=historical_plan,
            )

            result["raw_candidate_count"] = len(
                candidates
            )
            result["usable_candidate_count"] = len(
                ranked
            )

            if not ranked:
                no_candidate += 1
                result["status"] = "no_candidate"
                report["results"].append(result)

                print("  ↷ No usable candidate")
                continue

            winner = ranked[0]

            image_path, saved_metadata_path = (
                download_candidate(
                    winner,
                    destination_directory,
                )
            )

            downloaded += 1

            result.update(
                {
                    "status": "downloaded",
                    "selected_title": winner.title,
                    "selected_provider": winner.provider,
                    "selected_score": winner.score,
                    "identity_confidence": (
                        winner.identity_confidence
                    ),
                    "selected_license": (
                        winner.license_name
                    ),
                    "image_path": str(image_path),
                    "metadata_path": str(
                        saved_metadata_path
                    ),
                }
            )
            report["results"].append(result)

            print(
                f"  ✓ {winner.title}"
            )
            print(
                f"    Score {winner.score}; "
                f"{winner.license_name}"
            )

        except Exception as exc:
            failures += 1

            result.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            report["results"].append(result)

            print(
                f"  ⚠ {type(exc).__name__}: {exc}"
            )

        report_path = (
            production.work_root
            / "historical_candidates"
            / "batch_report.json"
        )

        save_json(report_path, report)

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    report["finished_at"] = (
        datetime.now(UTC).isoformat()
    )
    report["summary"] = {
        "selected_shots": len(selected),
        "searched": searched,
        "downloaded": downloaded,
        "skipped_blank": skipped_blank,
        "skipped_existing": skipped_existing,
        "skipped_approved": skipped_approved,
        "no_candidate": no_candidate,
        "failures": failures,
    }

    report_path = (
        production.work_root
        / "historical_candidates"
        / "batch_report.json"
    )
    save_json(report_path, report)

    print()
    print("=" * 80)
    print("BATCH SUMMARY")
    print("=" * 80)
    print(f"Searched:              {searched}")
    print(f"Candidates downloaded: {downloaded}")
    print(f"Blank / AI fallback:   {skipped_blank}")
    print(f"Already downloaded:    {skipped_existing}")
    print(f"Already approved:      {skipped_approved}")
    print(f"No candidate:          {no_candidate}")
    print(f"Failures:              {failures}")
    production.session.metric(
        "selected_shots",
        len(selected),
        station=station_name,
    )
    production.session.metric(
        "searched",
        searched,
        station=station_name,
    )
    production.session.metric(
        "downloaded",
        downloaded,
        station=station_name,
    )
    production.session.metric(
        "skipped_blank",
        skipped_blank,
        station=station_name,
    )
    production.session.metric(
        "skipped_existing",
        skipped_existing,
        station=station_name,
    )
    production.session.metric(
        "skipped_approved",
        skipped_approved,
        station=station_name,
    )
    production.session.metric(
        "no_candidate",
        no_candidate,
        station=station_name,
    )
    production.session.metric(
        "failures",
        failures,
        station=station_name,
    )

    production.session.artifact(
        "historical_identity",
        identity_path(production),
        station=station_name,
    )
    production.session.artifact(
        "batch_report",
        report_path,
        station=station_name,
    )
    production.session.artifact(
        "candidate_directory",
        production.work_root / "historical_candidates",
        station=station_name,
    )

    if failures:
        production.session.warning(
            (
                f"Historical candidate search completed "
                f"with {failures} failed shot search(es)."
            ),
            station=station_name,
        )

    production.session.finish_station(
        station_name,
        success=True,
    )

    print()
    print(f"Report: {report_path}")
    print()
    print("✅ Batch historical review complete")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Search all storyboard historical_search phrases "
            "and download one review candidate per shot."
        )
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Pause between searches.",
    )
    parser.add_argument(
        "--start-shot",
        type=int,
    )
    parser.add_argument(
        "--end-shot",
        type=int,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Repeat searches and replace candidates.",
    )
    args = parser.parse_args()

    run(
        slug=args.slug,
        limit=args.limit,
        delay_seconds=args.delay,
        force=args.force,
        start_shot=args.start_shot,
        end_shot=args.end_shot,
    )


if __name__ == "__main__":
    main()
