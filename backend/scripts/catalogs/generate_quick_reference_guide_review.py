"""Build the standalone, review-only TopSpot40 Quick Reference Guide.

The permanent-code directory is recovered from the approved phase-three review
guide so this small companion never queries the catalog database or alters the
approved master catalog.
"""
from __future__ import annotations

import argparse
import html
import itertools
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from backend.scripts.catalogs import master_print_catalog as catalog


CATALOG_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = CATALOG_DIR / "output"
APPROVED_DIRECTORY_SOURCE = OUTPUT_DIR / "topspot40_quick_reference_guide_phase3_review.html"
APPROVED_MASTER_SOURCE = OUTPUT_DIR / "topspot40_master_print_catalog_castle_cover_review.html"
DEFAULT_OUTPUT = OUTPUT_DIR / "topspot40_quick_reference_guide_review.html"
EXPECTED_COUNTS = {"N": 64, "C": 52, "A": 226, "D": 127}


def without_footer(page: str) -> str:
    return re.sub(r'<footer class="folio">.*?</footer>', "", page)


def directory_entries(source: str, code_prefix: str) -> list[tuple[str, str]]:
    pattern = rf'<li><strong>({code_prefix}-\d{{3}})</strong>\s*(.*?)</li>'
    return [(code, html.unescape(re.sub(r"<.*?>", "", title)).strip()) for code, title in re.findall(pattern, source)]


def directory_pages(title: str, entries: list[tuple[str, str]], page_size: int) -> list[str]:
    pages: list[str] = []
    for page_number, start in enumerate(range(0, len(entries), page_size), start=1):
        continuation = "" if page_number == 1 else f' <span class="continuation">continued — page {page_number}</span>'
        items = "".join(
            f"<li><strong>{html.escape(code)}</strong> {html.escape(name)}</li>"
            for code, name in entries[start:start + page_size]
        )
        pages.append(
            f'<section class="catalog-page quick-reference"><header><span class="eyebrow">Quick Reference Guide</span>'
            f"<h2>{html.escape(title)}{continuation}</h2></header><ul>{items}</ul></section>"
        )
    return pages


def grouped_directory_page(title: str, groups: list[tuple[str, list[tuple[str, str]]]], *, directory_class: str) -> str:
    """Render one compact, grouped directory page without reducing entry type."""
    blocks = "".join(
        f'<section class="directory-group"><h3>{html.escape(group_name)}</h3><ul>'
        + "".join(
            f"<li><strong>{html.escape(code)}</strong> {html.escape(name)}</li>"
            for code, name in entries
        )
        + "</ul></section>"
        for group_name, entries in groups
    )
    return (
        f'<section class="catalog-page quick-reference grouped-directory {directory_class}"><header>'
        f'<span class="eyebrow">Quick Reference Guide</span><h2>{html.escape(title)}</h2>'
        f'</header><div class="grouped-directory-columns">{blocks}</div></section>'
    )


def grouped_directory_pages(
    title: str,
    groups: list[tuple[str, list[tuple[str, str]]]],
    *,
    directory_class: str,
    page_count: int,
) -> list[str]:
    """Keep named alphabetical groups intact while balancing their page loads."""
    if len(groups) < page_count:
        raise ValueError("There must be at least one directory group per page.")
    weights = [len(entries) + 1 for _heading, entries in groups]
    best_cuts: tuple[int, ...] | None = None
    best_score: tuple[int, int] | None = None
    for cuts in itertools.combinations(range(1, len(groups)), page_count - 1):
        boundaries = (0, *cuts, len(groups))
        loads = [sum(weights[boundaries[index]:boundaries[index + 1]]) for index in range(page_count)]
        score = (max(loads), max(loads) - min(loads))
        if best_score is None or score < best_score:
            best_score, best_cuts = score, cuts
    assert best_cuts is not None
    boundaries = (0, *best_cuts, len(groups))
    pages: list[str] = []
    for page_number in range(page_count):
        heading = title if page_number == 0 else f'{title} <span class="continuation">continued — page {page_number + 1}</span>'
        page_groups = groups[boundaries[page_number]:boundaries[page_number + 1]]
        blocks = "".join(
            f'<section class="directory-group"><h3>{html.escape(group_name)}</h3><ul>'
            + "".join(
                f"<li><strong>{html.escape(code)}</strong> {html.escape(name)}</li>"
                for code, name in entries
            )
            + "</ul></section>"
            for group_name, entries in page_groups
        )
        pages.append(
            f'<section class="catalog-page quick-reference grouped-directory {directory_class}"><header>'
            f'<span class="eyebrow">Quick Reference Guide</span><h2>{heading}</h2>'
            f'</header><div class="grouped-directory-columns">{blocks}</div></section>'
        )
    return pages


