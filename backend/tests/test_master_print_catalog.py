from __future__ import annotations

from copy import deepcopy
from datetime import date
from hashlib import sha256
import re
from unittest.mock import Mock

import pytest
from sqlmodel import Session, select

from backend.scripts.catalogs import master_print_catalog as catalog
from backend.database import engine
from backend.models.collection_models import Collection, CollectionCategory


def sample_program(kind="Nostalgia"):
    return catalog.Program(
        "N-001" if kind == "Nostalgia" else "C-001",
        kind, "1950s country" if kind == "Nostalgia" else "A Collection",
        "1950s-country" if kind == "Nostalgia" else "a_collection",
        decade="1950s" if kind == "Nostalgia" else None,
        genre="country" if kind == "Nostalgia" else None,
        tracks=({"rank": 17, "title": "A Song", "artist": "An Artist", "year": 1958},),
    )


def sample_docuseries_group(*, story_count=2, name="Instruments That Changed Music"):
    stories = tuple(catalog.DocuseriesStory(
        slug=f"story-{number}", title=f"Verified Story {number}",
        story_text="Reviewed English narration source.", duration_seconds=420, code=f"D-{number:03d}",
    ) for number in range(1, story_count + 1))
    return catalog.DocuseriesGroup("musical_instruments", name, stories)


def test_approved_backend_mapping_checksum_counts_and_target_kinds_are_stable():
    approved = catalog.load_approved_manifest()
    assignments = approved["assignments"]
    assert len(assignments) == 469
    assert {prefix: sum(item["code"].startswith(f"{prefix}-") for item in assignments) for prefix in "NCAD"} == {
        "N": 64, "C": 52, "A": 226, "D": 127,
    }
    assert len({item["code"] for item in assignments}) == 469
    artist_codes, story_codes = catalog.approved_code_maps(approved)
    assert len(artist_codes) == 226 and len(story_codes) == 127
    assert all(item["kind"] != "docuseries_group" for item in assignments)
    assert all(item["kind"] != "radio" for item in assignments)


def test_quick_reference_includes_all_supported_code_types_and_no_radio_code():
    artist_rows = [{"code": "A-001", "artist_name": "Artist", "genre_track_count": 3}]
    rendered = "".join(catalog.render_quick_reference_pages(
        [sample_program(), sample_program("Collection")], artist_rows, [sample_docuseries_group()],
    ))
    assert "Quick Reference Guide" in rendered
    assert "N-001" in rendered and "C-001" in rendered and "A-001" in rendered and "D-001" in rendered
    assert "Radio Mode offers a flexible listening experience" in rendered


def test_quick_reference_radio_mode_copy_is_complete_and_uses_no_program_code():
    rendered = "".join(catalog.render_quick_reference_pages(
        [sample_program()], [], [],
    ))
    assert "Create Your Own Personal Radio Station" in rendered
    assert "approximately 12–15 minutes of music" in rendered
    assert "Nostalgia, Collections, and Artist Radio" in rendered
    radio_section = re.search(r'<section class="radio-mode-guide">(.*?)</section>', rendered, re.DOTALL).group(1)
    assert not re.search(r"\b[NCAD]-\d{3}\b", radio_section)


def test_standalone_quick_reference_uses_color_cover_subtitle_and_only_reference_pages():
    rendered = catalog.render_quick_reference_html(
        [sample_program(), sample_program("Collection")],
        artist_rows=[{"code": "A-001", "artist_name": "Artist"}],
        docuseries_groups=[sample_docuseries_group()],
        generated_on=date(2026, 9, 20),
    )
    assert "cover-topspot40-color-concept.png" in rendered
    assert "Permanent Program Numbers<br>and Radio Mode" in rendered
    assert "TopSpot40<br>Discovery Guide" not in rendered
    assert "Artist Spotlight Directory" not in rendered
    assert 'class="docuseries-story"' not in rendered
    assert "Every Song Holds a Story and a Memory" not in rendered


