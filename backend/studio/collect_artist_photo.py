from __future__ import annotations

import argparse
import re
import sys
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlmodel import Session

from backend.database import engine
from backend.models.dbmodels import Artist
from backend.studio.documentary import slugify
from backend.studio.historical.downloader import (
    download_candidate,
    save_json_atomic,
)
from backend.studio.historical.providers.wikimedia import (
    WikimediaCommonsProvider,
)
from backend.studio.historical.ranking import (
    candidate_is_usable,
    candidate_searchable_text,
    normalized_phrase,
)
from backend.studio.historical_assets import (
    historical_directories,
)

from backend.studio.historical_storage import (
    upload_artist_photo,
)


def next_photo_number(
    *directories: Path,
) -> int:
    numbers: list[int] = []

    for directory in directories:
        for path in directory.iterdir():
            match = re.match(
                r"^(\d{3})[-_]",
                path.name,
            )

            if match:
                numbers.append(
                    int(match.group(1))
                )

    return max(numbers, default=0) + 1


def safe_photo_title(title: str) -> str:
    cleaned = title.removeprefix("File:")
    cleaned = Path(cleaned).stem
    cleaned = slugify(cleaned).replace("_", "-")

    if not cleaned:
        return "historical-photo"

    return cleaned[:72].rstrip("-")


def load_artist(artist_id: int) -> Artist:
    with Session(engine) as db:
        artist = db.get(Artist, artist_id)

        if artist is None:
            raise LookupError(
                f"Artist ID not found: {artist_id}"
            )

        return artist


def find_duplicate_metadata(
    metadata_directory: Path,
    *,
    page_url: str,
    original_url: str,
) -> Path | None:
    candidate_urls = {
        url
        for url in (page_url, original_url)
        if url
    }

    for metadata_path in metadata_directory.glob("*.json"):
        try:
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue

        existing_urls = {
            str(metadata.get("page_url") or ""),
            str(metadata.get("original_url") or ""),
        }

        if candidate_urls & existing_urls:
            return metadata_path

    return None

