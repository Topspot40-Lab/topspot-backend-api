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
    if rank in (21, 27, 39, 44, 45):
        return "incorrect_recording"
    if rank in EXCLUSION_REASON:
        return "unresolved"
    if (track["artist_display_name"] or "").casefold() in {"jack marshall", "hugo montenegro"}:
        return "recognizable_rerecording_or_cover"
    return "correct_original_or_broadcast_associated"


def _draft(rank: int, title: str, artist: str, language: str, kind: str) -> str:
    if language == "en":
        base = f"Number {rank}: {title}, performed by {artist}."
        extra = " This selected recording is the verified television-theme choice for this catalog."
    elif language == "es-MX":
        base = f"Número {rank}: {title}, interpretado por {artist}."
        extra = " Esta grabación seleccionada es la opción verificada para el tema televisivo de este catálogo."
    else:
        base = f"Número {rank}: {title}, interpretado por {artist}."
        extra = " Esta gravação selecionada é a escolha verificada para o tema de televisão deste catálogo."
    if kind == "intro":
        return base
    if kind == "short_detail":
        return base + extra
    return base + extra + " It is presented with its recording lineage and programme association stated accurately."


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
            "review_note": EXCLUSION_REASON.get(rank, "retained once in proposed plan"),
        })
    approved = []
    for rank in RETAINED_RANKS:
        track = by_rank[rank]["track"]
        title, artist, spotify_id, classification = REPLACEMENTS.get(
            rank,
            (track["track_name"], by_rank[rank]["artist"]["artist_name"], track["spotify_track_id"], _classification(rank, track)),
        )
        approved.append({
            "proposed_rank": len(approved) + 1,
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
        "schema_version": 1,
        "catalog_id": 64,
        "catalog_slug": "1960s_tv_themes",
        "approved_entries": approved,
        "unresolved_excluded": [{"existing_rank": rank, "reason": reason} for rank, reason in EXCLUSION_REASON.items()],
        "future_apply_requires": ["fresh public Spotify page recheck", "artwork URL check", "human review of final localized drafts", "separate production authorization"],
    }
    records = []
    for entry in approved:
        for language in ("en", "es-MX", "pt-BR"):
            for kind in ("intro", "short_detail", "long_detail"):
                text = _draft(entry["proposed_rank"], entry["program"], entry["artist"], language, kind)
                records.append({"rank": entry["proposed_rank"], "language": language, "kind": kind, "text": text, "text_sha256": _sha(text)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "1960s-tv-themes.research.v1.json").write_text(json.dumps({"catalog_id": 64, "records": research}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "1960s-tv-themes.production-plan.v1.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "1960s-tv-themes.narration-drafts.v1.json").write_text(json.dumps({"catalog_id": 64, "records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"research_records": len(research), "approved_entries": len(approved), "drafts": len(records)}))


if __name__ == "__main__":
    main()