def test_stable_manifest_assignments_are_complete_and_unchanged():
    manifest = catalog.load_manifest()
    catalog.validate_manifest(manifest)
    assert manifest["nostalgia"][0] == {
        "code": "N-001", "decade_slug": "1950s", "genre_slug": "country"
    }
    assert manifest["nostalgia"][-1]["code"] == "N-064"
    assert {entry["code"] for entry in manifest["collections"]} == {
        f"C-{number:03d}" for number in range(1, 53)
    }
    # This is an intentional print-contract checksum, not a generated value.
    assert sha256(catalog.MANIFEST_PATH.read_bytes()).hexdigest() == "7cbda8ca72a1e7f16f4d124184d0b74ecbc86e5d51cdd7f313beb730c6c32ca7"


def test_manifest_validation_reports_duplicate_missing_stale_and_unassigned():
    manifest = catalog.load_manifest()
    broken = deepcopy(manifest)
    broken["nostalgia"][1]["code"] = "N-001"
    available = {
        "nostalgia": {("1950s", "country"), ("2090s", "new_genre")},
        "collections": {broken["collections"][0]["slug"], "future_collection"},
    }
    with pytest.raises(catalog.ManifestValidationError) as raised:
        catalog.validate_manifest(broken, available)
    message = str(raised.value)
    assert "duplicate nostalgia codes" in message
    assert "missing nostalgia codes" in message
    assert "stale nostalgia entries" in message
    assert "unassigned collection entries" in message


def test_nostalgia_order_is_decade_then_established_genre_order():
    manifest = catalog.load_manifest()
    shuffled = deepcopy(manifest)
    shuffled["nostalgia"].reverse()
    ordered = catalog.ordered_nostalgia_entries(shuffled)
    assert [(entry["decade_slug"], entry["genre_slug"]) for entry in ordered[:3]] == [
        ("1950s", "country"), ("1950s", "pop"), ("1950s", "rock")
    ]
    assert [(entry["decade_slug"], entry["genre_slug"]) for entry in ordered[-2:]] == [
        ("2020s", "folk_acoustic"), ("2020s", "tv_themes")
    ]


def test_rank_and_year_are_rendered_from_database_values():
    rendered = catalog.render_program_page(sample_program(), None)
    assert "#17" in rendered
    assert "A Song" in rendered
    assert "An Artist" in rendered
    assert "(1958)" in rendered


def test_track_entries_show_only_the_permanent_catalog_rank_without_list_numbering():
    program = catalog.Program(
        "N-031", "Nostalgia", "1980s Folk Acoustic", "1980s-folk-acoustic",
        decade="1980s", genre="folk_acoustic",
        tracks=(
            {"rank": 1, "title": "Mrs. Robinson", "artist": "Simon & Garfunkel", "year": 1968},
            {"rank": 17, "title": "Homeward Bound", "artist": "Simon & Garfunkel", "year": 1966},
        ),
    )
    rendered = catalog.render_program_page(program, None)
    assert '<ul class="track-list">' in rendered
    assert '<ol class="track-list">' not in rendered
    assert "#1" in rendered and "#17" in rendered
    assert "N-031" in rendered


def test_large_print_css_sets_track_toc_and_directory_text_to_twelve_points():
    rendered = catalog.render_html([sample_program()], generated_on=date(2026, 9, 20))
    assert ".track-columns { display: grid; grid-template-columns: 1fr 1fr;" in rendered
    assert ".track-list { margin: 0; padding: 0; list-style: none; font-size: 12pt; line-height: 1.25" in rendered
    assert ".toc-section li, .toc-section p { font-size: 12pt; line-height: 1.3" in rendered
    assert ".artist-list { flex: 1; margin: 0; padding-left: .2in; font-size: 12pt; line-height: 1.28" in rendered
    assert ".program-heading { min-height: .76in; }" in rendered


def test_display_capitalization_is_render_only_and_preserves_common_acronyms():
    track = {"rank": 1, "title": "dancing in the u.s.a.", "artist": "ac/dc", "year": None}
    rendered = catalog.render_track(track)
    assert "Dancing in the U.S.A." in rendered
    assert "AC/DC" in rendered
    assert track["title"] == "dancing in the u.s.a."