def candidate_matches_artist(
    candidate,
    artist_name: str,
) -> bool:
    artist_phrase = normalized_phrase(
        artist_name
    )
    title_phrase = normalized_phrase(
        candidate.title
    )

    return bool(
        artist_phrase
        and artist_phrase in title_phrase
    )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Search Wikimedia Commons and approve one photograph "
            "for a premium artist's historical library."
        )
    )
    parser.add_argument(
        "--artist-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--query",
        required=True,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--select",
        type=int,
        help=(
            "Candidate number to approve. Without this option, "
            "the command only displays candidates."
        ),
    )
    parser.add_argument(
        "--discovered-via",
        default="wikimedia_commons",
        help="Where the candidate was initially discovered.",
    )
    parser.add_argument(
        "--discovery-url",
        default="",
        help="Optional discovery-page URL, such as a PICRYL page.",
    )

    parser.add_argument(
        "--keep-local",
        action="store_true",
        help=(
            "Keep the full-resolution local photo after "
            "it has been uploaded to Supabase."
        ),
    )

    parser.add_argument(
        "--allow-identity-override",
        action="store_true",
        help=(
            "Allow approval when the candidate metadata does "
            "not explicitly contain the artist's name."
        ),
    )

    parser.add_argument(
        "--select-page-url",
        help=(
            "Approve the candidate having this exact Wikimedia "
            "Commons page URL. Safer than a result number."
        ),
    )

    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )

    args = parse_args()
    artist = load_artist(args.artist_id)
    artist_name = artist.artist_name.strip()
    artist_slug = slugify(artist_name)

    provider = WikimediaCommonsProvider()
    candidates = provider.search(
        args.query,
        limit=args.limit,
    )

    print()
    print("TOPSPOT STUDIO — ARTIST PHOTO COLLECTOR")
    print("=" * 65)
    print(f"Artist:     {artist_name}")
    print(f"Artist ID:  {args.artist_id}")
    print(f"Query:      {args.query}")
    print(f"Candidates: {len(candidates)}")
    print()

    for number, candidate in enumerate(
        candidates,
        start=1,
    ):
        usable = candidate_is_usable(candidate)
        identity_match = candidate_matches_artist(
            candidate,
            artist_name,
        )

        if not usable:
            status = "REJECTED"
        elif identity_match:
            status = "ELIGIBLE"
        else:
            status = "REVIEW IDENTITY"

        print(
            f"{number}. {status} "
            f"{candidate.title}"
        )
        print(
            f"   Size:    "
            f"{candidate.width}x{candidate.height}"
        )
        print(f"   Creator: {candidate.creator}")
        print(f"   License: {candidate.license_name}")
        print(f"   Page:    {candidate.page_url}")
        print()

    if (
        args.select is None
        and not args.select_page_url
    ):
        print(
            "Preview complete. Nothing was downloaded. "
            "Approve using --select-page-url URL."
        )
        return

    if args.select_page_url:
        matching_candidates = [
            candidate
            for candidate in candidates
            if candidate.page_url
            == args.select_page_url
        ]

        if len(matching_candidates) != 1:
            raise SystemExit(
                "The selected page URL was not found exactly "
                "once in the current results."
            )

        candidate = matching_candidates[0]
    else:
        selected_index = args.select - 1

        if (
            selected_index < 0
            or selected_index >= len(candidates)
        ):
            raise SystemExit(
                f"--select must be between 1 "
                f"and {len(candidates)}."
            )

        candidate = candidates[selected_index]

    if not candidate_is_usable(candidate):
        raise SystemExit(
            "Selected candidate failed the size, format, "
            "or license requirements."
        )

    if (
        not candidate_matches_artist(
            candidate,
            artist_name,
        )
        and not args.allow_identity_override
    ):
        raise SystemExit(
            "Selected candidate does not explicitly match "
            "the artist identity. Review it manually and use "
            "--allow-identity-override only if it is correct."
        )


    directories = historical_directories(
        source_type="artist_story",
        slug=artist_slug,
    )
    directories.ensure()

    duplicate_metadata = find_duplicate_metadata(
        directories.metadata,
        page_url=candidate.page_url,
        original_url=candidate.original_url,
    )

    if duplicate_metadata is not None:
        raise SystemExit(
            "This photograph is already approved:\n"
            f"{duplicate_metadata}"
        )

    photo_number = next_photo_number(
        directories.photos,
        directories.metadata,
    )
    title_slug = safe_photo_title(candidate.title)

    with TemporaryDirectory() as temporary:
        downloaded_image, _ = download_candidate(
            candidate,
            Path(temporary),
        )

        final_image_path = (
            directories.photos
            / (
                f"{photo_number:03d}-"
                f"{title_slug}"
                f"{downloaded_image.suffix.lower()}"
            )
        )

        downloaded_image.replace(final_image_path)

        storage_metadata = upload_artist_photo(
            artist_slug=artist_slug,
            photo_path=final_image_path,
        )

    metadata_path = (
        directories.metadata
        / f"{final_image_path.stem}.json"
    )

    metadata = candidate.to_dict()
    metadata.update(
        {
            "artist_id": args.artist_id,
            "artist_name": artist_name,
            "artist_slug": artist_slug,
            "search_query": args.query,
            "discovered_via": args.discovered_via,
            "discovery_url": args.discovery_url,
            "approved": True,
            "approved_at": datetime.now(UTC).isoformat(),
            "approved_image": final_image_path.name,
            **storage_metadata,
        }
    )

    save_json_atomic(
        metadata_path,
        metadata,
    )

    if not args.keep_local:
        final_image_path.unlink()

    print("=" * 65)
    print(
        f"UPLOADED: "
        f"{storage_metadata['storage_bucket']}/"
        f"{storage_metadata['storage_key']}"
    )
    print(f"METADATA: {metadata_path}")

    if args.keep_local:
        print(f"LOCAL:    {final_image_path}")
    else:
        print("LOCAL:    removed after verified upload")


if __name__ == "__main__":
    main()