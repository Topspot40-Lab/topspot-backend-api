from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.studio.production import Production


def save_manifest(
    production: Production,
    manifest: dict[str, Any],
) -> None:
    """
    Save the Production Record atomically so a failed write cannot leave
    manifest.json partially written.
    """
    temporary_path = production.manifest_path.with_suffix(".json.tmp")

    temporary_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(production.manifest_path)


def export_story_files(
    production: Production,
    *,
    refresh: bool,
) -> list[Path]:
    """
    Export database story text as permanent source snapshots.

    The database remains the source of truth. Existing story files are
    preserved unless --refresh is explicitly supplied.
    """
    documentary = production.documentary
    story_root = production.production_root / "story"
    story_root.mkdir(parents=True, exist_ok=True)

    exported: list[Path] = []

    for language in documentary.languages:
        destination = story_root / f"{language.language_code}.md"

        content = (
            f"# {documentary.title}\n\n"
            f"## Language\n\n"
            f"{language.language_code}\n\n"
            f"## Source\n\n"
            f"{documentary.source_type} #{documentary.source_id}\n\n"
            f"## Documentary Story\n\n"
            f"{language.story_text.strip()}\n"
        )

        if destination.exists() and not refresh:
            existing = destination.read_text(encoding="utf-8")

            if existing == content:
                print(f"✓ Story already current: {destination}")
            else:
                print(
                    f"⚠ Preserving existing story snapshot: {destination}\n"
                    "  Use --refresh to replace it from the database."
                )

            exported.append(destination)
            continue

        destination.write_text(content, encoding="utf-8")
        print(f"✓ Exported story: {destination}")
        exported.append(destination)

    return exported


def download_storage_object(
    *,
    bucket: str,
    primary_key: str,
    fallback_key: str | None,
) -> tuple[bytes, str]:
    """
    Download the preferred YouTube narration.

    If it is not present, fall back to the original narration object.
    """
    # Import only when storage is actually needed. This allows
    # --help and module imports to work without Supabase credentials.
    from backend.services.supabase_client import supabase
    keys = [primary_key]

    if fallback_key and fallback_key != primary_key:
        keys.append(fallback_key)

    last_error: Exception | None = None

    for key in keys:
        try:
            print(f"  Trying: {bucket}/{key}")
            data = supabase.storage.from_(bucket).download(key)

            if data:
                return data, key
        except Exception as exc:
            last_error = exc
            print(f"  Not available: {bucket}/{key}")

    if last_error is not None:
        raise RuntimeError(
            f"Unable to download narration from bucket {bucket!r}. "
            f"Tried: {keys}"
        ) from last_error

    raise RuntimeError(
        f"Downloaded narration was empty. Bucket={bucket!r}, keys={keys}"
    )


def prepare_audio(
    production: Production,
    *,
    refresh: bool,
) -> list[Path]:
    documentary = production.documentary
    downloaded: list[Path] = []

    for language in documentary.available_audio():
        destination = production.work_root / "audio" / (
            language.local_audio_name
        )

        if (
            destination.exists()
            and destination.stat().st_size > 0
            and not refresh
        ):
            print(
                f"✓ Using existing narration: {destination} "
                f"({destination.stat().st_size:,} bytes)"
            )
            downloaded.append(destination)
            continue

        if not language.tts_bucket:
            raise RuntimeError(
                f"Missing narration bucket for "
                f"{language.language_code}"
            )

        preferred_key = language.youtube_key or language.tts_key

        if not preferred_key:
            raise RuntimeError(
                f"Missing narration key for "
                f"{language.language_code}"
            )

        print(
            f"Downloading {language.language_code} narration..."
        )

        data, downloaded_key = download_storage_object(
            bucket=language.tts_bucket,
            primary_key=preferred_key,
            fallback_key=language.tts_key,
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

        print(
            f"✓ Downloaded narration: {destination} "
            f"({destination.stat().st_size:,} bytes)\n"
            f"  Source: {language.tts_bucket}/{downloaded_key}"
        )

        downloaded.append(destination)

    expected_languages = len(documentary.languages)

    if len(downloaded) != expected_languages:
        raise RuntimeError(
            f"Prepared {len(downloaded)} narration files, "
            f"but the documentary has {expected_languages} languages."
        )

    return downloaded


def update_production_record(
    production: Production,
    *,
    story_files: list[Path],
    audio_files: list[Path],
) -> None:
    manifest = dict(production.manifest)
    status = dict(manifest.get("status", {}))
    artifacts = dict(manifest.get("artifacts", {}))

    status.update(
        {
            "current_station": "source_assets_ready",
            "story_ready": True,
            "audio_ready": True,
        }
    )

    artifacts["stories"] = [
        str(path.relative_to(production.production_root)).replace("\\", "/")
        for path in story_files
    ]

    artifacts["audio"] = [
        str(path.relative_to(production.work_root)).replace("\\", "/")
        for path in audio_files
    ]

    manifest["status"] = status
    manifest["artifacts"] = artifacts
    manifest["updated_at"] = datetime.now(UTC).isoformat()

    save_manifest(production, manifest)


def prepare_source_assets(
    *,
    slug: str,
    refresh: bool,
) -> None:
    production = Production(slug)
    production.ensure_work_dirs()

    print()
    print("Factory Station 2 — Prepare Source Assets")
    print(f"Production: {production.documentary.title}")
    print(f"Slug:       {production.slug}")
    print()

    story_files = export_story_files(
        production,
        refresh=refresh,
    )

    print()

    audio_files = prepare_audio(
        production,
        refresh=refresh,
    )

    update_production_record(
        production,
        story_files=story_files,
        audio_files=audio_files,
    )

    print()
    print("✅ Factory Station 2 complete")
    print(f"   Stories:  {len(story_files)}")
    print(f"   Narration: {len(audio_files)}")
    print("   Current station: source_assets_ready")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare permanent story snapshots and local narration "
            "for an existing TopSpot Studio production."
        )
    )

    parser.add_argument(
        "--slug",
        required=True,
        help="Existing production slug, such as casey_kasem.",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Replace story snapshots and re-download narration "
            "from their source systems."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        prepare_source_assets(
            slug=args.slug,
            refresh=args.refresh,
        )
    except (
        FileNotFoundError,
        KeyError,
        LookupError,
        RuntimeError,
        ValueError,
    ) as exc:
        raise SystemExit(f"❌ {exc}") from exc


if __name__ == "__main__":
    main()
