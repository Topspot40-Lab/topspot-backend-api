"""Create Phase 2 review artifacts without changing catalog or database data."""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection
from backend.models.dbmodels import (
    Artist,
    Decade,
    DecadeGenre,
    Genre,
    MusicDocuseries,
    MusicDocuseriesCollection,
    MusicDocuseriesLocale,
)
from backend.services.artist_spotlight_eligibility import featured_artist_eligibility_rows

GENRE_ORDER = (
    "country", "pop", "rock", "rnb_soul", "latin_global", "blues_jazz",
    "folk_acoustic", "tv_themes",
)
DOCUSERIES_GROUP_ORDER = (
    "musical_instruments", "movements_revolutions", "latin_america_and_caribbean",
    "history_eras", "legends_rivalries", "foundations_technology_events",
    "people_behind_the_music", "mysteries_tragedies", "modern_music_listening",
    "songs_stories", "modern_music_revolutions", "beyond_the_music",
    "brazil_and_new_global_sounds", "mexico_border",
)
CODE_PATTERN = re.compile(r"\b([NCAD]-\d{3})\b")
_LOWERCASE_DISPLAY_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into",
    "nor", "of", "on", "or", "over", "the", "to", "vs", "with",
}
_ACRONYMS = {
    "AC", "DC", "DJ", "MC", "R&B", "RNB", "TV", "USA", "U.S.A", "U.S.A.",
    "B.B.", "C.C.R.", "ELO", "K.C.", "LL", "P!NK",
}


def _title(value: str) -> str:
    return html.unescape(value).replace("_", " ").strip()


def _display_capitalization(value: str) -> str:
    """Match the catalog generator's render-only artist-name capitalization."""
    def capitalize_word(match: re.Match[str]) -> str:
        word = match.group(0)
        uppercase = word.upper()
        if uppercase in _ACRONYMS:
            return uppercase
        if word != word.lower() and word != word.upper():
            return word
        return word[:1].upper() + word[1:].lower()

    words = re.split(r"(\s+)", value.strip())
    positions = [index for index, word in enumerate(words) if word and not word.isspace()]
    first, last = (positions[0], positions[-1]) if positions else (-1, -1)
    polished: list[str] = []
    for index, token in enumerate(words):
        if not token or token.isspace():
            polished.append(token)
            continue
        bare = re.sub(r"^[^\w]*|[^\w]*$", "", token).lower()
        if re.fullmatch(r"\d{4}s", token, flags=re.IGNORECASE):
            polished.append(token)
        elif index not in (first, last) and bare in _LOWERCASE_DISPLAY_WORDS:
            polished.append(token.lower())
        else:
            polished.append(re.sub(
                r"[^\W\d_]+(?:[.'&-][^\W\d_]+)*", capitalize_word, token
            ))
    return "".join(polished)


def _canonical_titles(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'<span class="code">(?P<code>[NC]-\d{3})</span>.*?<h2>(?P<title>.*?)</h2>',
        re.DOTALL,
    )
    titles: dict[str, str] = {}
    for match in pattern.finditer(text):
        # A long program repeats its code on continuation pages.  The first
        # page is its canonical printed title; later headings add "continued".
        titles.setdefault(
            match.group("code"), re.sub(r"<.*?>", "", _title(match.group("title")))
        )
    return titles