def alphabetical_key(entry: tuple[str, str]) -> str:
    """Sort display names alphabetically, ignoring accents and punctuation."""
    return "".join(
        character for character in unicodedata.normalize("NFKD", entry[1])
        if not unicodedata.combining(character) and character.isalnum()
    ).casefold()


def artist_initial(name: str) -> str:
    """Return the display initial used by the artist directory."""
    return name[0].upper()


def artist_groups(entries: list[tuple[str, str]], *, high_volume: int = 18) -> list[tuple[str, list[tuple[str, str]]]]:
    """Build contiguous alphabetical ranges from actual letter volumes.

    Letters with at least ``high_volume`` artists retain their own headings.
    Adjacent smaller letters are combined until they form a comparably useful
    section; a tiny trailing remainder joins its preceding range.
    """
    by_letter: dict[str, list[tuple[str, str]]] = {}
    for entry in entries:
        by_letter.setdefault(artist_initial(entry[1]), []).append(entry)
    letters = list(by_letter)
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    index = 0
    while index < len(letters):
        letter = letters[index]
        if len(by_letter[letter]) >= high_volume:
            groups.append((letter, by_letter[letter]))
            index += 1
            continue
        segment_letters: list[str] = []
        segment_entries: list[tuple[str, str]] = []
        while index < len(letters) and len(by_letter[letters[index]]) < high_volume:
            segment_letters.append(letters[index])
            segment_entries.extend(by_letter[letters[index]])
            index += 1
        range_start = 0
        while range_start < len(segment_letters):
            range_end = range_start
            range_entries: list[tuple[str, str]] = []
            while range_end < len(segment_letters) and len(range_entries) < high_volume:
                range_entries.extend(by_letter[segment_letters[range_end]])
                range_end += 1
            # Do not strand a very small final range. Add it to the prior
            # low-volume range instead, retaining one continuous heading.
            remaining = sum(len(by_letter[item]) for item in segment_letters[range_end:])
            if remaining and remaining < high_volume // 2:
                range_entries.extend(entry for item in segment_letters[range_end:] for entry in by_letter[item])
                range_end = len(segment_letters)
            label_end = segment_letters[range_end - 1]
            label = segment_letters[range_start] if segment_letters[range_start] == label_end else f"{segment_letters[range_start]}–{label_end}"
            groups.append((label, range_entries))
            range_start = range_end
    return groups


def nostalgia_groups(entries: list[tuple[str, str]]) -> list[tuple[str, list[tuple[str, str]]]]:
    groups: dict[str, list[tuple[str, str]]] = {}
    for code, title in entries:
        decade = title.split(" ", 1)[0]
        groups.setdefault(decade, []).append((code, title.split(" ", 1)[1]))
    return list(groups.items())