def test_track_overflow_is_split_into_balanced_large_print_program_pages():
    tracks = tuple({"rank": number, "title": f"Song {number}", "artist": "Artist", "year": None}
                   for number in range(1, 47))
    pages = catalog.render_program_pages(sample_program().__class__(
        "N-001", "Nostalgia", "1950s country", "1950s-country", decade="1950s", tracks=tracks
    ), None)
    assert len(pages) == 2
    counts = [page.count("<li>") for page in pages]
    assert sum(counts) == 46 and max(counts) - min(counts) <= 2
    assert all('<ul class="track-list">' in page for page in pages)
    assert all('<ol class="track-list">' not in page for page in pages)
    rendered_ranks = re.findall(r'<span class="rank">#(\d+)</span>', "".join(pages))
    assert rendered_ranks == [str(number) for number in range(1, 47)]
    assert all("QR" not in page for page in pages)


def test_long_track_titles_use_safe_weighted_pages_with_full_continuation_identity():
    tracks = tuple({
        "rank": number,
        "title": f"A deliberately long recording title with concert location and edition {number}",
        "artist": "A Deliberately Long Artist Name", "year": 1980,
    } for number in range(1, 31))
    program = catalog.Program(
        "C-002", "Collection", "Long Title Collection", "long-title-collection",
        category="American Heritage Favorites", tracks=tracks,
    )
    pages = catalog.render_program_pages(program, None, group_banner=program.category)
    assert len(pages) > 1
    assert all("C-002" in page and "Long Title Collection" in page for page in pages)
    assert all("American Heritage Favorites" in page for page in pages)
    assert "continued" in pages[1]
    assert re.findall(r'<span class="rank">#(\d+)</span>', "".join(pages)) == [str(number) for number in range(1, 31)]
    for page in pages:
        tracks_on_page = re.findall(r'<span class="rank">#(\d+)</span>', page)
        source_tracks = [tracks[int(rank) - 1] for rank in tracks_on_page]
        assert sum(catalog.track_print_weight(track) for track in source_tracks) <= 2 * catalog.TRACK_COLUMN_LINE_CAPACITY


def test_every_collection_track_page_repeats_its_collection_group_name():
    tracks = tuple({"rank": number, "title": f"Song {number}", "artist": "Artist", "year": None}
                   for number in range(1, 47))
    program = catalog.Program(
        "C-002", "Collection", "American Folk Heroes", "american_folk_heroes",
        category="American Heritage Favorites", category_slug="american_heritage_favorites",
        category_sort_order=1, tracks=tracks,
    )
    pages = catalog.render_program_pages(program, None, group_banner=program.category)
    assert len(pages) == 2
    assert all("COLLECTION GROUP" in page for page in pages)
    assert all("American Heritage Favorites" in page for page in pages)
    assert all("C-002" in page and "American Folk Heroes" in page for page in pages)
    assert "continued — page 2" in pages[1]


def test_artist_directory_groups_only_supplied_eligibility_rows_and_counts():
    rows = [
        {"genre_name": "Country", "artist_name": "Eligible One", "genre_track_count": 3},
        {"genre_name": "Country", "artist_name": "Eligible Two", "genre_track_count": 5},
        {"genre_name": "Rock", "artist_name": "Eligible Rock", "genre_track_count": 4},
    ]
    rendered = catalog.render_html([sample_program()], artist_rows=rows)
    assert "Eligible One" in rendered and "3 eligible tracks" in rendered
    assert "Eligible Rock" in rendered and "4 eligible tracks" in rendered
    assert rendered.count("<h2>Country</h2>") == 1
    assert "Artist Spotlight directory" in rendered


def test_artist_directory_repeats_genre_heading_on_continuation_pages():
    rows = [{"genre_name": "Country", "artist_name": f"Artist {number}", "genre_track_count": 1}
            for number in range(catalog.ARTISTS_PER_DIRECTORY_PAGE + 1)]
    pages = catalog.render_artist_directory_pages(rows, None)
    assert len(pages) == 2
    assert all("<h2>Country" in page for page in pages)
    assert "continued — page 2" in pages[1]
    assert pages[1].count("<li>") > 1


def test_discovery_guide_has_four_print_pages_before_the_toc_with_required_content():
    rendered = catalog.render_html([sample_program()], generated_on=date(2026, 9, 20))
    assert len(catalog.render_discovery_pages()) == 4
    assert rendered.index("TopSpot40<br>Discovery Guide") < rendered.index("Table of Contents")
    assert "Three Parts of Every Guided Experience" in rendered
    assert all(label in rendered for label in ("Program Introduction", "Track Detail", "Artist Biography"))
    assert all(label in rendered for label in ("English", "Español", "Português do Brasil"))
    assert "TopSpot40 is an independent music-discovery and narration service." in rendered
    assert "QR" not in rendered
    assert "spotify logo" not in rendered.casefold()