def _printed_docuseries_stories(path: Path) -> list[tuple[str, str]]:
    """Read the current Docuseries review output without regenerating it."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'<article class="docuseries-story" data-docuseries-slug="(?P<slug>[^"]+)">'
        r'<h3>(?P<title>.*?)</h3>',
        re.DOTALL,
    )
    return [
        (html.unescape(match.group("slug")), re.sub(r"<.*?>", "", _title(match.group("title"))))
        for match in pattern.finditer(text)
    ]


def _same_printed_title(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        value = value.replace("â€“", "–").replace("—", "-").replace("–", "-")
        return re.sub(r"\s+", " ", value).strip().casefold()

    return normalize(left) == normalize(right)


def _scan_codes(catalog_root: Path) -> dict[str, list[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for path in (catalog_root / "backend" / "scripts" / "catalogs").rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".html", ".md", ".csv"}:
            continue
        if any(part.endswith("browser-profile") or part.startswith("tempcheck") for part in path.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for code in CODE_PATTERN.findall(content):
            found[code[0]].add(str(path.relative_to(catalog_root)).replace("\\", "/"))
    return {prefix: sorted(paths) for prefix, paths in sorted(found.items())}


def _record(
    *, code: str | None, kind: str, printed_title: str, target: dict[str, Any],
    source: str, status: str, notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "type": kind,
        "printed_title": printed_title,
        "stable_target_identity": target,
        "source_location": source,
        "status": status,
        "notes": notes or [],
    }


def build_audit(catalog_root: Path) -> dict[str, Any]:
    catalog_dir = catalog_root / "backend" / "scripts" / "catalogs"
    manifest_path = catalog_dir / "catalog_code_manifest.json"
    master_html = catalog_dir / "output" / "topspot40_master_print_catalog.html"
    docuseries_review_html = (
        catalog_dir / "output" / "topspot40_master_print_catalog_music_docuseries_review.html"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    html_titles = _canonical_titles(master_html)
    printed_docuseries = _printed_docuseries_stories(docuseries_review_html)
    records: list[dict[str, Any]] = []
    ambiguities: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []

    with Session(engine) as session:
        decades = {row.id: row for row in session.exec(select(Decade)).all()}
        genres = {row.id: row for row in session.exec(select(Genre)).all()}
        genres_by_slug = {row.slug: row for row in genres.values()}
        decade_genres = {
            (decades[row.decade_id].slug, genres[row.genre_id].slug): row
            for row in session.exec(select(DecadeGenre)).all()
            if row.decade_id in decades and row.genre_id in genres
        }
        collections = {row.slug: row for row in session.exec(select(Collection)).all()}
        for entry in manifest["nostalgia"]:
            identity = (entry["decade_slug"], entry["genre_slug"])
            target = decade_genres.get(identity)
            genre = genres_by_slug.get(entry["genre_slug"])
            title = f"{entry['decade_slug']} {genre.genre_name if genre else entry['genre_slug']}"
            status = "printed_verified" if target and _same_printed_title(html_titles.get(entry["code"], ""), title) else "needs_review"
            if not target:
                ambiguities.append({"code": entry["code"], "reason": "Nostalgia target missing from database", "identity": identity})
            if target and not _same_printed_title(html_titles.get(entry["code"], ""), title):
                ambiguities.append({"code": entry["code"], "reason": "Canonical HTML title differs from database-derived title", "html_title": html_titles.get(entry["code"]), "database_title": title})
            records.append(_record(
                code=entry["code"], kind="nostalgia", printed_title=html_titles.get(entry["code"], title),
                target={"decade_slug": identity[0], "genre_slug": identity[1], "decade_genre_id": target.id if target else None},
                source="backend/scripts/catalogs/catalog_code_manifest.json#nostalgia",
                status=status,
            ))
        for entry in manifest["collections"]:
            target = collections.get(entry["slug"])
            title = target.name if target else entry["slug"]
            status = "printed_verified" if target and _same_printed_title(html_titles.get(entry["code"], ""), title) else "needs_review"
            if not target:
                ambiguities.append({"code": entry["code"], "reason": "Collection target missing from database", "slug": entry["slug"]})
            if target and not _same_printed_title(html_titles.get(entry["code"], ""), title):
                ambiguities.append({"code": entry["code"], "reason": "Canonical HTML title differs from database title", "html_title": html_titles.get(entry["code"]), "database_title": title})
            records.append(_record(
                code=entry["code"], kind="collection", printed_title=html_titles.get(entry["code"], title),
                target={"collection_slug": entry["slug"], "collection_id": target.id if target else None},
                source="backend/scripts/catalogs/catalog_code_manifest.json#collections",
                status=status,
            ))

        all_artist_rows = featured_artist_eligibility_rows(
            genres=list(GENRE_ORDER), per_genre=True,
        )
        retained_rows = [row for row in all_artist_rows if row["genre_slug"] != "tv_themes"]
        by_artist: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in retained_rows:
            by_artist[row["artist_id"]].append(row)
        tv_only = {
            row["artist_id"] for row in all_artist_rows if row["genre_slug"] == "tv_themes"
        } - set(by_artist)
        artist_by_id = {
            row.id: row for row in session.exec(select(Artist).where(Artist.id.in_(by_artist))).all()
        }
        ordered_artists = sorted(
            by_artist.items(),
            key=lambda pair: (
                min(row["genre_name"].casefold() for row in pair[1]),
                min(row["artist_name"].casefold() for row in pair[1]),
                pair[0],
            ),
        )
        for number, (artist_id, rows) in enumerate(ordered_artists, start=1):
            artist = artist_by_id.get(artist_id)
            categories = sorted({row["genre_slug"] for row in rows})
            records.append(_record(
                code=None, kind="artist_spotlight",
                printed_title=_display_capitalization(rows[0]["artist_name"]),
                target={"artist_id": artist_id, "spotify_artist_id": artist.spotify_artist_id if artist else None, "retained_genre_slugs": categories},
                source="backend/scripts/catalogs/output/topspot40_master_print_catalog.html#artist-spotlight-directory",
                status="proposed_pending_gary",
                notes=[f"Proposed A-{number:03d}; no printed A-xxx assignment exists."],
            ))
        for artist_id in sorted(tv_only):
            artist = session.get(Artist, artist_id)
            exclusions.append({
                "type": "artist_spotlight", "artist_id": artist_id,
                "artist_name": artist.artist_name if artist else None,
                "reason": "Excluded: appears only in the TV Themes Artist Spotlight category.",
            })

        story_rows = session.exec(
            select(MusicDocuseriesCollection, MusicDocuseries, MusicDocuseriesLocale)
            .join(MusicDocuseries, MusicDocuseries.collection_id == MusicDocuseriesCollection.id)
            .join(MusicDocuseriesLocale, MusicDocuseriesLocale.docuseries_id == MusicDocuseries.id)
            .where(MusicDocuseriesCollection.is_active == True)
            .where(MusicDocuseries.is_active == True)
            .where(MusicDocuseriesLocale.language_code == "en")
            .order_by(MusicDocuseries.sort_order, MusicDocuseries.id)
        ).all()
        stories_by_group: dict[str, list[tuple[Any, Any, Any]]] = {
            slug: [] for slug in DOCUSERIES_GROUP_ORDER
        }
        unexpected_story_groups: set[str] = set()
        for group, story, locale in story_rows:
            if group.slug not in stories_by_group:
                unexpected_story_groups.add(group.slug)
                continue
            stories_by_group[group.slug].append((group, story, locale))

        docuseries_story_memberships: dict[int, set[str]] = defaultdict(set)
        for slug in DOCUSERIES_GROUP_ORDER:
            stories = stories_by_group[slug]
            if not stories:
                ambiguities.append({
                    "type": "docuseries_group", "slug": slug,
                    "reason": "No active English story appears under this printed heading.",
                })
            for group, story, _locale in stories:
                docuseries_story_memberships[story.id].add(group.slug)
                records.append(_record(
                    code=None, kind="music_docuseries_story", printed_title=story.title,
                    target={
                        "music_docuseries_id": story.id,
                        "music_docuseries_slug": story.slug,
                        "music_docuseries_title": story.title,
                        "group_slug": group.slug,
                        "group_name": group.name,
                        "music_docuseries_collection_id": group.id,
                    },
                    source="backend/scripts/catalogs/master_print_catalog.py#DOCUSERIES_GROUP_ORDER",
                    status="proposed_pending_gary",
                    notes=["No printed D-xxx assignment exists; proposed in catalog story order."],
                ))
        if unexpected_story_groups:
            ambiguities.append({
                "type": "docuseries_story", "reason": "Active English stories appear in groups outside the catalog order.",
                "group_slugs": sorted(unexpected_story_groups),
            })
        audited_docuseries = [
            record for record in records if record["type"] == "music_docuseries_story"
        ]
        printed_slug_counts = Counter(slug for slug, _title in printed_docuseries)
        audited_by_slug = {
            record["stable_target_identity"]["music_docuseries_slug"]: record
            for record in audited_docuseries
        }
        printed_by_slug = dict(printed_docuseries)
        missing_from_print = sorted(set(audited_by_slug) - set(printed_slug_counts))
        unexpected_in_print = sorted(set(printed_slug_counts) - set(audited_by_slug))
        duplicate_printed_slugs = sorted(
            slug for slug, count in printed_slug_counts.items() if count > 1
        )
        title_mismatches = sorted(
            slug for slug, record in audited_by_slug.items()
            if slug in printed_by_slug
            and not _same_printed_title(
                record["stable_target_identity"]["music_docuseries_title"],
                printed_by_slug[slug],
            )
        )
        if missing_from_print or unexpected_in_print or duplicate_printed_slugs or title_mismatches:
            ambiguities.append({
                "type": "docuseries_story", "reason": "Printed Docuseries review output does not match source records.",
                "missing_from_print": missing_from_print,
                "unexpected_in_print": unexpected_in_print,
                "duplicate_printed_slugs": duplicate_printed_slugs,
                "title_mismatches": title_mismatches,
            })

    code_counts = Counter(record["code"][0] for record in records if record["code"])
    proposed = {
        "artist_spotlights": [
            {"proposed_code": f"A-{number:03d}", **record}
            for number, record in enumerate(
                (record for record in records if record["type"] == "artist_spotlight"), start=1
            )
        ],
        "docuseries_stories": [
            {"proposed_code": f"D-{number:03d}", **record}
            for number, record in enumerate(
                (record for record in records if record["type"] == "music_docuseries_story"), start=1
            )
        ],
    }
    codes = [record["code"] for record in records if record["code"]]
    targets = [json.dumps(record["stable_target_identity"], sort_keys=True) for record in records]
    diagnostics = {
        "duplicate_codes": sorted({code for code in codes if codes.count(code) > 1}),
        "duplicate_targets": sorted({target for target in targets if targets.count(target) > 1}),
        "missing_programs": [record for record in records if record["status"] == "needs_review"],
        "inconsistent_titles": [item for item in ambiguities if "title" in item["reason"]],
        "docuseries_printed_story_count": len([
            record for record in records if record["type"] == "music_docuseries_story"
        ]),
        "docuseries_review_story_count": len(printed_docuseries),
        "docuseries_missing_from_review": missing_from_print,
        "docuseries_unexpected_in_review": unexpected_in_print,
        "docuseries_duplicate_printed_slugs": duplicate_printed_slugs,
        "docuseries_title_mismatches": title_mismatches,
        "docuseries_duplicate_story_ids": sorted(
            story_id for story_id, memberships in docuseries_story_memberships.items()
            if len(memberships) > 1
        ),
        "docuseries_stories_in_multiple_groups": {
            str(story_id): sorted(memberships)
            for story_id, memberships in docuseries_story_memberships.items()
            if len(memberships) > 1
        },
        "docuseries_unexpected_group_slugs": sorted(unexpected_story_groups),
        "existing_code_locations": _scan_codes(catalog_root),
    }
    return {
        "audit_version": 1,
        "scope": {
            "catalog_manifest": str(manifest_path),
            "canonical_master_html": str(master_html),
            "docuseries_current_review_html": str(docuseries_review_html),
            "radio_mode": "not inspected or changed; excluded from program-code scope",
            "tv_themes": "excluded only from Artist Spotlight proposals; retained in Nostalgia N-008 through N-064 and other catalog data",
        },
        "counts_by_prefix": {"N": code_counts["N"], "C": code_counts["C"], "A": 0, "D": 0, "proposed_A": len(proposed["artist_spotlights"]), "proposed_D": len(proposed["docuseries_stories"])},
        "records": records,
        "proposed_assignments_requiring_gary_approval": proposed,
        "ambiguities": ambiguities,
        "exclusions": exclusions,
        "diagnostics": diagnostics,
    }


def write_artifacts(audit: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "program_code_phase2_mapping.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output_dir / "program_code_phase2_audit.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "code", "type", "printed_title", "stable_target_identity",
            "source_location", "status", "notes",
        ])
        writer.writeheader()
        for record in audit["records"]:
            writer.writerow({
                **record,
                "stable_target_identity": json.dumps(record["stable_target_identity"], sort_keys=True),
                "notes": " | ".join(record["notes"]),
            })
    (output_dir / "program_code_phase2_proposed_a_d.json").write_text(
        json.dumps(audit["proposed_assignments_requiring_gary_approval"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "program_code_phase2_proposed_a_d.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=[
            "proposed_code", "type", "printed_title", "stable_target_identity",
            "source_location", "status", "notes",
        ])
        writer.writeheader()
        for group in audit["proposed_assignments_requiring_gary_approval"].values():
            for record in group:
                writer.writerow({
                    "proposed_code": record["proposed_code"],
                    "type": record["type"],
                    "printed_title": record["printed_title"],
                    "stable_target_identity": json.dumps(
                        record["stable_target_identity"], sort_keys=True
                    ),
                    "source_location": record["source_location"],
                    "status": record["status"],
                    "notes": " | ".join(record["notes"]),
                })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    write_artifacts(build_audit(args.catalog_root), args.output_dir)


if __name__ == "__main__":
    main()
