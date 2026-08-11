"""Build the approved 48-video release manifest; never uploads."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.studio.youtube.manifest import load_manifest
from backend.studio.youtube.release_plan import build_manifest_document, write_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--productions-root", type=Path, default=Path("backend/studio/productions"))
    parser.add_argument("--english-playlist-id", default="PLII-SQFCqs7o")
    parser.add_argument("--spanish-playlist-id", default="PLPOixzTGhR1s")
    parser.add_argument("--portuguese-playlist-id", default="PLCKwRppGaVAs")
    parser.add_argument("--output", type=Path, default=Path("backend/studio/work/youtube_release_manifest.json"))
    args = parser.parse_args(argv)
    document = build_manifest_document(
        args.productions_root.resolve(),
        english_docuseries_playlist_id=args.english_playlist_id,
        spanish_docuseries_playlist_id=args.spanish_playlist_id,
        portuguese_docuseries_playlist_id=args.portuguese_playlist_id,
    )
    write_manifest(document, args.output)
    manifest = load_manifest(args.output)
    print(f"Dry-run manifest ready: {len(manifest.uploads)} uploads, {len(manifest.playlists)} playlists")
    print(f"Saved to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