def test_instructions_page_includes_approved_founder_note_and_pattys_rule():
    rendered = catalog.render_instructions_page()
    assert "Why We Created TopSpot40" in rendered
    assert "<em>American Top 40</em>" in rendered
    assert "Patty’s Rule" in rendered
    assert "If a feature is too complicated to enjoy, it probably needs to be simplified." in rendered


def test_toc_is_one_conventional_page_with_major_sections_and_starting_pages():
    programs = [sample_program(), sample_program("Collection")]
    rendered = catalog.render_html(programs)
    assert "Nostalgia" in rendered
    assert "Collections" in rendered
    assert "Artist Spotlight" in rendered
    assert rendered.count('class="catalog-page toc"') == 1
    toc_start = rendered.index('class="catalog-page toc"')
    toc = rendered[toc_start:rendered.index('</section>', toc_start)]
    assert "Quick Reference Guide" in toc
    assert toc.index("Nostalgia Programs") < toc.index("Collections") < toc.index("Artist Spotlight")
    assert "N-001" not in toc and "C-001" not in toc


def test_docuseries_catalog_has_an_unnumbered_final_conclusion_and_toc_entry():
    rendered = catalog.render_html(
        [sample_program()], docuseries_groups=[sample_docuseries_group()],
        generated_on=date(2026, 9, 20),
    )
    toc_start = rendered.index('class="catalog-page toc"')
    toc = rendered[toc_start:rendered.index('</section>', toc_start)]
    conclusion_start = rendered.index('class="catalog-page closing-conclusion"')
    conclusion = rendered[conclusion_start:rendered.index('</section>', conclusion_start)]
    assert "Every Song Holds a Story and a Memory" in toc
    assert "Music accompanies us throughout our lives" in conclusion
    assert "Thank you for listening." in conclusion
    assert 'class="closing-pullquote"' in conclusion
    assert 'topspot40-old-dog-new-tracks-icon.png' in conclusion
    assert 'class="back-cover-frame"' in conclusion
    assert 'class="back-cover-lower"' in conclusion
    assert "<footer" not in conclusion
    assert rendered.rfind('class="catalog-page closing-conclusion"') > rendered.rfind('class="catalog-page docuseries')


def test_print_edition_excludes_qr_placeholders_destinations_and_scanning_instructions():
    rendered = catalog.render_html(
        [sample_program(), sample_program("Collection")],
        nostalgia_qr=lambda _program: "https://configured.example/program/N-001",
        collection_qr=lambda _program: "https://configured.example/program/C-001",
        artist_qr_url="https://configured.example/artists",
        artist_rows=[{"genre_name": "Country", "artist_name": "Artist", "genre_track_count": 1}],
    )
    assert "QR" not in rendered
    assert "qr-" not in rendered.casefold()
    assert "configured.example" not in rendered
    assert "scan the program" not in rendered.casefold()


def test_required_print_css_includes_letter_landscape_backgrounds_alternating_gutters_and_folios():
    rendered = catalog.render_html([sample_program()], generated_on=date(2026, 9, 20))
    assert "@page { size: letter landscape; margin: 0; }" in rendered
    assert ".catalog-page:nth-of-type(even)" in rendered
    assert "padding-left: .48in; padding-right: .78in" in rendered
    assert "print-color-adjust: exact" in rendered
    assert "columns: 2" in rendered
    assert "Page 1" in rendered
    assert "counter(page)" not in rendered
    assert "padding: .42in .48in .44in .78in" in rendered


def test_rendered_folios_are_sequential_after_pagination():
    rendered = catalog.render_html([sample_program()], generated_on=date(2026, 9, 20))
    folios = [int(number) for number in re.findall(r"Page (\d+)</footer>", rendered)]
    assert folios == list(range(1, len(folios) + 1))


