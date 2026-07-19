from __future__ import annotations

import argparse
import shutil
from pathlib import Path


HISTORICAL_ROOT = Path("backend/studio/assets/historical")
PRODUCTIONS_ROOT = Path("backend/studio/productions")


MIGRATIONS = {
    # Docuseries
    "casey_kasem": Path("docuseries/casey_kasem"),
    "dick_clark": Path("docuseries/dick_clark"),
    "ed_sullivan": Path("docuseries/ed_sullivan"),

    # Premium artists
    "johnny_cash": Path("artists/j/johnny_cash"),
    "juan_gabriel": Path("artists/j/juan_gabriel"),
    "luis_miguel": Path("artists/l/luis_miguel"),
    "merle_haggard": Path("artists/m/merle_haggard"),
    "pedro_infante": Path("artists/p/pedro_infante"),
    "vicente_fernandez": Path(
        "artists/v/vicente_fernandez"
    ),
}


def update_json_paths(*, dry_run: bool) -> tuple[int, int]:
    changed_files = 0
    replacements = 0

    for json_path in PRODUCTIONS_ROOT.rglob("*.json"):
        original = json_path.read_text(encoding="utf-8")
        updated = original
        file_replacements = 0

        for slug, destination in MIGRATIONS.items():
            old_prefix = f"assets/historical/{slug}/"
            new_prefix = (
                "assets/historical/"
                f"{destination.as_posix()}/"
            )

            count = updated.count(old_prefix)

            if count:
                updated = updated.replace(
                    old_prefix,
                    new_prefix,
                )
                file_replacements += count

        if updated == original:
            continue

        changed_files += 1
        replacements += file_replacements

        print(
            f"{'WOULD UPDATE' if dry_run else 'UPDATED'} "
            f"{json_path} "
            f"({file_replacements} path replacement(s))"
        )

        if not dry_run:
            temporary_path = json_path.with_suffix(
                json_path.suffix + ".tmp"
            )
            temporary_path.write_text(
                updated,
                encoding="utf-8",
            )
            temporary_path.replace(json_path)

    return changed_files, replacements


def migrate_directories(*, dry_run: bool) -> tuple[int, int]:
    moved = 0
    skipped = 0

    for slug, relative_destination in MIGRATIONS.items():
        source = HISTORICAL_ROOT / slug
        destination = (
            HISTORICAL_ROOT / relative_destination
        )

        if destination.exists():
            if source.exists():
                raise FileExistsError(
                    "Both old and new historical directories exist:\n"
                    f"Old: {source}\n"
                    f"New: {destination}"
                )

            print(f"ALREADY MOVED {destination}")
            skipped += 1
            continue

        if not source.exists():
            print(f"MISSING       {source}")
            skipped += 1
            continue

        print(
            f"{'WOULD MOVE' if dry_run else 'MOVED'} "
            f"{source} -> {destination}"
        )
        moved += 1

        if not dry_run:
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            shutil.move(
                str(source),
                str(destination),
            )

    return moved, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate TopSpot Studio historical assets into "
            "separate docuseries and alphabetized artist folders."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without moving or editing anything.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print()
    print("TOPSPOT STUDIO — HISTORICAL LAYOUT MIGRATION")
    print("=" * 65)
    print(f"Dry run: {'yes' if args.dry_run else 'no'}")
    print()

    moved, skipped = migrate_directories(
        dry_run=args.dry_run
    )
    changed_files, replacements = update_json_paths(
        dry_run=args.dry_run
    )

    print()
    print("=" * 65)
    print(f"Directories to move:  {moved}")
    print(f"Directories skipped:  {skipped}")
    print(f"JSON files to update: {changed_files}")
    print(f"Path replacements:    {replacements}")

    if args.dry_run:
        print("Dry run complete. Nothing was changed.")
    else:
        print("Migration complete.")


if __name__ == "__main__":
    main()