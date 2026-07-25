from __future__ import annotations

import argparse
import hashlib
import mimetypes
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.studio_models import (
    StudioProductionAsset,
)


WORK_ROOT = Path("backend/studio/work")


@dataclass(frozen=True)
class Production:
    production_type: str
    source_id: int
    slug: str
    title: str


PRODUCTIONS = (
    Production(
        "documentary",
        36,
        "casey_kasem",
        "Casey Kasem: The Voice of America's Top 40",
    ),
    Production(
        "documentary",
        34,
        "dick_clark",
        "Dick Clark: America's Oldest Teenager",
    ),
    Production(
        "documentary",
        33,
        "ed_sullivan",
        (
            "Ed Sullivan: The Man Who Introduced "
            "America to Rock & Roll"
        ),
    ),
    Production(
        "artist",
        141,
        "johnny_cash",
        "Johnny Cash",
    ),
    Production(
        "artist",
        1952,
        "juan_gabriel",
        "Juan Gabriel",
    ),
    Production(
        "artist",
        777,
        "luis_miguel",
        "Luis Miguel",
    ),
)


@dataclass(frozen=True)
class AssetSpec:
    asset_type: str
    language_code: str
    path: Path
    status: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Catalog the six completed YouTube "
            "production packages."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write records to the database.",
    )
    return parser.parse_args()


def asset_specs(
    production: Production,
) -> list[AssetSpec]:
    slug = production.slug
    output = WORK_ROOT / slug / "output"
    youtube = output / "youtube"

    specs = [
        AssetSpec(
            asset_type="localized_video",
            language_code=language,
            path=output / f"{slug}_{language}.mp4",
            status="published",
        )
        for language in ("en", "es", "pt-BR")
    ]

    specs.append(
        AssetSpec(
            asset_type=(
                "master_video_no_narration"
            ),
            language_code="und",
            path=youtube / f"{slug}.mp4",
            status="multilingual_ready",
        )
    )

    specs.extend(
        AssetSpec(
            asset_type="youtube_audio_track",
            language_code=language,
            path=youtube / f"{slug}_{language}.mp3",
            status="multilingual_ready",
        )
        for language in ("en", "es", "pt-BR")
    )

    return specs


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as source:
        while chunk := source.read(
            1024 * 1024
        ):
            digest.update(chunk)

    return digest.hexdigest()


def duration_seconds(path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:"
            "nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    value = result.stdout.strip()

    if not value:
        return None

    return round(float(value), 3)


def content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(
        path.name
    )[0]

    if guessed:
        return guessed

    if path.suffix.lower() == ".mp3":
        return "audio/mpeg"

    if path.suffix.lower() == ".mp4":
        return "video/mp4"

    return "application/octet-stream"


def find_existing(
    db: Session,
    production: Production,
    spec: AssetSpec,
) -> StudioProductionAsset | None:
    statement = select(
        StudioProductionAsset
    ).where(
        StudioProductionAsset.production_type
        == production.production_type,
        StudioProductionAsset.source_id
        == production.source_id,
        StudioProductionAsset.version_number
        == 1,
        StudioProductionAsset.asset_type
        == spec.asset_type,
        StudioProductionAsset.language_code
        == spec.language_code,
    )

    return db.exec(statement).first()


def main() -> None:
    args = parse_args()
    mode = "APPLY" if args.apply else "DRY RUN"

    print(
        "TOPSPOT — COMPLETED YOUTUBE "
        "ASSET CATALOG"
    )
    print(f"MODE: {mode}")
    print("=" * 78)

    expected = 0
    inserted = 0
    existing_count = 0
    missing = 0
    errors = 0
    total_bytes = 0

    with Session(engine) as db:
        for production in PRODUCTIONS:
            print()
            print(
                f"{production.slug} "
                f"[{production.production_type}]"
            )
            print("-" * 78)

            for spec in asset_specs(production):
                expected += 1
                path = spec.path

                if not path.exists():
                    missing += 1
                    print(
                        f"MISSING  "
                        f"{spec.asset_type:27} "
                        f"{spec.language_code:5} "
                        f"{path}"
                    )
                    continue

                try:
                    size = path.stat().st_size
                    checksum = sha256_file(path)
                    duration = duration_seconds(path)
                    total_bytes += size

                    existing = find_existing(
                        db,
                        production,
                        spec,
                    )

                    if existing is not None:
                        existing_count += 1
                        action = "EXISTS"
                    else:
                        action = "INSERT"

                    print(
                        f"{action:7} "
                        f"{spec.asset_type:27} "
                        f"{spec.language_code:5} "
                        f"{size / 1024 / 1024:9.2f} MB "
                        f"{duration:9.3f}s "
                        f"{checksum[:12]} "
                        f"{path.name}"
                    )

                    if (
                        args.apply
                        and existing is None
                    ):
                        record = (
                            StudioProductionAsset(
                                production_type=(
                                    production
                                    .production_type
                                ),
                                source_id=(
                                    production.source_id
                                ),
                                slug=production.slug,
                                title=production.title,
                                version_number=1,
                                asset_type=(
                                    spec.asset_type
                                ),
                                language_code=(
                                    spec.language_code
                                ),
                                filename=path.name,
                                local_path=(
                                    path.as_posix()
                                ),
                                storage_provider=(
                                    "local_archive"
                                ),
                                storage_bucket=None,
                                storage_key=None,
                                content_type=(
                                    content_type(path)
                                ),
                                file_size_bytes=size,
                                duration_seconds=(
                                    duration
                                ),
                                sha256=checksum,
                                status=spec.status,
                                is_current=True,
                                created_at=(
                                    datetime.now(UTC)
                                ),
                                updated_at=(
                                    datetime.now(UTC)
                                ),
                            )
                        )
                        db.add(record)
                        inserted += 1

                except Exception as exc:
                    errors += 1
                    print(
                        f"ERROR    {path}: {exc}"
                    )

        if args.apply and errors == 0:
            db.commit()

    print()
    print("=" * 78)
    print(f"Expected:       {expected}")
    print(f"Inserted:       {inserted}")
    print(f"Already exists: {existing_count}")
    print(f"Missing:        {missing}")
    print(f"Errors:         {errors}")
    print(
        f"Total size:     "
        f"{total_bytes / 1024 / 1024 / 1024:.2f} GB"
    )

    if not args.apply:
        print()
        print(
            "Dry run only. Add --apply "
            "to insert records."
        )


if __name__ == "__main__":
    main()