def test_generate_uses_canonical_artist_eligibility_service(monkeypatch):
    manifest = catalog.load_manifest()
    monkeypatch.setattr(catalog, "load_manifest", lambda: manifest)
    monkeypatch.setattr(catalog, "load_programs", lambda _session, _manifest: [sample_program()])
    monkeypatch.setattr(catalog, "load_approved_manifest", lambda: {"assignments": []})
    monkeypatch.setattr(catalog, "approved_code_maps", lambda _manifest: ({1: "A-001"}, {}))
    monkeypatch.setattr(catalog, "load_docuseries_groups", lambda _session, _codes: [])
    captured = {}
    def fake_eligibility(**kwargs):
        captured.update(kwargs)
        return [{"artist_id": 1, "genre_name": "Country", "genre_slug": "country", "artist_name": "Eligible", "genre_track_count": 3}]
    monkeypatch.setattr(catalog, "featured_artist_eligibility_rows", fake_eligibility)
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *_): return False
    monkeypatch.setattr(catalog, "Session", lambda _engine: FakeSession())
    output = Mock()
    output.parent = Mock()
    assert catalog.generate(output) is output
    output.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    output.write_text.assert_called_once()
    assert captured == {"genres": [genre for genre in catalog.GENRE_ORDER if genre != "tv_themes"], "per_genre": True}


def collection_program(code, title, slug, group=None, order=None):
    return catalog.Program(
        code, "Collection", title, slug,
        category=group, category_slug=group.casefold().replace(" ", "_") if group else None,
        category_sort_order=order,
    )


def test_collection_groups_follow_stored_order_and_preserve_each_code_once():
    programs = [
        collection_program("C-003", "Zulu", "zulu", "Second", 2),
        collection_program("C-002", "Alpha", "alpha", "First", 1),
        collection_program("C-001", "Bravo", "bravo", "First", 1),
        collection_program("C-004", "Orphan", "orphan"),
    ]
    groups, ungrouped = catalog.collection_groups(reversed(programs))
    assert [group.name for group in groups] == ["First", "Second", "Other Collections"]
    assert [program.code for program in groups[0].collections] == ["C-002", "C-001"]
    assert [program.code for group in groups for program in group.collections] == ["C-002", "C-001", "C-003", "C-004"]
    assert ungrouped == ["orphan"]


def test_loaded_collection_group_membership_matches_database_values():
    manifest = catalog.load_manifest()
    with Session(engine) as session:
        programs = catalog.load_programs(session, manifest)
        database_membership = {row.slug: row.category_id for row in session.exec(select(Collection)).all()}
        category_slugs = {row.id: row.slug for row in session.exec(select(CollectionCategory)).all()}
    grouped, ungrouped = catalog.collection_groups(program for program in programs if program.kind == "Collection")
    rendered_membership = {program.slug: group.slug for group in grouped if group.slug != "other_collections" for program in group.collections}
    assert set(rendered_membership) | set(ungrouped) == set(database_membership)
    assert all(program.slug not in ungrouped for group in grouped if group.slug != "other_collections" for program in group.collections)
    assert all(database_membership[slug] is not None for slug in rendered_membership)
    assert all(rendered_membership[slug] == category_slugs[database_membership[slug]] for slug in rendered_membership)
    assert all(database_membership[slug] is None for slug in ungrouped)


def test_blues_jazz_fits_one_balanced_three_column_artist_page():
    rows = [{"genre_name": "Blues Jazz", "artist_name": f"Artist {number:02d}", "genre_track_count": 3}
            for number in range(37)]
    pages = catalog.render_artist_directory_pages(rows, None)
    assert len(pages) == 1
    counts = [column.count("<li>") for column in pages[0].split('<ul class="artist-list">')[1:]]
    assert sum(counts) == 37 and max(counts) - min(counts) <= 2


def test_artist_continuations_only_follow_capacity_and_are_not_sparse():
    rows = [{"genre_name": "Country", "artist_name": f"Artist {number:03d}", "genre_track_count": 3}
            for number in range(catalog.ARTISTS_PER_DIRECTORY_PAGE + 1)]
    pages = catalog.render_artist_directory_pages(rows, None)
    assert len(pages) == 2
    assert all(page.count("<li>") <= catalog.ARTISTS_PER_DIRECTORY_PAGE for page in pages)
    assert min(page.count("<li>") for page in pages) >= 30
    assert "continued" in pages[1]
    assert all("QR" not in page for page in pages)


