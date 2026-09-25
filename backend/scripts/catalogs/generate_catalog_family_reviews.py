"""Generate the five standalone TopSpot40 catalog-family review editions.

All pages are composed from the approved master and Quick Reference review HTML.
No database access or master-catalog mutation is required.  Artist Spotlight
content is the approved Artist Spotlight directory, per the approved scope.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.scripts.catalogs import master_print_catalog as catalog


CATALOG_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = CATALOG_DIR / "output"
MASTER_SOURCE = OUTPUT_DIR / "topspot40_master_print_catalog_castle_cover_review.html"
QUICK_SOURCE = OUTPUT_DIR / "topspot40_quick_reference_guide_review.html"


@dataclass(frozen=True)
class Edition:
    slug: str
    subtitle: str
    codes: tuple[str, ...]
    detailed: tuple[str, ...]
    complete_instructions: bool = False


EDITIONS = (
    Edition("complete_program_guide", "Complete Program Guide", ("N", "C", "A", "D"), ("N", "C", "A", "D"), True),
    Edition("quick_reference_guide_final", "Quick Reference Guide", ("N", "C", "A", "D"), ()),
    Edition("nostalgia_programs", "Nostalgia Programs", ("N",), ("N",)),
    Edition("collections_programs", "Collections Programs", ("C",), ("C",)),
    Edition("artist_spotlights_docuseries", "Artist Spotlights & Music Docuseries", ("A", "D"), ("A", "D")),
)


def page_sections(document: str) -> list[str]:
    """Return outer catalog pages, retaining nested page-local sections."""
    starts = [match.start() for match in re.finditer(r'<section class="catalog-page', document)]
    body_end = document.index("</body></html>")
    return [document[start: starts[index + 1] if index + 1 < len(starts) else body_end] for index, start in enumerate(starts)]


def without_footer(page: str) -> str:
    return re.sub(r'<footer class="folio">.*?</footer>', "", page)


def approved_sources() -> tuple[list[str], list[str], str]:
    master = MASTER_SOURCE.read_text(encoding="utf-8")
    quick = QUICK_SOURCE.read_text(encoding="utf-8")
    stylesheet = quick.split("<style>", 1)[1].split("</style>", 1)[0]
    return [without_footer(page) for page in page_sections(master)], [without_footer(page) for page in page_sections(quick)], stylesheet


def cover(subtitle: str) -> str:
    return (
        '<section class="catalog-page cover family-cover">'
        f'<img src="{catalog.ARTWORK_URL}/{catalog.FINAL_COVER_ARTWORK}" alt="TopSpot40 — Music, Memories &amp; Moments">'
        f'<p class="family-cover-subtitle">{subtitle}</p></section>'
    )


def instructions(codes: tuple[str, ...], *, complete: bool) -> str:
    if complete:
        return catalog.render_instructions_page()
    descriptions = {"N": "Nostalgia Programs", "C": "Collections Programs", "A": "Artist Spotlights", "D": "Music Docuseries"}
    labels = ", ".join(descriptions[code] for code in codes)
    patterns = ", ".join(f"{code}-xxx" for code in codes)
    directory_note = (
        "Use the Quick Reference directory to find a program and its permanent Program Number. "
        "Detailed program listings follow the directory."
    )
    if codes == ("A", "D"):
        directory_note = "Use the Quick Reference directory to find a program and its permanent Program Number. Detailed Music Docuseries listings follow the directory."
    artist_note = (
        "Find an artist in the Artist Spotlight directory and use the permanent A-xxx Program Number as an optional Program Mode shortcut. "
        "You may also browse Artist Spotlights directly from the on-screen Program Mode menus."
        if "A" in codes else ""
    )
    code_boxes = "".join(
        f'<p><strong>{code}-xxx</strong><span>{descriptions[code][:-1] if descriptions[code].endswith("s") else descriptions[code]}</span></p>'
        for code in codes
    )
    artist_html = f'<p class="artist-directory-note">{artist_note}</p>' if artist_note else ""
    return (
        '<section class="catalog-page instructions focused-instructions"><h1>Using This Catalog</h1>'
        '<p class="instructions-lead">Choose a program in Program Mode. Program Numbers are optional shortcuts and are not used by Radio Mode.</p>'
        f'<section class="code-guide">{code_boxes}</section>'
        '<h2>Two ways to start a program</h2><h3>Browse the menus</h3>'
        f'<p>Open TopSpot40, choose Program Mode, and select {labels}.</p>'
        '<h3>Use a Program Number shortcut</h3>'
        f'<p>Choose Enter Program Number under Program Mode and enter the printed {patterns} number.</p>'
        f'<p class="quick-guide-note">{directory_note}</p>'
        f'{artist_html}'
        '</section>'
    )


def quick_directories(quick_pages: list[str], codes: tuple[str, ...]) -> list[str]:
    wanted = {"N": "nostalgia-directory", "C": "collections-directory", "A": "artist-directory", "D": "<h2>Music Docuseries"}
    selected: list[str] = []
    for code in codes:
        marker = wanted[code]
        selected.extend(page for page in quick_pages if marker in page)
    return selected


def first_divider(master_pages: list[str], title: str) -> str:
    """Return an approved visual divider page by its printed title."""
    return next(
        page for page in master_pages
        if 'class="catalog-page divider' in page and f">{title}</h1>" in page
    )


def docuseries_opener(master_pages: list[str]) -> str:
    """Reuse the approved Docuseries opening page as its section divider."""
    return next(page for page in master_pages if 'class="catalog-page docuseries docuseries-opener"' in page)


def artist_featured_by_genre_pages(master_pages: list[str]) -> list[str]:
    """Return the approved Artist guidance and genre-browse pages, in source order."""
    selected: list[str] = []
    for page in master_pages:
        header = page.split(">", 1)[0]
        if "artist-guide" in header or "artist-directory" in header:
            selected.append(page)
    return selected


def detailed_pages(
    master_pages: list[str], types: tuple[str, ...], *, skip_divider_titles: tuple[str, ...] = (), skip_docuseries_opener: bool = False
) -> list[str]:
    pages: list[str] = []
    if "N" in types or "C" in types:
        active: str | None = None
        pending_divider: str | None = None
        for page in master_pages:
            if 'class="catalog-page divider' in page:
                pending_divider = page
                continue
            if 'class="catalog-page program-page"' in page:
                match = re.search(r'<span class="code">([NC])-\d{3}</span>', page)
                if match:
                    active = match.group(1)
                    if (
                        active in types
                        and pending_divider is not None
                        and not any(f">{title}</h1>" in pending_divider for title in skip_divider_titles)
                    ):
                        pages.append(pending_divider)
                    pending_divider = None
                if active in types:
                    pages.append(page)
            elif active and 'class="catalog-page program-page"' not in page:
                active = None
    # Approved scope: the four-page A-code Quick Reference directory is the
    # complete printed Artist Spotlight section. Do not append an extra
    # directory or infer artist-specific song-list pages.
    if "D" in types:
        pages.extend(
            page for page in master_pages
            if 'class="catalog-page docuseries' in page
            and not (skip_docuseries_opener and 'docuseries-opener' in page.split(">", 1)[0])
        )
    return pages


def complete_master_tail(master_pages: list[str]) -> list[str]:
    """Retain the approved full-guide sequence after its opening directories."""
    start = next(index for index, page in enumerate(master_pages) if 'class="catalog-page discovery' in page)
    return [
        page for page in master_pages[start:]
        if "closing-conclusion" not in page
        and 'class="catalog-page artist-directory"' not in page
        and 'class="catalog-page artist-guide"' not in page
    ]


def complete_pre_artist_tail(master_pages: list[str]) -> list[str]:
    """Keep the approved Complete Guide through the end of Collections only.

    Artist and Docuseries material is deliberately assembled afterwards as one
    continuous section, so the directories never become separated from their
    guidance, genre pages, or Docuseries content.
    """
    start = next(index for index, page in enumerate(master_pages) if 'class="catalog-page discovery' in page)
    end = next(index for index, page in enumerate(master_pages) if ">Artist Spotlight Directory</h1>" in page)
    removed = {
        first_divider(master_pages, "Nostalgia · 1950s"),
        first_divider(master_pages, "American Heritage Favorites"),
    }
    return [page for page in master_pages[start:end] if page not in removed]


def sectioned_directories(master_pages: list[str], quick_pages: list[str], codes: tuple[str, ...]) -> list[str]:
    """Place each approved directory directly after its approved section opener."""
    pages: list[str] = []
    dividers = {
        "N": first_divider(master_pages, "Nostalgia · 1950s"),
        "C": first_divider(master_pages, "American Heritage Favorites"),
        "A": first_divider(master_pages, "Artist Spotlight Directory"),
        "D": docuseries_opener(master_pages),
    }
    for code in codes:
        pages.append(dividers[code])
        pages.extend(quick_directories(quick_pages, (code,)))
        if code == "A" and codes == ("A", "D"):
            pages.extend(artist_featured_by_genre_pages(master_pages))
    return pages


def build_edition(edition: Edition, *, generated_on: date | None = None) -> str:
    master_pages, quick_pages, stylesheet = approved_sources()
    generated = (generated_on or date.today()).isoformat()
    pages = [cover(edition.subtitle), catalog.render_music_enriches_page(), instructions(edition.codes, complete=edition.complete_instructions)]
    if edition.slug == "quick_reference_guide_final":
        pages.extend(quick_directories(quick_pages, edition.codes))
    elif edition.slug == "complete_program_guide":
        # The early reference material covers Nostalgia and Collections. The
        # Artist and Docuseries material is appended after all Collections
        # detail pages below, preserving the approved reading sequence.
        pages.extend(sectioned_directories(master_pages, quick_pages, ("N", "C")))
    else:
        pages.extend(sectioned_directories(master_pages, quick_pages, edition.codes))
    if edition.slug == "complete_program_guide":
        pages.extend(complete_pre_artist_tail(master_pages))
        pages.append(first_divider(master_pages, "Artist Spotlight Directory"))
        pages.extend(quick_directories(quick_pages, ("A",)))
        pages.extend(artist_featured_by_genre_pages(master_pages))
        pages.append(docuseries_opener(master_pages))
        pages.extend(quick_directories(quick_pages, ("D",)))
        pages.extend(detailed_pages(master_pages, ("D",), skip_docuseries_opener=True))
    else:
        skip_titles: tuple[str, ...] = ()
        if edition.codes == ("N",):
            skip_titles = ("Nostalgia · 1950s",)
        elif edition.codes == ("C",):
            skip_titles = ("American Heritage Favorites",)
        pages.extend(
            detailed_pages(
                master_pages,
                edition.detailed,
                skip_divider_titles=skip_titles,
                skip_docuseries_opener="D" in edition.detailed,
            )
        )
    pages.append(catalog.render_closing_conclusion())
    body = "".join(catalog.add_page_footers(pages, generated))
    family_css = '''
.family-cover { padding: 0; } .family-cover-subtitle { position: absolute; top: 2.08in; right: 1.15in; left: 1.15in; margin: 0; padding: .08in .18in; background: rgba(10,31,50,.86); color: #fff8e8; font-size: 19pt; font-weight: bold; letter-spacing: .04em; line-height: 1.15; text-align: center; text-transform: uppercase; }
.focused-instructions h3 { margin: .12in 0 .04in; color: #173a5e; font-size: 16pt; }.focused-instructions > p { max-width: 8.5in; margin: 0 0 .1in; font-size: 15pt; line-height: 1.35; }.focused-instructions .quick-guide-note { margin-top: .22in; padding-top: .12in; border-top: 2px solid #b48a32; }
'''
    return f'<!doctype html><html><head><meta charset="utf-8"><title>TopSpot40 — {edition.subtitle}</title><style>{stylesheet}{family_css}</style></head><body>{body}</body></html>'


def generate_all() -> list[Path]:
    paths: list[Path] = []
    for edition in EDITIONS:
        path = OUTPUT_DIR / f"topspot40_{edition.slug}_review.html"
        path.write_text(build_edition(edition), encoding="utf-8")
        paths.append(path)
    return paths


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    for path in generate_all():
        print(f"Generated: {path}")


if __name__ == "__main__":
    main()
