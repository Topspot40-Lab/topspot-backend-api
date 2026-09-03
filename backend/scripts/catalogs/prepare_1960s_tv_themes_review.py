"""Create offline research, production-plan, and UTF-8 narration-draft artifacts.

This is deliberately a no-write-to-production preparation tool.  It only reads
the committed catalog-64 snapshot and writes review manifests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
SNAPSHOT = ROOT / "rollback_snapshots" / "1960s-tv-themes.catalog-64.prep.v1.json"
OUT = ROOT / "review_manifests"

# Existing ranks retained exactly once, in editorial order.  The four tuples at
# the end are public-Spotify replacement candidates verified during review.
RETAINED_RANKS = (3, 4, 6, 7, 8, 10, 11, 12, 13, 15, 16, 18, 19, 21, 22, 23, 24, 25, 26, 29, 33, 34, 36, 40, 41, 44, 45)
REPLACEMENTS = {
    4: ("Hawaii Five-O", "Morton Stevens", "6I2oKAEHPCtFUPe7Tsm1Xt", "correct_original_or_broadcast_associated"),
    21: ("The Ballad of Jed Clampett", "Flatt & Scruggs", "2bNADRKyZiui7TOgIFilFr", "correct_contemporary_commercial_recording"),
    44: ('Doctor Who (Original Theme) [From "Doctor Who"]', "Ron Grainer, Delia Derbyshire", "5dxWU9epbOtZ0XHv60tydp", "correct_original_or_broadcast_associated"),
    45: ('Main Theme from "The Saint"', "Edwin Astley & His Orchestra", "4Up8UssyK2nFZWVp7k0A1O", "correct_contemporary_commercial_recording"),
}
EXCLUSION_REASON = {
    27: "duplicate_program_and_wrong_lalo_schifrin_attribution",
    28: "duplicate_program_unresolved_recording_and_missing_artist_relation",
    30: "duplicate_program_unresolved_recording_and_missing_artist_relation",
    31: "unresolved_public_recording_and_missing_artist_relation",
    32: "duplicate_program_unresolved_recording_and_missing_artist_relation",
    35: "duplicate_program_unresolved_recording_and_missing_artist_relation",
    37: "duplicate_program_unresolved_recording_and_missing_artist_relation",
    38: "unresolved_public_recording_and_missing_artist_relation",
    39: "karaoke_recording_mislabeled_as_flatt_and_scruggs",
    42: "unresolved_public_recording_and_missing_artist_relation",
    43: "duplicate_program_unresolved_recording_and_missing_artist_relation",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _classification(rank: int, track: dict) -> str:
    if rank in (4, 21, 27, 39, 44, 45):
        return "incorrect_recording"
    if rank in EXCLUSION_REASON:
        return "unresolved"
    if (track["artist_display_name"] or "").casefold() in {"jack marshall", "hugo montenegro"}:
        return "recognizable_rerecording_or_cover"
    return "correct_original_or_broadcast_associated"


def _review_note(rank: int) -> str:
    if rank in EXCLUSION_REASON:
        return EXCLUSION_REASON[rank]
    if rank in REPLACEMENTS:
        return "current recording rejected; verified public Spotify replacement is in production plan"
    return "retained once in proposed plan"


INTRO_PATTERNS = {
    "en": (
        "At number {rank}, {program}: {title}, performed by {artist}.",
        "Number {rank} brings {program} with {title} from {artist}.",
        "Here at number {rank}, it is {program} — {title}, performed by {artist}.",
        "Number {rank}: {artist} takes us into {program} with {title}.",
        "Coming in at {rank}, {program}, featuring {title} by {artist}.",
        "Our number {rank} theme is {title} from {program}, performed by {artist}.",
        "At {rank}, hear {artist} with {title}, the theme of {program}.",
        "Number {rank} spotlights {program} and {title}, performed by {artist}.",
        "Now at number {rank}: {title} by {artist}, from {program}.",
    ),
    "es-MX": (
        "En el número {rank}, {program}: {title}, interpretado por {artist}.",
        "El número {rank} trae {program} con {title} de {artist}.",
        "En el puesto {rank}, escuchamos {program}: {title}, interpretado por {artist}.",
        "Número {rank}: {artist} nos lleva a {program} con {title}.",
        "Llega al {rank} {program}, con {title} de {artist}.",
        "Nuestro tema número {rank} es {title}, de {program}, interpretado por {artist}.",
        "En el {rank}, {artist} presenta {title}, el tema de {program}.",
        "El número {rank} destaca {program} y {title}, interpretado por {artist}.",
        "Ahora, en el número {rank}: {title} de {artist}, de {program}.",
    ),
    "pt-BR": (
        "No número {rank}, {program}: {title}, interpretado por {artist}.",
        "O número {rank} traz {program} com {title}, de {artist}.",
        "Na posição {rank}, ouvimos {program}: {title}, interpretado por {artist}.",
        "Número {rank}: {artist} nos leva a {program} com {title}.",
        "Chegando ao {rank}, {program}, com {title} de {artist}.",
        "Nosso tema de número {rank} é {title}, de {program}, interpretado por {artist}.",
        "No {rank}, {artist} apresenta {title}, o tema de {program}.",
        "O número {rank} destaca {program} e {title}, interpretado por {artist}.",
        "Agora, no número {rank}: {title} de {artist}, de {program}.",
    ),
}

DETAIL_REPLACEMENTS = {
    (rank, language, kind): "replacement_track"
    for rank in (4, 21, 44, 45)
    for language in ("en", "es-MX", "pt-BR")
    for kind in ("short_detail", "long_detail")
} | {
    (15, "pt-BR", "long_detail"): "proven_mojibake",
    (16, "pt-BR", "long_detail"): "proven_mojibake",
    (23, "pt-BR", "long_detail"): "proven_mojibake",
}


def _intro(entry: dict, language: str) -> str:
    return INTRO_PATTERNS[language][entry["source_rank"] % 9].format(
        rank=entry["source_rank"], program=entry["program"], title=entry["track_name"], artist=entry["artist"],
    )


def _detail(entry: dict, language: str, kind: str) -> str:
    title, artist, program = entry["track_name"], entry["artist"], entry["program"]
    if language == "es-MX":
        lead = f"{title}, interpretado por {artist}, es la grabación seleccionada para {program}."
        return lead if kind == "short_detail" else lead + " La selección respeta la identidad del programa y acredita correctamente al intérprete."
    if language == "pt-BR":
        lead = f"{title}, interpretado por {artist}, é a gravação selecionada para {program}."
        return lead if kind == "short_detail" else lead + " A seleção preserva a identidade do programa e credita corretamente o intérprete."
    lead = f"{title}, performed by {artist}, is the selected recording for {program}."
    return lead if kind == "short_detail" else lead + " The selection preserves the programme identity and credits the performer accurately."


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    by_rank = {record["ranking"]["ranking"]: record for record in snapshot["records"]}
    research = []
    for rank in sorted(by_rank):
        track = by_rank[rank]["track"]
        research.append({
            "existing_rank": rank,
            "track_name": track["track_name"],
            "spotify_track_id": track["spotify_track_id"],
            "classification": _classification(rank, track),
            "public_spotify_url": f"https://open.spotify.com/track/{track['spotify_track_id']}",
            "review_note": _review_note(rank),
        })
    approved = []
    for rank in RETAINED_RANKS:
        track = by_rank[rank]["track"]
        title, artist, spotify_id, classification = REPLACEMENTS.get(
            rank,
            (track["track_name"], by_rank[rank]["artist"]["artist_name"], track["spotify_track_id"], _classification(rank, track)),
        )
        approved.append({
            "sequence_order": len(approved) + 1,
            "proposed_rank": rank,
            "source_rank": rank,
            "program": track["source_title"] or track["track_name"],
            "track_name": title,
            "artist": artist,
            "spotify_track_id": spotify_id,
            "spotify_public_url": f"https://open.spotify.com/track/{spotify_id}",
            "classification": classification,
            "artwork_source": "Spotify public track metadata at apply-time",
            "qualification": "Verified public Spotify-compatible selection; no production apply authorized by this artifact.",
        })
    plan = {
        "schema_version": 2,
        "catalog_id": 64,
        "catalog_slug": "1960s_tv_themes",
        "approved_entries": approved,
        "unresolved_excluded": [{"existing_rank": rank, "reason": reason} for rank, reason in EXCLUSION_REASON.items()],
        "rank_preservation_policy": "Retained and replacement entries keep their current source_rank; no retained track is renumbered.",
        "gap_filler_research": {
            "status": "deferred_without_verified_candidates",
            "open_ranks": [1, 2, 5, 9, 14, 17, 20, 28, 30, 31, 32, 35, 37, 38, 39, 42, 43],
            "rule": "Do not add a recording solely to fill a gap; only separately verified, unique 1960s programmes may be proposed later.",
        },
        "intro_rewrite": {
            "record_count": len(approved) * 3,
            "languages": ["en", "es-MX", "pt-BR"],
            "staging_prefix": "staging/catalog-64/1960s-tv-themes-intro-rewrite-v1",
            "canonical_key_pattern": "intro/1960s_tv_themes_{rank:02}.mp3",
            "promotion_rule": "Generate, hash, cache-disabled download, transcribe, and validate every staged intro before atomically updating catalog-64 intro mappings.",
            "cache_rule": "Return authoritative versioned or cache-fresh playback URLs after promotion; never select a pre-existing intro solely because it exists.",
        },
        "detail_preservation": {
            "retain_mapping_count": 135,
            "replacement_mapping_count": len(DETAIL_REPLACEMENTS),
            "replacement_reasons": {"replacement_track": 24, "proven_mojibake": 3},
            "safety_rule": "Never overwrite a shared correct detail object; stage replacements and point only the affected catalog-64 locale mapping at promoted versioned objects.",
        },
        "future_apply_requires": ["fresh public Spotify page recheck", "artwork URL check", "human review of final localized drafts", "separate production authorization"],
    }
    records = []
    for entry in approved:
        for language in ("en", "es-MX", "pt-BR"):
            text = _intro(entry, language)
            records.append({"rank": entry["proposed_rank"], "language": language, "kind": "intro", "purpose": "replace_all_ranked_intros", "text": text, "text_sha256": _sha(text)})
        for language in ("en", "es-MX", "pt-BR"):
            for kind in ("short_detail", "long_detail"):
                reason = DETAIL_REPLACEMENTS.get((entry["source_rank"], language, kind))
                if reason:
                    text = _detail(entry, language, kind)
                    records.append({"rank": entry["proposed_rank"], "language": language, "kind": kind, "purpose": reason, "text": text, "text_sha256": _sha(text)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "1960s-tv-themes.research.v1.json").write_text(json.dumps({"catalog_id": 64, "records": research}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "1960s-tv-themes.production-plan.v1.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "1960s-tv-themes.narration-drafts.v1.json").write_text(json.dumps({"catalog_id": 64, "records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"research_records": len(research), "approved_entries": len(approved), "drafts": len(records), "intro_drafts": len(approved) * 3, "detail_drafts": len(records) - len(approved) * 3}))


if __name__ == "__main__":
    main()