def test_artist_spotlight_toc_block_shares_the_final_collection_page():
    nostalgia = [sample_program()]
    groups, _ = catalog.collection_groups([collection_program("C-001", "Collection", "collection", "Group", 1)])
    pages = catalog.plan_grouped_toc_pages(nostalgia, groups)
    assert len(pages) == 1
    assert [block.title for block in pages[0]] == ["Nostalgia", "Group", "Artist Spotlight"]


def test_full_opening_nostalgia_toc_is_explicitly_balanced_into_two_columns():
    nostalgia = [catalog.Program(f"N-{number:03d}", "Nostalgia", f"Program {number}", f"program-{number}")
                 for number in range(1, 65)]
    rendered = catalog.render_grouped_toc_pages(nostalgia, [], maximum=65)
    assert len(rendered) == 2
    first_page = rendered[0]
    assert first_page.count('<section class="toc-section"><h3>Nostalgia Programs</h3>') == 2
    assert "N-032" in first_page and "N-033" in first_page and "N-064" in first_page


def test_all_artwork_dividers_use_the_approved_square_bw_branding_and_shared_alignment():
    rendered = catalog.render_artwork_divider(
        "Traditional Favorites", "Curated themed programs with permanent C-xxx codes.",
        "collection-group-traditional-favorites.png", eyebrow="Collection group",
    )
    assert 'class="divider-brand-icon"' in rendered
    assert 'topspot40-old-dog-new-tracks-bw.png' in rendered
    assert 'alt="TopSpot40 — Old Dog, New Tracks"' in rendered
    stylesheet = catalog.render_html([sample_program()])
    assert '.artwork-divider .divider-copy { position: absolute; z-index: 1; top: 1.8in; right: .68in; width: 3.65in; text-align: right; }' in stylesheet
    assert '.artwork-divider .divider-brand-icon { display: block; width: 1.7in; height: auto; margin: .24in 0 0 auto; }' in stylesheet


def test_approved_continuation_artwork_is_complete_resolvable_and_footer_safe():
    expected = {
        "N-007": "continuation-n007-1950s-folk-acoustic.png",
        "N-015": "continuation-n015-1960s-folk-acoustic.png",
        "N-023": "continuation-n023-1970s-folk-acoustic.png",
        "N-031": "continuation-n031-1980s-folk-acoustic.png",
        "N-039": "continuation-n039-1990s-folk-acoustic.png",
        "N-047": "continuation-n047-2000s-folk-acoustic.png",
        "N-055": "continuation-n055-2010s-folk-acoustic.png",
        "C-032": "continuation-c032-legends-tv-themes.png",
        "C-050": "continuation-c050-video-game-themes.png",
    }
    assert {code: artwork.filename for code, artwork in catalog.CONTINUATION_ARTWORK.items()} == expected
    assert {path.name for path in catalog.CONTINUATION_ARTWORK_DIR.glob("*.png")} == set(expected.values())
    assert all((catalog.CONTINUATION_ARTWORK_DIR / filename).is_file() for filename in expected.values())
    # The folio occupies the lower edge; 7.6in is the protected artwork floor.
    assert all(artwork.y_in + artwork.height_in <= 7.6 for artwork in catalog.CONTINUATION_ARTWORK.values())


def test_continuation_artwork_renders_once_only_on_its_assigned_final_page():
    tracks = tuple({
        "rank": number,
        "title": f"A deliberately long recording title for safe overflow placement {number}",
        "artist": "A Deliberately Long Artist Name", "year": 1980,
    } for number in range(1, 46))
    for code, artwork in catalog.CONTINUATION_ARTWORK.items():
        program = catalog.Program(
            code, "Collection" if code.startswith("C-") else "Nostalgia",
            f"Approved artwork program {code}", f"approved-artwork-{code}", tracks=tracks,
        )
        pages = catalog.render_program_pages(program, None)
        source = f'{catalog.CONTINUATION_ARTWORK_URL}/{artwork.filename}'
        assert len(pages) > 1
        assert sum(page.count(source) for page in pages) == 1
        assert source not in "".join(pages[:-1])
        assert pages[-1].count(source) == 1
        assert f'width: {artwork.width_in:g}in; height: {artwork.height_in:g}in;' in pages[-1]
        assert f'left: {artwork.x_in:g}in; top: {artwork.y_in:g}in;' in pages[-1]


