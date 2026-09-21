"""Build the permanent-code TopSpot40 master printed catalog.

This module deliberately keeps the catalog code manifest in Git. A database ID
or an alphabetic sort is not a printed catalog identifier: changing either must
never renumber a program that has already appeared in print.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

from sqlmodel import Session, select

from backend.database import engine
from backend.models.collection_models import Collection, CollectionCategory, CollectionTrackRanking
from backend.models.dbmodels import (
    Artist,
    Decade,
    DecadeGenre,
    Genre,
    MusicDocuseries,
    MusicDocuseriesCollection,
    MusicDocuseriesLocale,
    Track,
    TrackRanking,
)
from backend.services.artist_spotlight_eligibility import featured_artist_eligibility_rows

CATALOG_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = CATALOG_DIR / "catalog_code_manifest.json"
APPROVED_MANIFEST_PATH = CATALOG_DIR / "approved_program_code_manifest.json"
APPROVED_MANIFEST_SHA256 = "1359c98fc1f2f417d48e427e4ab76a0c3d79c3e3b724dfd7e26622a105c99b82"
OUTPUT_DIR = CATALOG_DIR / "output"
ARTWORK_DIR = CATALOG_DIR / "assets" / "TopSpot40-catalog-artwork"
ARTWORK_URL = "../assets/TopSpot40-catalog-artwork"
DIVIDER_BRAND_ARTWORK = "topspot40-old-dog-new-tracks-bw.png"
ARTIST_SPOTLIGHT_DIVIDER_ARTWORK = "artist-spotlight-directory.png"
CONTINUATION_ARTWORK_DIR = ARTWORK_DIR / "continuation-artwork"
CONTINUATION_ARTWORK_URL = f"{ARTWORK_URL}/continuation-artwork"
DECADE_ORDER = ("1950s", "1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "2020s")
GENRE_ORDER = ("country", "pop", "rock", "rnb_soul", "latin_global", "blues_jazz", "folk_acoustic", "tv_themes")
# The page planners budget wrapped 12pt lines rather than a raw item count.
# These limits deliberately retain a generous protected area above each folio.
TRACK_COLUMN_LINE_CAPACITY = 29
ARTIST_COLUMN_LINE_CAPACITY = 25
ARTISTS_PER_DIRECTORY_PAGE = ARTIST_COLUMN_LINE_CAPACITY * 3
TOC_ITEMS_PER_PAGE = 44
DOCUSERIES_COLUMN_LINE_CAPACITY = 18

# The application has an intentionally curated display order for these
# collections.  Database sort orders are retained for story ordering within a
# collection, but they are not reliable for ordering the collections because
# older seed data includes overlapping collection sort orders.
DOCUSERIES_GROUP_ORDER = (
    "musical_instruments",
    "movements_revolutions",
    "latin_america_and_caribbean",
    "history_eras",
    "legends_rivalries",
    "foundations_technology_events",
    "people_behind_the_music",
    "mysteries_tragedies",
    "modern_music_listening",
    "songs_stories",
    "modern_music_revolutions",
    "beyond_the_music",
    "brazil_and_new_global_sounds",
    "mexico_border",
)

COLLECTION_GROUP_ARTWORK = {
    "american_heritage_favorites": "collection-group-american-heritage-favorites.png",
    "traditional_favorites": "collection-group-traditional-favorites.png",
    "world_heritage_favorites": "collection-group-world-heritage-favorites.png",
    "soft_rock_70s_90s": "collection-group-soft-rock-70s-90s.png",
    "music_trends": "collection-group-music-trends.png",
    "music_legends": "collection-group-music-legends.png",
    "stage_and_screen": "collection-group-stage-screen.png",
    "classical_music": "collection-group-classical-music.png",
    "specialty_mixes": "collection-group-specialty-mixes.png",
}

_LOWERCASE_DISPLAY_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor", "of", "on", "or", "over", "the", "to", "vs", "with"}
_ACRONYMS = {"AC", "DC", "DJ", "MC", "R&B", "RNB", "TV", "USA", "U.S.A", "U.S.A.", "B.B.", "C.C.R.", "ELO", "K.C.", "LL", "P!NK"}


class ManifestValidationError(ValueError):
    """Raised when the checked-in permanent-code manifest and DB disagree."""


@dataclass(frozen=True)
class Program:
    code: str
    kind: str
    title: str
    slug: str
    decade: str | None = None
    genre: str | None = None
    category: str | None = None
    category_slug: str | None = None
    category_sort_order: int | None = None
    tracks: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CollectionGroup:
    """A print ordering view of the program's existing DB collection groups."""

    name: str
    slug: str
    sort_order: int | None
    collections: tuple[Program, ...]


@dataclass(frozen=True)
class TocBlock:
    title: str
    entries: tuple[Program, ...] = ()
    detail: str | None = None
    continuation: bool = False


@dataclass(frozen=True)
class ContinuationArtwork:
    """Approved artwork placed on one named program's final overflow page."""

    filename: str
    width_in: float
    height_in: float
    x_in: float
    y_in: float


@dataclass(frozen=True)
class DocuseriesStory:
    """An active English-language narrated Music Docuseries story."""

    slug: str
    title: str
    story_text: str
    duration_seconds: int | None
    code: str = ""
    short_description: str | None = None


@dataclass(frozen=True)
class DocuseriesGroup:
    """A print-ordered Music Docuseries collection and its stories."""

    slug: str
    name: str
    stories: tuple[DocuseriesStory, ...]


# These coordinates are the approved trim-page coordinates in
# continuation-artwork/PLACEMENT_MANIFEST.txt.  Keeping them in one shared
# mapping makes the printed placement auditable and prevents generic artwork
# from being applied to a different program or overflow page.
CONTINUATION_ARTWORK: dict[str, ContinuationArtwork] = {
    "N-007": ContinuationArtwork("continuation-n007-1950s-folk-acoustic.png", 4.8, 2.4, 3.1, 5.0),
    "N-015": ContinuationArtwork("continuation-n015-1960s-folk-acoustic.png", 4.8, 2.5, 3.1, 4.8),
    "N-023": ContinuationArtwork("continuation-n023-1970s-folk-acoustic.png", 4.8, 2.4, 3.1, 5.0),
    "N-031": ContinuationArtwork("continuation-n031-1980s-folk-acoustic.png", 4.8, 2.3, 3.1, 5.1),
    "N-039": ContinuationArtwork("continuation-n039-1990s-folk-acoustic.png", 4.6, 1.7, 3.2, 5.5),
    "N-047": ContinuationArtwork("continuation-n047-2000s-folk-acoustic.png", 4.6, 1.6, 3.2, 5.6),
    "N-055": ContinuationArtwork("continuation-n055-2010s-folk-acoustic.png", 4.8, 2.4, 3.1, 5.0),
    "C-032": ContinuationArtwork("continuation-c032-legends-tv-themes.png", 4.8, 2.5, 3.1, 4.8),
    "C-050": ContinuationArtwork("continuation-c050-video-game-themes.png", 4.6, 1.8, 3.2, 5.4),
}


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_approved_manifest(path: Path = APPROVED_MANIFEST_PATH) -> dict[str, Any]:
    """Load the verbatim backend-approved mapping and guard against drift."""
    if hashlib.sha256(path.read_bytes()).hexdigest() != APPROVED_MANIFEST_SHA256:
        raise ManifestValidationError("approved program-code manifest checksum differs from backend-approved mapping")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assignments = payload.get("assignments", [])
    counts = {prefix: sum(item.get("code", "").startswith(f"{prefix}-") for item in assignments) for prefix in "NCAD"}
    if payload.get("approved") is not True or counts != {"N": 64, "C": 52, "A": 226, "D": 127}:
        raise ManifestValidationError("approved program-code manifest has invalid counts")
    if len({item["code"] for item in assignments}) != 469:
        raise ManifestValidationError("approved program-code manifest has duplicate codes")
    return payload


def approved_code_maps(manifest: dict[str, Any]) -> tuple[dict[int, str], dict[str, str]]:
    assignments = manifest["assignments"]
    artists = {item["target"]["artist_id"]: item["code"] for item in assignments if item["kind"] == "artist_spotlight"}
    stories = {item["target"]["slug"]: item["code"] for item in assignments if item["kind"] == "docuseries_story"}
    if len(artists) != 226 or len(stories) != 127:
        raise ManifestValidationError("approved Artist Spotlight or Docuseries targets are not unique")
    return artists, stories


def _expected_codes(prefix: str, count: int) -> set[str]:
    return {f"{prefix}-{number:03d}" for number in range(1, count + 1)}


def validate_manifest(manifest: dict[str, Any], available: dict[str, set[Any]] | None = None) -> None:
    """Validate numbering and, when supplied, database membership."""
    problems: list[str] = []
    for section, prefix, total in (("nostalgia", "N", 64), ("collections", "C", 52)):
        entries = manifest.get(section)
        if not isinstance(entries, list):
            problems.append(f"{section} must be a list")
            continue
        codes = [entry.get("code") for entry in entries]
        duplicates = sorted({code for code in codes if code and codes.count(code) > 1})
        if duplicates:
            problems.append(f"duplicate {section} codes: {', '.join(duplicates)}")
        actual, expected = set(codes), _expected_codes(prefix, total)
        missing, unexpected = sorted(expected - actual), sorted(actual - expected)
        if missing:
            problems.append(f"missing {section} codes: {', '.join(missing)}")
        if unexpected:
            problems.append(f"invalid {section} codes: {', '.join(unexpected)}")
        if len(entries) != total:
            problems.append(f"{section} has {len(entries)} entries; expected {total}")
    nostalgia_keys = [(x.get("decade_slug"), x.get("genre_slug")) for x in manifest.get("nostalgia", [])]
    collection_keys = [x.get("slug") for x in manifest.get("collections", [])]
    if len(nostalgia_keys) != len(set(nostalgia_keys)):
        problems.append("duplicate nostalgia program identities")
    if len(collection_keys) != len(set(collection_keys)):
        problems.append("duplicate collection program identities")
    if available is not None:
        manifest_nostalgia, manifest_collections = set(nostalgia_keys), set(collection_keys)
        for label, stale, unassigned in (
            ("nostalgia", sorted(manifest_nostalgia - available["nostalgia"]), sorted(available["nostalgia"] - manifest_nostalgia)),
            ("collection", sorted(manifest_collections - available["collections"]), sorted(available["collections"] - manifest_collections)),
        ):
            if stale:
                problems.append(f"stale {label} entries: {stale}")
            if unassigned:
                problems.append(f"unassigned {label} entries: {unassigned}")
    if problems:
        raise ManifestValidationError("; ".join(problems))


