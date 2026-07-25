from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlmodel import Session, select

from backend.database import engine
from backend.models.studio_models import (
    StudioProductionAsset,
)


YOUTUBE_VIDEOS = {
    ("casey_kasem", "en"): "S714GDHmXOM",
    ("casey_kasem", "es"): "gzIDwxIfduE",
    ("casey_kasem", "pt-BR"): "n42Hj2Iu7mQ",

    ("dick_clark", "en"): "2yScit1XO6w",
    ("dick_clark", "es"): "axSE5mnulZo",
    ("dick_clark", "pt-BR"): "u7jUqAgdyp4",

    ("ed_sullivan", "en"): "LT26QwbhG6w",
    ("ed_sullivan", "es"): "U076P30Uww4",
    ("ed_sullivan", "pt-BR"): "NZi3L-sajXY",

    ("johnny_cash", "en"): "hRcz2e1b_Uk",
    ("johnny_cash", "es"): "bF6-8bfakCQ",
    ("johnny_cash", "pt-BR"): "aIPu_LqI0qc",

    ("juan_gabriel", "en"): "vuhujKxvJjs",
    ("juan_gabriel", "es"): "EwupTOHF5V4",
    ("juan_gabriel", "pt-BR"): "wjE0Lp6zp2A",

    ("luis_miguel", "en"): "kfy9oGvZhes",
    ("luis_miguel", "es"): "aaJ2204NqUo",
    ("luis_miguel", "pt-BR"): "HIX_Eo3iEa4",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Attach canonical YouTube IDs to "
            "published localized-video assets."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the links to the database.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mode = "APPLY" if args.apply else "DRY RUN"

    print(
        "TOPSPOT — YOUTUBE VIDEO LINK CATALOG"
    )
    print(f"MODE: {mode}")
    print("=" * 78)

    found = 0
    updates = 0
    unchanged = 0
    missing = 0
    conflicts = 0

    with Session(engine) as db:
        for (
            slug,
            language_code,
        ), video_id in YOUTUBE_VIDEOS.items():
            statement = select(
                StudioProductionAsset
            ).where(
                StudioProductionAsset.slug
                == slug,
                StudioProductionAsset.asset_type
                == "localized_video",
                StudioProductionAsset.language_code
                == language_code,
                StudioProductionAsset.version_number
                == 1,
                StudioProductionAsset.is_current
                == True,
            )

            rows = db.exec(statement).all()

            if not rows:
                missing += 1
                print(
                    f"MISSING   {slug:16} "
                    f"{language_code:5}"
                )
                continue

            if len(rows) != 1:
                conflicts += 1
                print(
                    f"CONFLICT  {slug:16} "
                    f"{language_code:5} "
                    f"rows={len(rows)}"
                )
                continue

            asset = rows[0]
            found += 1

            url = (
                "https://www.youtube.com/"
                f"watch?v={video_id}"
            )

            if (
                asset.youtube_video_id == video_id
                and asset.youtube_url == url
            ):
                unchanged += 1
                action = "UNCHANGED"
            else:
                updates += 1
                action = "UPDATE"

            print(
                f"{action:9} "
                f"{slug:16} "
                f"{language_code:5} "
                f"{video_id}"
            )

            if args.apply and action == "UPDATE":
                asset.youtube_video_id = video_id
                asset.youtube_url = url
                asset.updated_at = datetime.now(UTC)
                db.add(asset)

        if (
            args.apply
            and missing == 0
            and conflicts == 0
        ):
            db.commit()

    print()
    print("=" * 78)
    print(f"Expected:  {len(YOUTUBE_VIDEOS)}")
    print(f"Found:     {found}")
    print(f"Updates:   {updates}")
    print(f"Unchanged: {unchanged}")
    print(f"Missing:   {missing}")
    print(f"Conflicts: {conflicts}")

    if not args.apply:
        print()
        print(
            "Dry run only. Add --apply "
            "to update the database."
        )


if __name__ == "__main__":
    main()