def test_no_unapproved_continuation_artwork_can_be_rendered():
    program = catalog.Program(
        "N-999", "Nostalgia", "Unassigned Program", "unassigned-program",
        tracks=tuple({"rank": number, "title": "Long Title " * 8, "artist": "Artist", "year": 1980}
                     for number in range(1, 46)),
    )
    rendered = "".join(catalog.render_program_pages(program, None))
    assert "continuation-artwork" not in rendered
    assert catalog.CONTINUATION_ARTWORK_URL not in rendered


def test_artist_spotlight_introduction_uses_approved_terms_and_print_native_guides():
    pages = catalog.render_artist_spotlight_instruction_pages()
    assert len(pages) == 2
    rendered = "".join(pages)
    assert "How Artist Spotlight Works" in pages[0]
    assert "Two Ways to Enjoy a Featured Artist" in pages[1]
    assert all(label in rendered for label in (
        "Featured Artists", "Other Artists", "Single Track Artists",
        "5&ndash;10 minutes", "Play Artist Story", "Start Artist Spotlight",
        "Guided Play", "Auto Play", "Previous", "Next", "More Info", "Track List",
    ))
    assert "Premium Artists" not in rendered
    assert "http://" not in rendered and "https://" not in rendered


def test_artist_spotlight_block_precedes_directory_with_an_intentional_blank_and_divider():
    rendered = catalog.render_html(
        [sample_program()],
        artist_rows=[{"genre_name": "Country", "artist_name": "Artist", "genre_track_count": 1}],
        generated_on=date(2026, 9, 20),
    )
    blank = 'Intentionally blank for Artist Spotlight Directory alignment'
    divider = f'{catalog.ARTWORK_URL}/{catalog.ARTIST_SPOTLIGHT_DIVIDER_ARTWORK}'
    directory = 'Artist Spotlight directory'
    assert rendered.index(blank) < rendered.index(divider) < rendered.index("How Artist Spotlight Works")
    assert rendered.index("How Artist Spotlight Works") < rendered.index("Two Ways to Enjoy a Featured Artist") < rendered.rindex(directory)
    assert f'<img class="divider-art" src="{divider}" alt="">' in rendered




def test_collection_toc_split_labels_only_later_group_portions_as_continued():
    collections = [collection_program(f"C-{number:03d}", f"Collection {number}", f"collection_{number}", "Traditional Favorites", 1)
                   for number in range(1, 6)]
    groups, _ = catalog.collection_groups(collections)
    pages = catalog.plan_grouped_toc_pages([], groups, maximum=4)
    traditional_blocks = [block for page in pages for block in page if block.title == "Traditional Favorites"]

    assert [block.continuation for block in traditional_blocks] == [False, True]
    assert [program.code for block in traditional_blocks for program in block.entries] == [
        "C-001", "C-002", "C-003", "C-004", "C-005",
    ]
    rendered = catalog.render_grouped_toc_pages([], groups, maximum=4)
    headings = [page[page.index("Traditional Favorites"):page.index("</h3>", page.index("Traditional Favorites"))]
                for page in rendered if "Traditional Favorites" in page]
    assert "continued" not in headings[0]
    assert "continued" in headings[1]


def test_docuseries_uses_the_required_application_group_order_and_all_english_rows():
    groups = catalog.load_docuseries_groups(Session(engine))
    assert [group.name for group in groups] == [
        "Instruments That Changed Music", "Movements & Revolutions",
        "Latin America and the Caribbean", "History & Eras", "Legends & Rivalries",
        "Foundations, Technology, and Events", "The People Behind the Music",
        "Mysteries & Tragedies", "Modern Music and Listening", "Songs & Stories",
        "Modern Music Revolutions", "Beyond the Music", "Brazil and New Global Sounds",
        "Mexico and the Border",
    ]
    stories = [story for group in groups for story in group.stories]
    assert len(groups) == 14
    assert len(stories) == 127
    assert len({story.slug for story in stories}) == len(stories)
    assert all(story.story_text.strip() for story in stories)