def ordered_nostalgia_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    decades = {value: index for index, value in enumerate(DECADE_ORDER)}
    genres = {value: index for index, value in enumerate(GENRE_ORDER)}
    return sorted(manifest["nostalgia"], key=lambda entry: (
        decades.get(entry["decade_slug"], len(DECADE_ORDER)),
        genres.get(entry["genre_slug"], len(GENRE_ORDER)),
    ))


def _rows_to_tracks(rows: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    return tuple({"rank": int(ranking), "title": track_name, "artist": artist_display_name or artist_name or "Unknown Artist", "year": year_released}
        for ranking, track_name, artist_display_name, artist_name, year_released in rows)


def load_programs(session: Session, manifest: dict[str, Any]) -> list[Program]:
    decades = {row.id: row for row in session.exec(select(Decade)).all()}
    genres = {row.id: row for row in session.exec(select(Genre)).all()}
    db_nostalgia = {(decades[row.decade_id].slug, genres[row.genre_id].slug): row for row in session.exec(select(DecadeGenre)).all()
        if row.decade_id in decades and row.genre_id in genres}
    db_collections = {row.slug: row for row in session.exec(select(Collection)).all()}
    validate_manifest(manifest, {"nostalgia": set(db_nostalgia), "collections": set(db_collections)})
    categories = {row.id: row for row in session.exec(select(CollectionCategory)).all()}
    programs: list[Program] = []
    for entry in ordered_nostalgia_entries(manifest):
        decade_slug, genre_slug = entry["decade_slug"], entry["genre_slug"]
        db_row = db_nostalgia[(decade_slug, genre_slug)]
        rows = session.exec(select(TrackRanking.ranking, Track.track_name, Track.artist_display_name, Artist.artist_name, Track.year_released)
            .join(Track, TrackRanking.track_id == Track.id).join(Artist, Track.artist_id == Artist.id)
            .where(TrackRanking.decade_genre_id == db_row.id).order_by(TrackRanking.ranking)).all()
        programs.append(Program(entry["code"], "Nostalgia", f"{decade_slug} {genres[db_row.genre_id].genre_name}",
            db_row.slug or f"{decade_slug}-{genre_slug}", decade_slug, genre_slug, tracks=_rows_to_tracks(rows)))
    for entry in manifest["collections"]:
        db_row = db_collections[entry["slug"]]
        rows = session.exec(select(CollectionTrackRanking.ranking, Track.track_name, Track.artist_display_name, Artist.artist_name, Track.year_released)
            .join(Track, CollectionTrackRanking.track_id == Track.id).join(Artist, Track.artist_id == Artist.id)
            .where(CollectionTrackRanking.collection_id == db_row.id).order_by(CollectionTrackRanking.ranking)).all()
        category = categories.get(db_row.category_id)
        programs.append(Program(
            entry["code"], "Collection", db_row.name, db_row.slug,
            category=category.name if category else None,
            category_slug=category.slug if category else None,
            category_sort_order=category.sort_order if category else None,
            tracks=_rows_to_tracks(rows),
        ))
    return programs


def load_docuseries_groups(session: Session, story_codes: dict[str, str] | None = None) -> list[DocuseriesGroup]:
    """Load every active English story in the application's curated group order.

    ``MusicDocuseriesLocale`` is the authoritative source for narration and
    duration.  Requiring its English row prevents untranslated metadata from
    entering this English-language print edition.
    """
    rows = session.exec(
        select(MusicDocuseriesCollection, MusicDocuseries, MusicDocuseriesLocale)
        .join(MusicDocuseries, MusicDocuseries.collection_id == MusicDocuseriesCollection.id)
        .join(MusicDocuseriesLocale, MusicDocuseriesLocale.docuseries_id == MusicDocuseries.id)
        .where(MusicDocuseriesCollection.is_active == True)
        .where(MusicDocuseries.is_active == True)
        .where(MusicDocuseriesLocale.language_code == "en")
        .order_by(MusicDocuseries.sort_order, MusicDocuseries.id)
    ).all()
    grouped: dict[str, list[DocuseriesStory]] = {slug: [] for slug in DOCUSERIES_GROUP_ORDER}
    names: dict[str, str] = {}
    unexpected: set[str] = set()
    for group, story, locale in rows:
        if group.slug not in grouped:
            unexpected.add(group.slug)
            continue
        names[group.slug] = group.name
        grouped[group.slug].append(DocuseriesStory(
            slug=story.slug,
            code=story_codes.get(story.slug, "") if story_codes is not None else "",
            title=story.title,
            story_text=locale.story_text or "",
            duration_seconds=locale.duration_seconds,
            short_description=story.short_description,
        ))
    missing = [slug for slug in DOCUSERIES_GROUP_ORDER if not grouped[slug]]
    unresolved = [story.slug for stories in grouped.values() for story in stories if not story.code]
    if missing or unexpected or (story_codes is not None and (unresolved or set(story_codes) != {story.slug for stories in grouped.values() for story in stories})):
        details = []
        if missing:
            details.append(f"missing active English Music Docuseries groups: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected active English Music Docuseries groups: {', '.join(sorted(unexpected))}")
        if story_codes is not None and unresolved:
            details.append(f"unassigned Music Docuseries stories: {', '.join(unresolved)}")
        if story_codes is not None and set(story_codes) != {story.slug for stories in grouped.values() for story in stories}:
            details.append("approved Docuseries manifest does not exactly match catalog stories")
        raise ManifestValidationError("; ".join(details))
    return [DocuseriesGroup(slug, names[slug], tuple(grouped[slug])) for slug in DOCUSERIES_GROUP_ORDER]


def load_artist_spotlight_rows(artist_codes: dict[int, str]) -> list[dict[str, Any]]:
    """Return approved, non-TV-Themes directory rows annotated with A codes."""
    rows = featured_artist_eligibility_rows(
        genres=[genre for genre in GENRE_ORDER if genre != "tv_themes"], per_genre=True,
    )
    approved = [dict(row, code=artist_codes[row["artist_id"]]) for row in rows if row["artist_id"] in artist_codes]
    present = {row["artist_id"] for row in approved}
    if present != set(artist_codes):
        raise ManifestValidationError("approved Artist Spotlight manifest does not exactly match retained directory artists")
    if any(row.get("genre_slug") == "tv_themes" for row in approved):
        raise ManifestValidationError("TV Themes is not permitted in Artist Spotlight directory")
    return approved


def collection_groups(collections: Iterable[Program]) -> tuple[list[CollectionGroup], list[str]]:
    """Group catalog collections by their existing category relationship.

    CollectionCategory.sort_order is the program's stored group ordering.  A
    name/slug ordering only breaks ties, and collection title/slug ordering is
    used because collections have no stored display-order field.
    """
    grouped: dict[tuple[str, str, int | None], list[Program]] = defaultdict(list)
    ungrouped: list[Program] = []
    for collection in collections:
        if collection.category and collection.category_slug:
            grouped[(collection.category, collection.category_slug, collection.category_sort_order)].append(collection)
        else:
            ungrouped.append(collection)
    groups = [
        CollectionGroup(
            name=name,
            slug=slug,
            sort_order=sort_order,
            collections=tuple(sorted(items, key=lambda program: (program.title.casefold(), program.slug.casefold(), program.code))),
        )
        for (name, slug, sort_order), items in grouped.items()
    ]
    groups.sort(key=lambda group: (group.sort_order is None, group.sort_order if group.sort_order is not None else 0, group.name.casefold(), group.slug))
    if ungrouped:
        groups.append(CollectionGroup(
            name="Other Collections",
            slug="other_collections",
            sort_order=None,
            collections=tuple(sorted(ungrouped, key=lambda program: (program.title.casefold(), program.slug.casefold(), program.code))),
        ))
    return groups, [program.slug for program in sorted(ungrouped, key=lambda program: program.slug.casefold())]


def placeholder(label: str, url: str | None) -> str:
    if url:
        return f'<div class="qr" data-qr-url="{html.escape(url, quote=True)}"><strong>{html.escape(label)}</strong><br>QR route configured</div>'
    return f'<div class="qr qr-placeholder"><strong>{html.escape(label)}</strong><br>QR route pending confirmation</div>'


def display_capitalization(value: str | None) -> str:
    """Polish a database label for print without changing its stored value."""
    if not value:
        return ""

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
            polished.append(re.sub(r"[^\W\d_]+(?:[.'&-][^\W\d_]+)*", capitalize_word, token))
    return "".join(polished)


def estimated_print_lines(value: str, *, characters_per_line: int) -> float:
    """Conservative line budget for a fixed-width print column."""
    text = re.sub(r"\s+", " ", value).strip()
    return max(1, math.ceil(len(text) / characters_per_line))


def partition_for_print_columns(
    items: tuple[Any, ...] | list[Any],
    weights: list[float],
    *,
    columns: int,
    column_capacity: float,
) -> list[list[Any]]:
    """Keep ordered items intact while balancing pages below a safe budget."""
    if not items:
        return [[]]
    maximum = columns * column_capacity
    page_count = max(1, math.ceil(sum(weights) / maximum))
    pending_items, pending_weights = list(items), list(weights)
    pages: list[list[Any]] = []
    for page_index in range(page_count):
        remaining_pages = page_count - page_index
        target = sum(pending_weights) / remaining_pages
        page: list[Any] = []
        used = 0.0
        while pending_items:
            next_weight = pending_weights[0]
            if page and (used >= target or used + next_weight > maximum):
                break
            page.append(pending_items.pop(0))
            used += pending_weights.pop(0)
        if not page and pending_items:
            page.append(pending_items.pop(0))
            pending_weights.pop(0)
        pages.append(page)
    if pending_items:
        pages[-1].extend(pending_items)
    return pages


def split_print_columns(items: list[Any], weights: list[float], columns: int) -> list[list[Any]]:
    """Split an already-safe page into ordered, visually balanced columns."""
    if not items:
        return [[] for _ in range(columns)]
    pending_items, pending_weights = list(items), list(weights)
    columns_out: list[list[Any]] = []
    for index in range(columns):
        remaining_columns = columns - index
        if remaining_columns == 1:
            columns_out.append(pending_items)
            break
        target = sum(pending_weights) / remaining_columns
        column: list[Any] = []
        used = 0.0
        while pending_items:
            if column and used >= target:
                break
            column.append(pending_items.pop(0))
            used += pending_weights.pop(0)
        columns_out.append(column)
    while len(columns_out) < columns:
        columns_out.append([])
    return columns_out


def track_print_weight(track: dict[str, Any]) -> float:
    year = f" ({track['year']})" if track.get("year") else ""
    text = f"#{track['rank']} {display_capitalization(track['title'])} — {display_capitalization(track['artist'])}{year}"
    return estimated_print_lines(text, characters_per_line=70) + .27


def artist_print_weight(row: dict[str, Any]) -> float:
    text = f"{row.get('code', '')} {display_capitalization(row['artist_name'])} {row['genre_track_count']} eligible tracks"
    return estimated_print_lines(text, characters_per_line=40) + .28


def render_track(track: dict[str, Any]) -> str:
    year = f' <span class="year">({html.escape(str(track["year"]))})</span>' if track.get("year") else ""
    return f'<li><span class="rank">#{track["rank"]}</span> <span class="song">{html.escape(display_capitalization(track["title"]))}</span> <span class="artist">— {html.escape(display_capitalization(track["artist"]))}</span>{year}</li>'


def render_continuation_artwork(program: Program, page_number: int, page_count: int) -> str:
    """Render an approved asset only on its assigned program's final continuation."""
    artwork = CONTINUATION_ARTWORK.get(program.code)
    if artwork is None or page_number != page_count or page_number == 1:
        return ""
    source = f"{CONTINUATION_ARTWORK_URL}/{artwork.filename}"
    style = (f"left: {artwork.x_in:g}in; top: {artwork.y_in:g}in; "
             f"width: {artwork.width_in:g}in; height: {artwork.height_in:g}in;")
    return (f'<img class="continuation-artwork" src="{html.escape(source, quote=True)}" '
            f'style="{style}" alt="">')


def render_program_pages(program: Program, qr_url: str | None, *, group_banner: str | None = None) -> list[str]:
    """Render readable, balanced program continuations without dropping tracks."""
    pages: list[str] = []
    weights = [track_print_weight(track) for track in program.tracks]
    chunks = partition_for_print_columns(
        program.tracks, weights, columns=2, column_capacity=TRACK_COLUMN_LINE_CAPACITY,
    )
    for page_number, tracks in enumerate(chunks, start=1):
        continuation = f" <span class=\"continuation\">continued — page {page_number}</span>" if page_number > 1 else ""
        # A collection page must stand on its own when printed, including an
        # overflow page separated from the first page of its program.
        banner = (f'<div class="collection-group-banner"><span>COLLECTION GROUP</span>'
                  f' · {html.escape(display_capitalization(group_banner))}</div>') if group_banner else ""
        chunk_weights = [track_print_weight(track) for track in tracks]
        columns = split_print_columns(tracks, chunk_weights, 2)
        listing = "".join(f'<ul class="track-list">{"".join(render_track(track) for track in column)}</ul>' for column in columns)
        artwork = render_continuation_artwork(program, page_number, len(chunks))
        pages.append(f'''<section class="catalog-page program-page">{banner}<header class="program-heading"><span class="code">{program.code}</span><span class="eyebrow">{program.kind}</span><h2>{html.escape(display_capitalization(program.title))}{continuation}</h2></header><div class="track-columns">{listing}</div>{artwork}</section>''')
    return pages


def render_program_page(program: Program, qr_url: str | None) -> str:
    """Compatibility helper for callers rendering a known one-page program."""
    return render_program_pages(program, qr_url)[0]


def render_artist_directory_pages(rows: list[dict[str, Any]], artist_qr_url: str | None) -> list[str]:
    """Keep every genre together and make any continuation self-explanatory."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("genre_slug") == "tv_themes" or str(row.get("genre_name", "")).casefold() == "tv themes":
            continue
        grouped[row["genre_name"]].append(row)
    pages: list[str] = []
    for genre in sorted(grouped):
        artists = sorted(grouped[genre], key=lambda row: row["artist_name"].casefold())
        chunks = partition_for_print_columns(
            artists, [artist_print_weight(artist) for artist in artists],
            columns=3, column_capacity=ARTIST_COLUMN_LINE_CAPACITY,
        )
        for number, chunk in enumerate(chunks, start=1):
            continuation = f' <span class="continuation">continued — page {number}</span>' if number > 1 else ""
            column_count = min(3, len(chunk))
            columns = []
            for artist_column in split_print_columns(chunk, [artist_print_weight(artist) for artist in chunk], column_count):
                items = "".join(f'<li><span class="artist-code">{html.escape(row.get("code", ""))}</span> {html.escape(display_capitalization(row["artist_name"]))} <span>{row["genre_track_count"]} eligible tracks</span></li>' for row in artist_column)
                columns.append(f'<ul class="artist-list">{items}</ul>')
            pages.append(f'<section class="catalog-page artist-directory"><header class="program-heading"><span class="eyebrow">Artist Spotlight directory</span><h2>{html.escape(display_capitalization(genre))}{continuation}</h2></header><div class="artist-columns">{"".join(columns)}</div></section>')
    return pages


def render_toc_section(title: str, programs: list[Program]) -> str:
    entries = "".join(f'<li><span class="toc-code">{program.code}</span> {html.escape(display_capitalization(program.title))}</li>' for program in programs)
    return f'<section class="toc-section"><h3>{title}</h3><ol>{entries}</ol></section>'


def render_toc_page(title: str, programs: list[Program], note: str, page_number: int = 1) -> str:
    midpoint = math.ceil(len(programs) / 2)
    left, right = programs[:midpoint], programs[midpoint:]
    continuation = f' <span class="continuation">continued — page {page_number}</span>' if page_number > 1 else ""
    return f'<section class="catalog-page toc"><h2>{title}{continuation}</h2><p class="toc-intro">{note}</p><div class="toc-columns">{render_toc_section(title, left)}{render_toc_section(title, right)}</div></section>'


def render_toc_pages(title: str, programs: list[Program], note: str, maximum: int) -> list[str]:
    return [render_toc_page(title, programs[index:index + maximum], note, page_number)
            for page_number, index in enumerate(range(0, len(programs), maximum), start=1)]


def plan_grouped_toc_pages(nostalgia: list[Program], groups: list[CollectionGroup], *, maximum: int = TOC_ITEMS_PER_PAGE) -> list[list[TocBlock]]:
    """Pack the ordered TOC sections without stranding Artist Spotlight."""
    blocks = [TocBlock("Nostalgia", tuple(nostalgia))]
    blocks.extend(TocBlock(group.name, group.collections) for group in groups)
    blocks.append(TocBlock("Artist Spotlight", detail="Directory organized by genre, with eligible track counts."))
    pages: list[list[TocBlock]] = [[]]
    seen_titles: set[str] = set()
    used = 0
    for block in blocks:
        entries = list(block.entries)
        while entries:
            available = maximum - used
            if available < 2:  # preserve a heading and its first entry
                pages.append([])
                used = 0
                available = maximum
            take = min(len(entries), available - 1)
            # ``continuation`` describes this rendered fragment, not whether
            # another fragment follows it. The first appearance keeps the
            # normal name; every later appearance says "continued".
            pages[-1].append(TocBlock(block.title, tuple(entries[:take]), continuation=block.title in seen_titles))
            seen_titles.add(block.title)
            used += take + 1
            entries = entries[take:]
            if entries:
                pages.append([])
                used = 0
        if not block.entries:
            if used >= maximum:
                pages.append([])
                used = 0
            pages[-1].append(block)
            used += 1
    return [page for page in pages if page]


def render_grouped_toc_block(block: TocBlock) -> str:
    continuation = ' <span class="continuation">continued</span>' if block.continuation else ""
    entries = "".join(f'<li><span class="toc-code">{program.code}</span> {html.escape(display_capitalization(program.title))}</li>' for program in block.entries)
    detail = f'<p>{html.escape(block.detail)}</p>' if block.detail else ""
    listing = f'<ol>{entries}</ol>' if entries else ""
    return f'<section class="toc-section"><h3>{html.escape(display_capitalization(block.title))}{continuation}</h3>{detail}{listing}</section>'


def render_grouped_toc_pages(nostalgia: list[Program], groups: list[CollectionGroup], *, maximum: int = TOC_ITEMS_PER_PAGE) -> list[str]:
    pages = plan_grouped_toc_pages(nostalgia, groups, maximum=maximum)
    rendered: list[str] = []
    for page_number, page in enumerate(pages):
        # The opening 64-program Nostalgia index is intentionally split into
        # equal columns.  CSS column flow cannot do this while keeping a
        # section heading attached to its list.
        if (page_number == 0 and len(page) == 1 and page[0].title == "Nostalgia"
                and len(page[0].entries) > 1):
            midpoint = math.ceil(len(page[0].entries) / 2)
            columns = (render_toc_section("Nostalgia Programs", list(page[0].entries[:midpoint]))
                       + render_toc_section("Nostalgia Programs", list(page[0].entries[midpoint:])))
        else:
            columns = "".join(render_grouped_toc_block(block) for block in page)
        rendered.append(f'<section class="catalog-page toc"><h2>Table of Contents</h2><p class="toc-intro">Permanent program codes for quick printed selection.</p><div class="toc-columns">{columns}</div></section>')
    return rendered


def render_artwork_divider(
    title: str,
    detail: str,
    artwork_filename: str,
    *,
    eyebrow: str,
) -> str:
    """Render the shared right-aligned treatment for illustrated dividers."""
    artwork = f"{ARTWORK_URL}/{artwork_filename}"
    icon = (f'<img class="divider-brand-icon" src="{html.escape(f"{ARTWORK_URL}/{DIVIDER_BRAND_ARTWORK}", quote=True)}" '
            f'alt="TopSpot40 — Old Dog, New Tracks">')
    return (f'<section class="catalog-page divider artwork-divider">'
            f'<img class="divider-art" src="{html.escape(artwork, quote=True)}" alt="">'
            f'<div class="divider-copy"><p class="divider-eyebrow">{html.escape(eyebrow)}</p>'
            f'<h1>{html.escape(title)}</h1><p>{html.escape(detail)}</p>{icon}</div></section>')


def append_recto_divider(pages: list[str], divider: str) -> None:
    """Start dividers on an odd (right-hand) page for long-edge duplex output."""
    if len(pages) % 2:
        pages.append('<section class="catalog-page duplex-blank" aria-label="Intentionally blank for duplex section alignment"></section>')
    pages.append(divider)


def add_page_footers(pages: list[str], generated: str) -> list[str]:
    """Use explicit folios: Chromium's page counter can otherwise emit Page 0."""
    rendered: list[str] = []
    for number, page in enumerate(pages, start=1):
        # The closing reflection is deliberately unnumbered.  Keep this as a
        # page-level opt-out so the normal sequential folio logic remains the
        # single source of truth for every other page.
        if "closing-conclusion" in page:
            rendered.append(page)
            continue
        start, closing, end = page.rpartition("</section>")
        rendered.append(f'{start}<footer class="folio">TopSpot40 · {generated} · Page {number}</footer>{closing}{end}')
    return rendered


def render_instructions_page() -> str:
    """The fixed opening instructions and approved founder note share page two."""
    return '''<section class="catalog-page instructions"><h2>Using This Catalog</h2><p><strong>N-xxx</strong> identifies a Nostalgia program by decade and genre. <strong>C-xxx</strong> identifies a themed Collection. These permanent program codes stay with their programs across future editions.</p><p>Residents choose music with the printed track rank shown beside each song. For example, <strong>N-001 / #27</strong> means track 27 in Nostalgia program N-001.</p><p class="print-note">For left coil binding: print double-sided, flip on the long edge. The wider inside margin alternates by page and is kept clear of all track text.</p><section class="founder-note"><h3>Why We Created TopSpot40</h3><p>I grew up on a farm, milking cows while listening to the radio and enjoying stories about the songs and artists. On the school bus, Beatles songs helped pass the time. Later, Casey Kasem’s <em>American Top 40</em> deepened my appreciation for the rankings and stories that made music even more memorable.</p><p>My wife, Patty, grew up along the Mexican border. She is fluent in Spanish and Portuguese and has always appreciated the many cultures of the world. Her influence is an important reason TopSpot40 includes English, Spanish, and Brazilian Portuguese.</p><p>Music has a remarkable way of bringing back the people, places, and moments of our lives. We created TopSpot40 to help others rediscover those memories—and make a few new ones along the way.</p><p class="founder-signature">— Gary Steele, Founder of TopSpot40</p><blockquote><strong>Patty’s Rule</strong><br>If a feature is too complicated to enjoy, it probably needs to be simplified.</blockquote></section></section>'''


def render_artist_spotlight_instruction_pages() -> list[str]:
    """Large-print, print-native orientation pages preceding the directory."""
    return [
        '''<section class="catalog-page artist-guide artist-guide-directory"><h1>How Artist Spotlight Works</h1><p class="artist-guide-lead">Artist Spotlight brings an artist&rsquo;s story and available TopSpot40 tracks together in one guided experience. Browse the directory by artist category, alphabetical group, or musical genre, then select an artist to open that artist&rsquo;s Spotlight page.</p><div class="artist-category-grid"><article><h2>Featured Artists</h2><p>Artists with an extended TopSpot40 Artist Story and a multi-track Spotlight program.</p></article><article><h2>Other Artists</h2><p>Artists with multiple eligible TopSpot40 tracks collected into an Artist Spotlight program.</p></article><article><h2>Single Track Artists</h2><p>Artists currently represented by one eligible track in the TopSpot40 library.</p></article></div><p class="artist-count-note">The number shown beside an artist is the number of eligible TopSpot40 tracks currently available for that artist.</p><section class="directory-diagram" aria-label="Simplified Artist Spotlight Directory example"><h2>Browse the Directory</h2><div class="directory-controls"><div><span class="callout">1</span><strong>Artist category</strong><p>Featured Artists &nbsp; Other Artists &nbsp; Single Track Artists</p></div><div><span class="callout">2</span><strong>Alphabetical group</strong><p>A&ndash;C &nbsp; D&ndash;G &nbsp; H&ndash;M &nbsp; N&ndash;S &nbsp; T&ndash;Z</p></div><div><span class="callout">3</span><strong>Genre</strong><p>Country &nbsp; Pop &nbsp; Rock &nbsp; Folk Acoustic</p></div><div class="sample-artist"><span class="callout">4</span><strong>Sample Artist</strong><span>5 eligible tracks</span></div></div></section></section>''',
        '''<section class="catalog-page artist-guide artist-guide-listen"><h1>Two Ways to Enjoy a Featured Artist</h1><div class="artist-two-ways"><article><h2>1. Listen to the Artist Story</h2><p>Featured Artists include an extended narrated Artist Story, generally 5&ndash;10 minutes long. The story explores the artist&rsquo;s life, career, musical influence, memorable moments, and the background behind the music. Select <strong>Play Artist Story</strong> to enjoy the biography separately.</p><div class="spotlight-diagram" aria-label="Simplified Artist Spotlight page"><p class="diagram-title">Featured Artist</p><p class="diagram-subtitle">Artist Story and eligible tracks</p><div class="diagram-buttons"><span>1 &nbsp; Play Artist Story</span><span>2 &nbsp; Start Artist Spotlight</span></div></div></article><article><h2>2. Start the Artist Spotlight</h2><p>Select <strong>Start Artist Spotlight</strong> to open Car Mode and enjoy all eligible TopSpot40 tracks for that artist. Car Mode organizes the artist&rsquo;s available tracks into one listening experience and provides large, easy-to-use playback controls.</p><p class="controls-intro">The principal controls are <strong>Guided Play</strong>, <strong>Auto Play</strong> where available, <strong>Previous</strong>, <strong>Next</strong>, <strong>More Info</strong>, and <strong>Track List</strong>.</p><div class="car-mode-diagram" aria-label="Simplified Car Mode controls"><p class="diagram-title">Car Mode</p><div class="primary-controls"><span>Previous</span><span>Guided Play</span><span>Auto Play</span><span>Next</span></div><div class="secondary-controls"><span>More Info</span><span>Track List</span></div></div></article></div><p class="artist-spotify-note">TopSpot40 provides narration, program organization, and the guided experience. Spotify opens separately for recorded music.</p></section>''',
    ]


def docuseries_summary(story: DocuseriesStory) -> str:
    """Provide a conservative original synopsis without inventing details.

    The live catalog currently has reviewed English narration for every story
    but not uniformly populated short descriptions.  This wording is based on
    the verified story title and the existence of that narration; it avoids
    asserting people, dates, or conclusions that are not structured metadata.
    """
    if story.short_description:
        return story.short_description.strip()
    if not story.story_text.strip():
        return f"A narrated TopSpot40 story introducing {story.title} through the verified music history and cultural context associated with its subject."
    return f"A narrated TopSpot40 story examining {story.title} through the music history, people, events, and cultural context documented in its English program."


def format_docuseries_runtime(duration_seconds: int | None) -> str | None:
    """Format only stored runtimes; never estimate or invent a duration."""
    if duration_seconds is None or duration_seconds <= 0:
        return None
    minutes, seconds = divmod(duration_seconds, 60)
    if seconds:
        return f"{minutes} min {seconds:02d} sec"
    return f"{minutes} min"


def docuseries_print_weight(story: DocuseriesStory) -> float:
    summary = docuseries_summary(story)
    # Cards use a 12pt body beneath a 16pt title; use a deliberately
    # conservative estimate so the protected folio area stays clear.
    return (estimated_print_lines(story.title, characters_per_line=43)
            + estimated_print_lines(summary, characters_per_line=55) + 1.25)


def render_docuseries_opener() -> str:
    return '''<section class="catalog-page docuseries docuseries-opener"><p class="docuseries-eyebrow">TOPSPOT40 NARRATED STORIES</p><h1>Music<br>Docuseries</h1><p class="docuseries-lead">Discover the stories behind the music. These narrated programs explore the people, events, innovations, mysteries, and cultural movements that shaped music history. Each story generally runs between 6 and 12 minutes and contains no music tracks.</p><section class="docuseries-distinction"><h2>A Different Kind of Discovery</h2><p>Music Docuseries are stand-alone narrated stories. They are not ranked programs and they are not music-track collections.</p></section></section>'''


def render_docuseries_group_pages(group: DocuseriesGroup) -> list[str]:
    """Render a group on fresh pages, retaining its identity on continuations."""
    weights = [docuseries_print_weight(story) for story in group.stories]
    chunks = partition_for_print_columns(
        group.stories, weights, columns=2, column_capacity=DOCUSERIES_COLUMN_LINE_CAPACITY,
    )
    pages: list[str] = []
    for number, stories in enumerate(chunks, start=1):
        continuation = " <span class=\"continuation\">continued</span>" if number > 1 else ""
        detail = ('<p class="docuseries-group-note">Stories generally run 6&ndash;12 minutes. '
                  'Each selection is a stand-alone narrated story.</p>') if number == 1 else ""
        columns = split_print_columns(
            list(stories), [docuseries_print_weight(story) for story in stories], 2,
        )
        rendered_columns = []
        for column in columns:
            cards = []
            for story in column:
                runtime = format_docuseries_runtime(story.duration_seconds)
                runtime_html = f'<p class="docuseries-runtime">Runtime: {html.escape(runtime)}</p>' if runtime else ""
                cards.append(
                    f'<article class="docuseries-story" data-docuseries-slug="{html.escape(story.slug, quote=True)}">'
                    f'<h3><span class="docuseries-code">{html.escape(story.code)}</span> {html.escape(story.title)}</h3><p>{html.escape(docuseries_summary(story))}</p>{runtime_html}</article>'
                )
            rendered_columns.append(f'<div class="docuseries-column">{"".join(cards)}</div>')
        pages.append(
            f'<section class="catalog-page docuseries docuseries-group" data-docuseries-group="{html.escape(group.slug, quote=True)}">'
            f'<header class="docuseries-heading"><span class="eyebrow">Music Docuseries</span>'
            f'<h2>{html.escape(group.name)}{continuation}</h2>{detail}</header>'
            f'<div class="docuseries-columns">{"".join(rendered_columns)}</div></section>'
        )
    return pages


def render_docuseries_pages(groups: list[DocuseriesGroup]) -> list[str]:
    """Create the opener followed by all application-ordered groups."""
    if not groups:
        return []
    pages = [render_docuseries_opener()]
    for group in groups:
        pages.extend(render_docuseries_group_pages(group))
    return pages


def render_closing_conclusion() -> str:
    """Warm, unnumbered final page for the printed catalog."""
    logo = f'{ARTWORK_URL}/topspot40-old-dog-new-tracks-icon.png'
    return f'''<section class="catalog-page closing-conclusion"><div class="back-cover-frame"><span class="back-cover-corner corner-top-left" aria-hidden="true">❦</span><span class="back-cover-corner corner-top-right" aria-hidden="true">❦</span><span class="back-cover-corner corner-bottom-left" aria-hidden="true">❦</span><span class="back-cover-corner corner-bottom-right" aria-hidden="true">❦</span><div class="closing-copy back-cover-upper"><p class="closing-eyebrow">TOPSPOT40</p><h1>Every Song Holds a Story and a Memory</h1><p>A song can do something remarkable. In only a few notes, it can carry us across decades—to a childhood home, a school dance, a family celebration, a favorite vacation, or an evening spent with someone we loved.</p><p>Music is more than entertainment. It is part of how we remember our lives. Songs become connected to people, places, and moments, often remaining familiar long after many other details have faded. A melody can lift the spirit, encourage conversation, invite movement, and bring people together through a shared experience.</p><p>That is especially important in senior living communities. Music can help residents reconnect with meaningful memories and with one another. A familiar song may inspire someone to tell a story, sing along, tap a foot, or simply smile. Even when people come from different backgrounds or generations, music gives them something they can enjoy together.</p><p>TopSpot40 was created to make those connections easier. Its programs offer more than playlists. Narrated introductions, artist stories, historical context, and carefully organized music help turn listening into an experience. Residents can revisit the sounds of their own generation, discover the stories behind familiar recordings, explore musical traditions from around the world, or hear something entirely new.</p><p>There is no single correct way to enjoy music. Some listeners may prefer a complete guided program. Others may want to select a favorite artist, collection, decade, or genre. Radio Mode allows listeners to create a more personal and continually changing experience. Every choice offers another opportunity to remember, discover, and connect.</p><p>This catalog contains hundreds of programs, thousands of songs, and stories drawn from many decades of musical history. Yet its real value is not measured by the number of selections it contains. Its value is found in the moments those selections create: a memory recalled, a story shared, a room singing together, or one person feeling a little less alone.</p></div><div class="back-cover-lower"><blockquote class="closing-pullquote">Music accompanies us throughout our lives—and often, it stays with us when little else can.</blockquote><div class="closing-ornament" aria-hidden="true">&#9835;</div><p class="closing-thanks">Thank you for listening.</p><p class="closing-signature"><strong>TopSpot40</strong><br>Music, memories, and the stories that connect us.</p><img class="closing-brand-icon" src="{html.escape(logo, quote=True)}" alt="TopSpot40 — Old Dog, New Tracks"><div class="back-cover-staff" aria-hidden="true">♫&nbsp;&nbsp;♩&nbsp;&nbsp;♪&nbsp;&nbsp;♬&nbsp;&nbsp;♫</div></div></div></section>'''


def render_discovery_pages() -> list[str]:
    """Print adaptation of the approved public Discovery Guide."""
    # Narration: 1950s Pop, #2 “Don't Be Cruel” (ranking 2390, track 844,
    # artist 514), with approved en/es/pt-BR records from the catalog DB.
    return [
        '''<section class="catalog-page discovery discovery-overview"><p class="discovery-eyebrow">Music Discovery Through the Decades</p><h1>TopSpot40<br>Discovery Guide</h1><p class="discovery-lead">Discover more than 4,400 songs, 64 Nostalgia programs, 52 curated Collections, and almost 2,000 artists through music history, featured stories, and guided listening experiences.</p><section class="discovery-panel"><h2>TopSpot40 at a Glance</h2><p>TopSpot40 brings ranked music programs, stories, artist biographies, music history, curated collections, and guided discovery together. It is designed for discovering music and the context surrounding it—not as a music-streaming service.</p><ul class="discovery-figures"><li>More than 4,400 songs</li><li>64 Nostalgia programs</li><li>52 curated Collections</li><li>Almost 2,000 artists</li><li>English, Spanish, and Brazilian Portuguese</li></ul></section></section>''',
        '''<section class="catalog-page discovery discovery-how"><h1>How to Use TopSpot40</h1><div class="how-layout"><ol class="how-steps"><li>Find a program in this printed catalog.</li><li>Use its permanent <strong>N-xxx</strong> or <strong>C-xxx</strong> program code.</li><li>Open TopSpot40 on a phone, tablet, laptop, or desktop computer.</li><li>Select English, Spanish, or Brazilian Portuguese.</li><li>Choose <strong>Guided Play</strong> to move through the program with introductions, song information, music history, and artist stories.</li><li><strong>Auto Play</strong> is available on desktop and laptop computers.</li><li>Printed ranking numbers make it easy for a listener or activity leader to request a particular selection.</li></ol></div><div class="experience-list"><p><strong>Nostalgia Programs</strong> — Ranked music organized by decade and genre.</p><p><strong>Curated Collections</strong> — Themed programs created around particular interests, occasions, and musical traditions.</p><p><strong>Artist Spotlights</strong> — Artist directories showing eligible tracks and related program material.</p><p><strong>Music History and Stories</strong> — Narrated context surrounding the songs, recordings, performers, and their times.</p></div><aside class="spotify-notice"><h3>Spotify Notice</h3><p>TopSpot40 is an independent music-discovery and narration service. It is not affiliated with, sponsored by, endorsed by, or operated by Spotify. TopSpot40 does not provide or stream recorded music. When a user chooses to hear a song, Spotify opens separately, and use of Spotify is governed by Spotify’s own terms, account requirements, availability, and subscription conditions. Spotify is a trademark of Spotify AB.</p><p>Song availability, advertisements, playback behavior, and timing may vary by device, region, and Spotify account type.</p></aside></section>''',
        '''<section class="catalog-page discovery discovery-parts"><h1>Three Parts of Every Guided Experience</h1><p class="discovery-intro">1950s Pop — #2 “Don’t Be Cruel” by Elvis Presley</p><div class="narration-samples"><article><h2>1. Program Introduction</h2><p class="sample-source">Approved 1950s Pop introduction</p><blockquote>“Elvis Presley’s ‘Don’t Be Cruel’ soared to #2 in the 1950s pop charts, a gem from ‘Elvis 30 #1 Hits’ that still captivates listeners.”</blockquote></article><article><h2>2. Track Detail</h2><p class="sample-source">Approved track detail for “Don’t Be Cruel”</p><blockquote>“Elvis Presley’s ‘Don’t Be Cruel’ was recorded in a marathon session at RCA’s Studio B in Nashville, with Elvis insisting on multiple takes until he got it just right. The song’s infectious beat and playful lyrics made it an instant hit…”</blockquote></article><article><h2>3. Artist Biography</h2><p class="sample-source">Approved Elvis Presley artist biography</p><blockquote>“Elvis Presley, often referred to as the ‘King of Rock and Roll,’ revolutionized music with his dynamic performances and unique blend of genres, including rockabilly, pop, and gospel…”</blockquote></article></div><p class="sample-note">Narration samples are abbreviated for print. Complete introductions, track stories, and artist biographies are available through TopSpot40.</p></section>''',
        '''<section class="catalog-page discovery discovery-languages"><h1>One Experience, Three Languages</h1><p class="discovery-intro">1950s Pop — #2 “Don’t Be Cruel” by Elvis Presley<br><span>Track Detail</span></p><div class="language-samples"><article><h2>English</h2><blockquote>“Elvis Presley’s ‘Don’t Be Cruel’ was recorded in a marathon session at RCA’s Studio B in Nashville, with Elvis insisting on multiple takes until he got it just right…”</blockquote></article><article><h2>Español</h2><blockquote>“‘Don’t Be Cruel’ suplica por un trato más amable. Esta canción explica que no hay que ser cruel con un corazón que es verdadero…”</blockquote></article><article><h2>Português do Brasil</h2><blockquote>“‘Don’t Be Cruel’ suplica por um tratamento mais amável. Essa música explica que não se deve ser cruel com um coração que é verdadeiro…”</blockquote></article></div><p class="language-explainer">Choose your preferred language before beginning. TopSpot40’s guided introductions, track stories, and artist biographies are available in English, Spanish, and Brazilian Portuguese when narration has been prepared for that program.</p><p class="sample-note">Samples are abbreviated for print.</p></section>''',
    ]


def render_quick_reference_pages(programs: list[Program], artist_rows: list[dict[str, Any]], docuseries_groups: list[DocuseriesGroup]) -> list[str]:
    """Large-print guide that lists every permanent program code."""
    def pages_for(title: str, entries: list[tuple[str, str]], page_size: int) -> list[str]:
        pages = []
        for number, start in enumerate(range(0, len(entries), page_size), start=1):
            continuation = f' <span class="continuation">continued — page {number}</span>' if number > 1 else ''
            items = ''.join(f'<li><strong>{html.escape(code)}</strong> {html.escape(display_capitalization(name))}</li>' for code, name in entries[start:start + page_size])
            pages.append(f'<section class="catalog-page quick-reference"><header><span class="eyebrow">Quick Reference Guide</span><h2>{html.escape(title)}{continuation}</h2></header><ul>{items}</ul></section>')
        return pages
    nostalgia = [(program.code, program.title) for program in programs if program.kind == "Nostalgia"]
    collections = [(program.code, program.title) for program in programs if program.kind == "Collection"]
    artists = {row["code"]: row["artist_name"] for row in artist_rows if row.get("code")}
    pages = ['''<section class="catalog-page quick-reference quick-reference-intro"><span class="eyebrow">Quick Reference Guide</span><h1>Permanent Program Numbers</h1><p>Enter these permanent program numbers in TopSpot40 <strong>Program Mode</strong>.</p><section class="radio-mode-guide"><h2>Radio Mode</h2><h3>Create Your Own Personal Radio Station</h3><p>Radio Mode offers a flexible listening experience built around your choices. Select the genres, collections, or artists you want to hear, and TopSpot40 will automatically create a continuing series of varied music sets based on those selections.</p><p>Each set begins with a narrated introduction and provides approximately 12–15 minutes of music before the next set begins.</p><p>Radio Mode is available for Nostalgia, Collections, and Artist Radio. Because every station is personalized and changes as you listen, Radio Mode does not use permanent program numbers.</p></section></section>''']
    pages.extend(pages_for("Nostalgia Programs", nostalgia, 80))
    pages.extend(pages_for("Collections Programs", collections, 80))
    pages.extend(pages_for("Artist Spotlights", sorted(artists.items()), 72))
    doc_pages: list[list[str]] = [[]]
    used = 0
    for group in docuseries_groups:
        block = [f'<li class="reference-group">{html.escape(group.name)}</li>'] + [f'<li><strong>{html.escape(story.code)}</strong> {html.escape(display_capitalization(story.title))}</li>' for story in group.stories]
        if doc_pages[-1] and used + len(block) > 42:
            doc_pages.append([]); used = 0
        doc_pages[-1].extend(block); used += len(block)
    for number, items in enumerate(doc_pages, start=1):
        continuation = f' <span class="continuation">continued — page {number}</span>' if number > 1 else ''
        pages.append(f'<section class="catalog-page quick-reference"><header><span class="eyebrow">Quick Reference Guide</span><h2>Music Docuseries{continuation}</h2></header><ul>{"".join(items)}</ul></section>')
    return pages


def render_quick_reference_html(
    programs: list[Program], *, generated_on: date | None = None,
    artist_rows: list[dict[str, Any]] | None = None,
    docuseries_groups: list[DocuseriesGroup] | None = None,
) -> str:
    """Render the review-only, stand-alone permanent-program-number guide."""
    generated = (generated_on or date.today()).isoformat()
    # Reuse the catalog stylesheet so the companion guide inherits the same
    # print dimensions, large type, and black-and-white-safe treatment.
    catalog_html = render_html([], generated_on=generated_on)
    stylesheet = catalog_html.split("<style>", 1)[1].split("</style>", 1)[0]
    cover = (f'<section class="catalog-page cover quick-reference-cover"><img src="{ARTWORK_URL}/cover-topspot40-color-concept.png" '
             'alt="TopSpot40 — Music, Memories &amp; Moments"><div class="quick-reference-cover-copy">'
             '<p>Quick Reference Guide</p><h1>Permanent Program Numbers<br>and Radio Mode</h1></div></section>')
    pages = [cover, *render_quick_reference_pages(programs, artist_rows or [], docuseries_groups or [])]
    body = "".join(add_page_footers(pages, generated))
    guide_css = '''.quick-reference-cover { padding: 0; } .quick-reference-cover-copy { position: absolute; right: .55in; bottom: .62in; width: 4.9in; padding: .22in .28in; background: rgba(255,255,255,.93); border-left: 6px solid #b48a32; color: #173a5e; } .quick-reference-cover-copy p { margin: 0 0 .06in; font-size: 14pt; font-weight: bold; letter-spacing: .08em; text-transform: uppercase; } .quick-reference-cover-copy h1 { margin: 0; font-size: 25pt; line-height: 1.12; }'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>TopSpot40 Quick Reference Guide</title><style>{stylesheet}{guide_css}</style></head><body>{body}</body></html>'''


def render_html(programs: list[Program], *, generated_on: date | None = None, nostalgia_qr: Callable[[Program], str | None] | None = None, collection_qr: Callable[[Program], str | None] | None = None, artist_qr_url: str | None = None, artist_rows: list[dict[str, Any]] | None = None, docuseries_groups: list[DocuseriesGroup] | None = None) -> str:
    generated = (generated_on or date.today()).isoformat()
    nostalgia = [program for program in programs if program.kind == "Nostalgia"]
    collections = [program for program in programs if program.kind == "Collection"]
    groups, _ungrouped_slugs = collection_groups(collections)
    quick_reference_pages = render_quick_reference_pages(programs, artist_rows or [], docuseries_groups or [])
    pages = [
        '<section class="catalog-page cover"><img src="' + ARTWORK_URL + '/cover-topspot40-color-concept.png" alt="TopSpot40 — Music, Memories &amp; Moments"></section>',
        render_instructions_page(),
        *quick_reference_pages,
        *render_discovery_pages(),
        '<section class="catalog-page toc"><h2>Table of Contents</h2><div class="major-toc">__MAJOR_TOC__</div></section>',
    ]
    toc_index = len(pages) - 1
    current_decade = None
    for program in nostalgia:
        if program.decade != current_decade:
            current_decade = program.decade
            append_recto_divider(pages, render_artwork_divider(
                f"Nostalgia · {current_decade}", "Ranked programs organized by decade and genre.",
                f"nostalgia-{current_decade}.png", eyebrow="Nostalgia programs",
            ))
        pages.extend(render_program_pages(program, None))
    for group in groups:
        artwork = COLLECTION_GROUP_ARTWORK.get(group.slug)
        if artwork:
            append_recto_divider(pages, render_artwork_divider(
                group.name, "Curated themed programs with permanent C-xxx codes.", artwork,
                eyebrow="Collection group",
            ))
        for program in group.collections:
            pages.extend(render_program_pages(
                program,
                None,
                group_banner=group.name,
            ))
    # Pages through the end of the catalog programs are an approved print
    # baseline.  The Artist Spotlight introduction is appended only after
    # that boundary, preserving all preceding page content and folios.
    pages.append('<section class="catalog-page duplex-blank" aria-label="Intentionally blank for Artist Spotlight Directory alignment"></section>')
    append_recto_divider(pages, render_artwork_divider(
        "Artist Spotlight Directory",
        "Discover the stories and music of featured artists.",
        ARTIST_SPOTLIGHT_DIVIDER_ARTWORK,
        eyebrow="Artist Spotlight",
    ))
    pages.extend(render_artist_spotlight_instruction_pages())
    pages.extend(render_artist_directory_pages(artist_rows or [], None))
    # This is intentionally appended after the approved Artist Spotlight
    # directory.  Supplying no groups keeps lightweight unit-test documents
    # independent of database-only Docuseries source rows.
    pages.extend(render_docuseries_pages(docuseries_groups or []))
    if docuseries_groups:
        pages.append(render_closing_conclusion())
    def first_page_containing(marker: str) -> int | None:
        return next((index + 1 for index, page in enumerate(pages) if marker in page), None)
    major_sections = [("Quick Reference Guide", 3), ("Discovery Guide", first_page_containing('class="catalog-page discovery'))]
    if nostalgia:
        major_sections.append(("Nostalgia Programs", first_page_containing('nostalgia-1950s.png')))
    if collections:
        collection_page = first_page_containing('Collection group') or next((index + 1 for index, page in enumerate(pages) if 'catalog-page program-page' in page and '<span class="code">C-' in page), None)
        major_sections.append(("Collections", collection_page))
    major_sections.append(("Artist Spotlight", first_page_containing('Artist Spotlight Directory')))
    if docuseries_groups:
        major_sections.append(("Music Docuseries", first_page_containing('docuseries-opener')))
        major_sections.append(("Every Song Holds a Story and a Memory", first_page_containing('closing-conclusion')))
    major_sections = [(name, number) for name, number in major_sections if number is not None]
    toc_items = "".join(f'<p><strong>{html.escape(name)}</strong><span>{number}</span></p>' for name, number in major_sections)
    pages[toc_index] = pages[toc_index].replace("__MAJOR_TOC__", toc_items)
    body = "".join(add_page_footers(pages, generated))
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>TopSpot40 Master Printed Catalog</title><style>
@page {{ size: letter landscape; margin: 0; }}
* {{ box-sizing: border-box; }} body {{ margin: 0; color: #171717; font-family: Arial, sans-serif; }}
.catalog-page {{ width: 11in; height: 8.5in; overflow: hidden; padding: .42in .48in .44in .78in; position: relative; break-after: page; page-break-after: always; }}
.catalog-page:nth-of-type(even) {{ padding-left: .48in; padding-right: .78in; }} /* alternating inside coil gutter */
.folio {{ position: absolute; bottom: .15in; right: .48in; color: #555; font-size: 9pt; }} .catalog-page:nth-of-type(even) .folio {{ right: .78in; }}
h1 {{ font-size: 38pt; margin: 1.6in 0 .2in; }} h2 {{ margin: .04in 0 .12in; font-size: 24pt; }} h3 {{ margin: .06in 0; }}
.cover {{ padding: 0; background: #1b1305; }} .cover img {{ width: 100%; height: 100%; object-fit: cover; display: block; }} .cover .folio {{ color: white; text-shadow: 0 1px 2px #000; right: .3in; }}
.divider {{ background: #f8f8f6; }} .artwork-divider {{ padding: 0; overflow: hidden; }} .divider-art {{ position: absolute; inset: 0 auto 0 0; width: 100%; height: 100%; object-fit: cover; object-position: left center; }} .artwork-divider .divider-copy {{ position: absolute; z-index: 1; top: 1.8in; right: .68in; width: 3.65in; text-align: right; }} .artwork-divider .divider-copy h1 {{ margin: .08in 0 .18in; font-size: 34pt; line-height: 1.04; color: #173a5e; text-align: right; }} .artwork-divider .divider-copy p {{ font-size: 15pt; line-height: 1.3; text-align: right; }} .artwork-divider .divider-eyebrow {{ color: #555; font-size: 10pt !important; font-weight: bold; letter-spacing: .1em; text-transform: uppercase; text-align: right; }} .artwork-divider .divider-brand-icon {{ display: block; width: 1.7in; height: auto; margin: .24in 0 0 auto; }} .artwork-divider .folio {{ right: .62in; }} .duplex-blank {{ background: white; }} .code {{ font-weight: bold; font-size: 18pt; }} .eyebrow {{ margin-left: .15in; color: #555; text-transform: uppercase; font-size: 10pt; }} .continuation {{ color: #555; font-size: 11pt; font-weight: normal; white-space: nowrap; }}
.collection-group-banner {{ background: #173a5e; color: white; font-size: 11pt; font-weight: bold; letter-spacing: .025em; margin: -.42in -.48in .08in -.78in; padding: .07in .78in; }} .collection-group-banner span {{ font-size: 8pt; letter-spacing: .08em; }} .catalog-page:nth-of-type(even) .collection-group-banner {{ margin-left: -.48in; margin-right: -.78in; padding-left: .48in; padding-right: .78in; }}
.program-page, .artist-directory, .toc {{ padding-bottom: .78in; }} .program-heading {{ min-height: .76in; }} .program-page .program-heading, .program-page .track-columns {{ position: relative; z-index: 1; }} .continuation-artwork {{ position: absolute; display: block; object-fit: cover; object-position: center; z-index: 0; }}
.track-columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: .35in; margin-top: .04in; }} .track-list {{ margin: 0; padding: 0; list-style: none; font-size: 12pt; line-height: 1.25; }} .track-list li {{ break-inside: avoid; margin: 0 0 .055in; }} .rank {{ font-weight: bold; }} .song {{ font-weight: bold; }} .artist, .year {{ color: #444; font-weight: normal; }}
.instructions p {{ max-width: 8.7in; font-size: 14pt; line-height: 1.38; }} .print-note {{ border-left: 4px solid #173a5e; padding-left: .15in; }}
.founder-note {{ margin-top: .2in; padding-top: .16in; border-top: 2px solid #b48a32; }} .founder-note h3 {{ color: #173a5e; font-size: 17pt; margin: 0 0 .08in; }} .founder-note p {{ max-width: 8.7in; font-size: 12pt; line-height: 1.28; margin: 0 0 .075in; }} .founder-note .founder-signature {{ font-weight: bold; margin-top: .08in; }} .founder-note blockquote {{ margin: .1in 0 0; padding: .08in .14in; border-left: 4px solid #b48a32; background: #faf6ec; color: #3c3020; font-size: 12pt; line-height: 1.27; }}
.discovery {{ background: #fcfbf8; }} .discovery h1 {{ margin: .05in 0 .16in; color: #173a5e; font-size: 36pt; line-height: 1.03; }} .discovery h2 {{ color: #173a5e; font-size: 19pt; }} .discovery h3 {{ color: #173a5e; font-size: 14pt; }} .discovery p, .discovery li {{ font-size: 12.5pt; line-height: 1.34; }} .discovery-eyebrow {{ margin: .06in 0 .14in; color: #8a681f; font-size: 11pt !important; font-weight: bold; letter-spacing: .12em; text-transform: uppercase; }} .discovery-lead {{ max-width: 7.7in; font-size: 17pt !important; line-height: 1.35 !important; }} .discovery-panel {{ margin-top: .34in; max-width: 8.7in; padding: .22in .26in; border-top: 4px solid #b48a32; background: white; box-shadow: 0 1px 5px #ddd; }} .discovery-panel h2 {{ margin: 0 0 .08in; }} .discovery-figures {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: .09in; margin: .18in 0 0; padding: 0; list-style: none; }} .discovery-figures li {{ display: flex; align-items: center; justify-content: center; min-height: .8in; padding: .08in; border: 1px solid #c7b27d; background: #f7f3e9; color: #173a5e; font-size: 11pt; font-weight: bold; line-height: 1.18; text-align: center; }}
.discovery-how h1 {{ font-size: 31pt; }} .how-layout {{ display: block; }} .how-steps {{ margin: .04in 0; padding-left: .28in; max-width: 8.7in; }} .how-steps li {{ margin: 0 0 .07in; }} .experience-list {{ columns: 2; column-gap: .3in; margin-top: .08in; border-top: 1px solid #b48a32; padding-top: .08in; }} .experience-list p {{ margin: 0 0 .08in; font-size: 12pt; line-height: 1.28; }} .spotify-notice {{ margin-top: .1in; padding: .1in .14in; border-top: 1px solid #b48a32; color: #444; }} .spotify-notice h3 {{ margin: 0 0 .04in; font-size: 10.5pt; }} .spotify-notice p {{ margin: 0 0 .04in; font-size: 10pt; line-height: 1.23; }}
.discovery-intro {{ margin: -.03in 0 .13in; color: #665c4d; font-size: 12pt !important; }} .discovery-intro span {{ color: #8a681f; font-weight: bold; }} .narration-samples {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: .15in; }} .narration-samples article, .language-samples article {{ padding: .13in .15in; border-top: 3px solid #b48a32; background: white; box-shadow: 0 1px 4px #ddd; }} .narration-samples h2 {{ margin: 0 0 .04in; font-size: 16pt; }} .sample-source {{ color: #665c4d; font-size: 10pt !important; font-weight: bold; }} .narration-samples blockquote, .language-samples blockquote {{ margin: .1in 0 0; font-family: Georgia, serif; font-size: 12pt; line-height: 1.34; }} .sample-note {{ margin-top: .2in; padding-top: .1in; border-top: 1px solid #b48a32; color: #665c4d; font-size: 12pt !important; }} .language-samples {{ display: grid; grid-template-columns: 1fr 1fr; gap: .16in; }} .language-samples article:last-child {{ grid-column: 1 / span 2; }} .language-samples h2 {{ margin: 0; font-size: 17pt; }} .language-explainer {{ margin-top: .18in; font-size: 12pt !important; line-height: 1.3 !important; }}
.toc h2 {{ font-size: 30pt; }} .toc-intro {{ font-size: 14pt; margin: 0 0 .12in; }} .toc-columns {{ columns: 2; column-gap: .45in; }} .toc-section {{ break-inside: avoid; margin: 0 0 .14in; }} .toc-section h3 {{ font-size: 15pt; color: #173a5e; border-bottom: 1px solid #9eb4c7; }} .toc-section ol {{ margin: .05in 0; padding-left: .28in; }} .toc-section li, .toc-section p {{ font-size: 12pt; line-height: 1.3; margin: 0 0 .03in; }} .toc-code {{ display: inline-block; min-width: .52in; font-weight: bold; }} .toc-spotlight {{ column-span: all; }}
.major-toc {{ max-width: 7.6in; margin-top: .32in; }} .major-toc p {{ display: flex; justify-content: space-between; margin: 0; padding: .11in .14in; border-bottom: 1px solid #9eb4c7; font-size: 16pt; line-height: 1.25; }} .major-toc span {{ color: #173a5e; font-weight: bold; }}
.artist-columns {{ display: flex; gap: .34in; margin: .08in 0; }} .artist-list {{ flex: 1; margin: 0; padding-left: .2in; font-size: 12pt; line-height: 1.28; }} .artist-list li {{ break-inside: avoid; margin-bottom: .055in; }} .artist-list span {{ color: #555; }}
.quick-reference {{ background: #fcfcfa; }} .quick-reference h1 {{ margin: .12in 0 .18in; color: #173a5e; font-size: 34pt; }} .quick-reference h2 {{ color: #173a5e; font-size: 24pt; }} .quick-reference p {{ max-width: 8.5in; font-size: 14pt; line-height: 1.35; }} .quick-reference ul {{ columns: 3; column-gap: .28in; margin: .08in 0; padding: 0; list-style: none; }} .quick-reference li {{ break-inside: avoid; margin: 0 0 .045in; font-size: 11.5pt; line-height: 1.18; }} .quick-reference .reference-group {{ column-span: all; margin: .08in 0 .035in; padding-top: .04in; border-bottom: 1px solid #9eb4c7; color: #173a5e; font-size: 12pt; font-weight: bold; }} .radio-mode-guide {{ max-width: 8.8in; margin: .34in 0 0; padding: .2in .26in .18in; border: 2px solid #173a5e; border-left: 7px solid #b48a32; background: #fff; }} .radio-mode-guide h2 {{ margin: 0; color: #173a5e; font-size: 20pt; text-transform: uppercase; letter-spacing: .05em; }} .radio-mode-guide h3 {{ margin: .04in 0 .12in; color: #665c4d; font-size: 16pt; }} .radio-mode-guide p {{ margin: 0 0 .11in; max-width: none; font-size: 13pt; line-height: 1.32; }} .radio-mode-guide p:last-child {{ margin-bottom: 0; }} .artist-code, .docuseries-code {{ display: inline-block; min-width: .54in; font-weight: bold; color: #173a5e; }}
.artist-guide {{ background: #fcfcfa; }} .artist-guide h1 {{ margin: .03in 0 .13in; color: #173a5e; font-size: 30pt; line-height: 1.06; }} .artist-guide h2 {{ color: #173a5e; font-size: 16pt; line-height: 1.12; }} .artist-guide p {{ font-size: 12pt; line-height: 1.3; }} .artist-guide-lead {{ max-width: 9.25in; margin: 0 0 .16in; font-size: 13pt !important; line-height: 1.32 !important; }} .artist-category-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: .13in; }} .artist-category-grid article {{ padding: .12in .14in; border: 1px solid #8fa6b8; border-top: 4px solid #173a5e; background: white; }} .artist-category-grid h2 {{ margin: 0 0 .06in; }} .artist-category-grid p {{ margin: 0; }} .artist-count-note {{ margin: .12in 0; padding: .08in .12in; border-left: 4px solid #b48a32; background: #faf6ec; }} .directory-diagram, .spotlight-diagram, .car-mode-diagram {{ border: 2px solid #173a5e; background: white; }} .directory-diagram {{ padding: .11in .14in; }} .directory-diagram h2 {{ margin: 0 0 .08in; }} .directory-controls {{ display: grid; grid-template-columns: 1fr 1fr; gap: .08in .12in; }} .directory-controls > div {{ min-height: .52in; padding: .07in .1in; border: 1px solid #aebbc5; background: #f7f8f8; }} .directory-controls p {{ margin: .025in 0 0; font-size: 10.5pt; line-height: 1.16; }} .callout {{ display: inline-flex; width: .23in; height: .23in; margin-right: .05in; align-items: center; justify-content: center; border-radius: 50%; background: #173a5e; color: white; font-size: 10pt; font-weight: bold; }} .sample-artist {{ display: flex; align-items: center; gap: .08in; background: #edf1f3 !important; }} .sample-artist > span:last-child {{ margin-left: auto; color: #444; font-size: 10.5pt; }} .artist-two-ways {{ display: grid; grid-template-columns: 1fr 1fr; gap: .22in; }} .artist-two-ways article {{ padding: .1in .13in; border-top: 4px solid #b48a32; background: white; }} .artist-two-ways h2 {{ margin: 0 0 .07in; }} .artist-two-ways p {{ margin: 0 0 .09in; }} .spotlight-diagram, .car-mode-diagram {{ margin-top: .12in; padding: .12in; }} .diagram-title {{ margin: 0 !important; color: #173a5e; font-size: 16pt !important; font-weight: bold; }} .diagram-subtitle {{ color: #555; font-size: 10.5pt !important; }} .diagram-buttons {{ display: grid; gap: .07in; }} .diagram-buttons span, .primary-controls span, .secondary-controls span {{ display: block; padding: .09in; border: 1px solid #173a5e; background: #eef2f4; color: #173a5e; font-size: 11pt; font-weight: bold; text-align: center; }} .controls-intro {{ margin-bottom: .1in !important; }} .primary-controls {{ display: grid; grid-template-columns: 1fr 1fr; gap: .07in; }} .secondary-controls {{ display: grid; grid-template-columns: 1fr 1fr; gap: .07in; margin-top: .07in; }} .artist-spotify-note {{ margin: .13in 0 0; padding-top: .09in; border-top: 1px solid #b48a32; color: #444; font-size: 10.5pt !important; }}
.docuseries {{ background: #fcfcfa; }} .docuseries-opener {{ background: linear-gradient(118deg, #ece9e1 0%, #faf9f5 57%, #ffffff 100%); }} .docuseries-eyebrow {{ margin: .55in 0 .15in; color: #8a681f; font-size: 11pt; font-weight: bold; letter-spacing: .13em; }} .docuseries-opener h1 {{ margin: 0 0 .22in; color: #173a5e; font-size: 42pt; line-height: 1.02; }} .docuseries-lead {{ max-width: 7.7in; font-size: 17pt; line-height: 1.38; }} .docuseries-distinction {{ max-width: 8.2in; margin-top: .35in; padding: .18in .23in; border-left: 5px solid #b48a32; background: white; }} .docuseries-distinction h2 {{ margin: 0 0 .06in; color: #173a5e; font-size: 18pt; }} .docuseries-distinction p {{ margin: 0; font-size: 12.5pt; line-height: 1.32; }} .docuseries-group {{ padding-bottom: .78in; }} .docuseries-heading {{ min-height: .94in; border-bottom: 2px solid #b48a32; }} .docuseries-heading h2 {{ margin: .04in 0 .06in; color: #173a5e; font-size: 25pt; line-height: 1.08; }} .docuseries-group-note {{ margin: 0 0 .09in; color: #555; font-size: 11pt; line-height: 1.25; }} .docuseries-columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: .32in; margin-top: .11in; }} .docuseries-story {{ break-inside: avoid; margin: 0 0 .14in; padding: 0 0 .11in; border-bottom: 1px solid #c9c4b8; }} .docuseries-story h3 {{ margin: 0 0 .045in; color: #173a5e; font-size: 16pt; line-height: 1.17; }} .docuseries-story p {{ margin: 0; font-size: 12pt; line-height: 1.3; }} .docuseries-runtime {{ margin-top: .045in !important; color: #665c4d; font-size: 10.5pt !important; font-weight: bold; }}
.closing-conclusion {{ padding: .25in .3in; background: #f5f0e3; }} .back-cover-frame {{ position: relative; display: flex; flex-direction: column; width: 100%; height: 100%; overflow: hidden; border: 3px double #173a5e; outline: 1px solid #b48a32; outline-offset: 3px; background: #f5f0e3; }} .back-cover-corner {{ position: absolute; z-index: 2; color: #b48a32; font-family: Georgia, serif; font-size: 18pt; line-height: 1; }} .corner-top-left {{ top: .08in; left: .12in; }} .corner-top-right {{ top: .08in; right: .12in; transform: scaleX(-1); }} .corner-bottom-left {{ bottom: .08in; left: .12in; transform: scaleY(-1); }} .corner-bottom-right {{ bottom: .08in; right: .12in; transform: scale(-1); }} .closing-copy {{ max-width: none; text-align: left; }} .back-cover-upper {{ flex: 0 0 65%; padding: .24in .43in .12in; background: #f5f0e3; }} .closing-eyebrow {{ margin: 0 0 .055in; color: #a37a24; font-size: 11pt; font-weight: bold; letter-spacing: .14em; }} .closing-conclusion h1 {{ margin: 0 0 .11in; color: #173a5e; font-size: 26pt; line-height: 1.08; }} .closing-conclusion p {{ margin: 0 0 .065in; color: #292929; font-family: Georgia, serif; font-size: 11.1pt; line-height: 1.2; }} .back-cover-lower {{ position: relative; flex: 1 1 auto; overflow: hidden; padding: .12in .42in .08in; border-top: 2px solid #b48a32; background: #173a5e; color: #fff8e8; text-align: center; }} .closing-pullquote {{ position: relative; z-index: 1; max-width: 7.8in; margin: 0 auto .025in; padding: .055in .2in; border-top: 1px solid #d6b55d; border-bottom: 1px solid #d6b55d; color: #fff8e8; font-family: Georgia, serif; font-size: 14pt; font-style: italic; line-height: 1.2; text-align: center; }} .closing-ornament {{ position: relative; z-index: 1; margin: .01in auto; color: #d6b55d; font-family: Georgia, serif; font-size: 18pt; line-height: 1; text-align: center; }} .closing-conclusion .closing-thanks {{ position: relative; z-index: 1; margin: .025in 0 .04in; color: #fff8e8; font-size: 13.5pt; font-style: italic; font-weight: bold; text-align: center; }} .closing-conclusion .closing-signature {{ position: relative; z-index: 1; margin: 0; color: #fff8e8; font-family: Arial, sans-serif; font-size: 11.2pt; line-height: 1.22; text-align: center; }} .closing-brand-icon {{ position: relative; z-index: 1; display: block; width: .72in; height: auto; margin: .025in auto 0; }} .back-cover-staff {{ position: absolute; z-index: 0; right: 0; bottom: -.12in; left: 0; padding-top: .04in; border-top: 1px solid rgba(214,181,93,.35); color: rgba(214,181,93,.18); font-family: Georgia, serif; font-size: 42pt; letter-spacing: .22in; line-height: .8; text-align: center; }}
@media print {{ html, body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }} .catalog-page {{ break-after: page; page-break-after: always; }} }}
</style></head><body>{body}</body></html>'''


def generate(output: Path, *, nostalgia_url_template: str | None = None, collection_url_template: str | None = None, artist_qr_url: str | None = None, quick_reference_output: Path | None = None) -> Path:
    manifest = load_manifest()
    approved_manifest = load_approved_manifest()
    artist_codes, story_codes = approved_code_maps(approved_manifest)
    with Session(engine) as session:
        programs = load_programs(session, manifest)
        docuseries_groups = load_docuseries_groups(session, story_codes)
    artist_rows = load_artist_spotlight_rows(artist_codes)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(programs, artist_rows=artist_rows, docuseries_groups=docuseries_groups), encoding="utf-8")
    if quick_reference_output is not None:
        quick_reference_output.parent.mkdir(parents=True, exist_ok=True)
        quick_reference_output.write_text(render_quick_reference_html(programs, artist_rows=artist_rows, docuseries_groups=docuseries_groups), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "topspot40_master_print_catalog.html")
    parser.add_argument("--nostalgia-url-template")
    parser.add_argument("--collection-url-template")
    parser.add_argument("--artist-qr-url")
    parser.add_argument("--quick-reference-output", type=Path)
    args = parser.parse_args()
    print(f"Generated: {generate(args.output, nostalgia_url_template=args.nostalgia_url_template, collection_url_template=args.collection_url_template, artist_qr_url=args.artist_qr_url, quick_reference_output=args.quick_reference_output)}")


if __name__ == "__main__":
    main()