def collection_groups_from_master(master_html: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Read the approved master HTML's database-authoritative group sequence."""
    pattern = re.compile(
        r'<div class="collection-group-banner"><span>COLLECTION GROUP</span> · (.*?)</div>'
        r'<header class="program-heading"><span class="code">(C-\d{3})</span>.*?<h2>(.*?)</h2>',
        re.DOTALL,
    )
    grouped: dict[str, list[tuple[str, str]]] = {}
    seen_codes: set[str] = set()
    for raw_group, code, raw_title in pattern.findall(master_html):
        # A long collection can have a continuation page, which repeats its
        # banner and heading but must not repeat its permanent C code here.
        if code in seen_codes:
            continue
        seen_codes.add(code)
        group = html.unescape(raw_group).strip()
        title = html.unescape(re.sub(r"<.*?>", "", raw_title)).strip()
        grouped.setdefault(group, []).append((code, title))
    if not grouped:
        raise ValueError("Could not read collection groups from the approved master HTML.")
    return list(grouped.items())


def docuseries_pages(source: str) -> list[str]:
    pages = re.findall(
        r'<section class="catalog-page quick-reference"><header><span class="eyebrow">Quick Reference Guide</span><h2>Music Docuseries.*?</section>',
        source,
    )
    if not pages:
        raise ValueError("The approved guide does not contain Music Docuseries directory pages.")
    return [without_footer(page) for page in pages]


def quick_guide_instructions() -> str:
    return '''<section class="catalog-page instructions quick-guide-instructions"><h1>Using This Catalog</h1><p class="instructions-lead">Choose any program in Program Mode. Program Numbers are optional shortcuts and are not used by Radio Mode.</p><section class="code-guide"><p><strong>N-xxx</strong><span>Nostalgia Program</span></p><p><strong>C-xxx</strong><span>Collection</span></p><p><strong>A-xxx</strong><span>Artist Spotlight</span></p><p><strong>D-xxx</strong><span>Music Docuseries</span></p></section><h2>Two ways to start a program</h2><h3>Browse the menus</h3><ol class="program-steps"><li>Open TopSpot40 and choose Program Mode.</li><li>Choose Nostalgia Programs, Collections Programs, Artist Spotlights, or Music Docuseries.</li><li>Follow the menus to select your program.</li></ol><h3>Use a Program Number shortcut</h3><p class="program-number-shortcut">Choose Enter Program Number under Program Mode and enter the number printed beside the program.</p><p class="quick-guide-note">This Quick Reference Guide contains program numbers only; it does not include song lists or track rankings.</p></section>'''


def cover_page() -> str:
    return f'<section class="catalog-page cover"><img src="{catalog.ARTWORK_URL}/{catalog.FINAL_COVER_ARTWORK}" alt="TopSpot40 — Music, Memories &amp; Moments"></section>'


def approved_stylesheet() -> str:
    master_html = APPROVED_MASTER_SOURCE.read_text(encoding="utf-8")
    return master_html.split("<style>", 1)[1].split("</style>", 1)[0]


def build_html(directory_source: str, *, generated_on: date | None = None) -> str:
    nostalgia = directory_entries(directory_source, "N")
    collections = directory_entries(directory_source, "C")
    artists = sorted(directory_entries(directory_source, "A"), key=alphabetical_key)
    docuseries = directory_entries(directory_source, "D")
    actual_counts = Counter(code[0] for code, _ in [*nostalgia, *collections, *artists, *docuseries])
    if dict(actual_counts) != EXPECTED_COUNTS:
        raise ValueError(f"Unexpected permanent-code counts: {dict(actual_counts)}")
    all_codes = [code for code, _ in [*nostalgia, *collections, *artists, *docuseries]]
    if len(all_codes) != len(set(all_codes)):
        raise ValueError("Each permanent program number must appear exactly once.")
    grouped_artists = artist_groups(artists)
    if [entry for _heading, entries in grouped_artists for entry in entries] != artists:
        raise ValueError("Artist alphabetical groups must retain the complete sorted directory.")
    grouped_collections = collection_groups_from_master(APPROVED_MASTER_SOURCE.read_text(encoding="utf-8"))
    grouped_collection_codes = [code for _group, entries in grouped_collections for code, _title in entries]
    if set(grouped_collection_codes) != {code for code, _title in collections} or len(grouped_collection_codes) != 52:
        raise ValueError("Approved master collection groups do not contain exactly the 52 Quick Guide collections.")

    generated = (generated_on or date.today()).isoformat()
    pages = [
        cover_page(),
        catalog.render_music_enriches_page(),
        quick_guide_instructions(),
        grouped_directory_page("Nostalgia Programs", nostalgia_groups(nostalgia), directory_class="nostalgia-directory"),
        grouped_directory_page("Collections Programs", grouped_collections, directory_class="collections-directory"),
        *grouped_directory_pages("Artist Spotlights", grouped_artists, directory_class="artist-directory", page_count=4),
        *docuseries_pages(directory_source),
        catalog.render_closing_conclusion(),
    ]
    body = "".join(catalog.add_page_footers(pages, generated))
    grouped_directory_css = '''
.grouped-directory .grouped-directory-columns { column-gap: .3in; }
.nostalgia-directory .grouped-directory-columns { columns: 4; }
.collections-directory .grouped-directory-columns { columns: 3; }
.artist-directory .grouped-directory-columns { columns: 3; }
.grouped-directory .directory-group { break-inside: avoid; margin: 0 0 .12in; }
.grouped-directory .directory-group h3 { margin: 0 0 .045in; padding: 0 0 .035in; border-bottom: 1px solid #9eb4c7; color: #173a5e; font-size: 12pt; line-height: 1.1; }
.grouped-directory .directory-group ul { columns: auto; margin: 0; padding: 0; list-style: none; }
.grouped-directory .directory-group li { margin: 0 0 .035in; font-size: 11.5pt; line-height: 1.18; }
'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>TopSpot40 Quick Reference Guide</title><style>{approved_stylesheet()}{grouped_directory_css}</style></head><body>{body}</body></html>'''


def generate(output: Path = DEFAULT_OUTPUT) -> Path:
    source = APPROVED_DIRECTORY_SOURCE.read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(source), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(f"Generated: {generate(args.output)}")


if __name__ == "__main__":
    main()