def test_docuseries_opener_and_group_pages_are_large_print_and_self_identifying():
    group = sample_docuseries_group(story_count=22)
    pages = catalog.render_docuseries_pages([group])
    assert len(pages) > 2
    assert "Music<br>Docuseries" in pages[0]
    assert "contains no music tracks" in pages[0]
    assert 'data-docuseries-group="musical_instruments"' in pages[1]
    assert "Instruments That Changed Music" in pages[1]
    assert "Instruments That Changed Music" in pages[2]
    assert "continued" in pages[2]
    rendered = "".join(pages[1:])
    assert rendered.count('class="docuseries-story"') == 22
    assert "#1" not in rendered and 'class="rank"' not in rendered
    assert "Spotify" not in rendered and "Track List" not in rendered
    assert ".docuseries-story p { margin: 0; font-size: 12pt" in catalog.render_html([sample_program()])


def test_docuseries_summaries_and_runtime_labels_are_conservative_and_deterministic():
    source = catalog.DocuseriesStory(
        slug="verified", title="A Verified Subject", story_text="Reviewed source text.", duration_seconds=None,
    )
    assert catalog.format_docuseries_runtime(None) is None
    assert catalog.format_docuseries_runtime(372) == "6 min 12 sec"
    summary = catalog.docuseries_summary(source)
    assert "A Verified Subject" in summary
    assert 15 <= len(summary.split()) <= 30
    group = catalog.DocuseriesGroup("musical_instruments", "Instruments That Changed Music", (source,))
    assert catalog.render_docuseries_pages([group]) == catalog.render_docuseries_pages([group])


def test_docuseries_section_follows_the_artist_directory_without_affecting_prior_page_sequence():
    baseline = catalog.render_html(
        [sample_program()], artist_rows=[{"genre_name": "Country", "artist_name": "Artist", "genre_track_count": 1}],
        generated_on=date(2026, 9, 20),
    )
    extended = catalog.render_html(
        [sample_program()], artist_rows=[{"genre_name": "Country", "artist_name": "Artist", "genre_track_count": 1}],
        docuseries_groups=[sample_docuseries_group()], generated_on=date(2026, 9, 20),
    )
    marker = '<section class="catalog-page docuseries docuseries-opener">'
    assert marker in extended
    body_baseline = baseline.split("</style></head><body>", 1)[1]
    body_extended = extended.split("</style></head><body>", 1)[1]
    assert body_extended.index(marker) > body_extended.index("Artist Spotlight directory")
    # The D-code quick-reference pages are intentionally inserted near the
    # front. Ignore only those pages and their shifted folios; all catalog
    # content before the Docuseries opener must remain in the same order.
    strip_quick_reference = lambda value: re.sub(r'<section class="catalog-page quick-reference.*?</section>', '', value, flags=re.DOTALL)
    strip_alignment_blanks = lambda value: re.sub(r'<section class="catalog-page duplex-blank.*?</section>', '', value, flags=re.DOTALL)
    strip_toc = lambda value: re.sub(r'<section class="catalog-page toc.*?</section>', '', value, flags=re.DOTALL)
    normalize_folios = lambda value: re.sub(r'Page \d+</footer>', 'Page #</footer>', value)
    before_docuseries = body_extended[:body_extended.index(marker)]
    baseline_before_close = body_baseline[:-len("</body></html>")]
    assert normalize_folios(strip_toc(strip_alignment_blanks(strip_quick_reference(before_docuseries)))) == normalize_folios(strip_toc(strip_alignment_blanks(strip_quick_reference(baseline_before_close))))


def test_artist_directory_excludes_tv_themes_but_nostalgia_tv_themes_remains_printed():
    pages = catalog.render_artist_directory_pages([
        {"genre_name": "TV Themes", "genre_slug": "tv_themes", "artist_name": "TV Only", "genre_track_count": 3, "code": "A-001"},
        {"genre_name": "Rock", "genre_slug": "rock", "artist_name": "Retained", "genre_track_count": 3, "code": "A-002"},
    ], None)
    rendered = "".join(pages)
    assert "TV Only" not in rendered and "TV Themes" not in rendered
    assert "Retained" in rendered and "A-002" in rendered
    assert any(entry["genre_slug"] == "tv_themes" for entry in catalog.load_manifest()["nostalgia"])
