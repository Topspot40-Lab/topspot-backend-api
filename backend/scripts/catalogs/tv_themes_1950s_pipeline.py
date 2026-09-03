"""Side-effect-free helpers for the 1950s TV Themes production plan."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

CATALOG_SLUG = "1950s-tv_themes"
CATALOG_ID = 63
LANGUAGES = ("en", "es", "pt-BR")
NARRATION_TYPES = ("intro", "short_detail", "long_detail")
BUCKETS = {"en": "audio-en", "es": "audio-es", "pt-BR": "audio-ptbr"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def playable_candidates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in manifest["approved_catalog_candidates"] if item.get("spotify_track_id", "").strip()]


def validate_production_plan(manifest: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest["program"] != {"decade_genre_id": CATALOG_ID, "slug": CATALOG_SLUG}:
        raise ValueError("wrong catalog manifest")
    approved = {item["spotify_track_id"] for item in playable_candidates(manifest)}
    entries = plan.get("ranked_candidates", [])
    ids, ranks = [item.get("spotify_track_id", "") for item in entries], [item.get("proposed_rank") for item in entries]
    if len(entries) != 19 or len(ids) != len(set(ids)) or set(ids) != approved:
        raise ValueError("plan must contain exactly the 19 approved Spotify candidates")
    if ranks != list(range(1, 20)):
        raise ValueError("plan ranks must be contiguous from 1 through 19")
    required = ("show_title", "theme_title", "performer", "original_broadcast_years", "classification", "qualification", "ranking_rationale")
    for entry in entries:
        missing = [key for key in required if not str(entry.get(key, "")).strip()]
        if missing:
            raise ValueError(f"{entry.get('show_title', 'candidate')}: missing {', '.join(missing)}")
    return entries


def canonical_key(entry: dict[str, Any], narration_type: str) -> str:
    if narration_type == "intro":
        return f"intro/{CATALOG_SLUG}_{entry['proposed_rank']:02d}.mp3"
    if narration_type == "short_detail":
        return f"short-detail/{entry['spotify_track_id']}.mp3"
    if narration_type == "long_detail":
        return f"detail/{entry['spotify_track_id']}.mp3"
    raise ValueError(f"unsupported narration type: {narration_type}")


def expected_narration(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"catalog_slug": CATALOG_SLUG, "catalog_id": CATALOG_ID, "ranking": entry["proposed_rank"], "spotify_track_id": entry["spotify_track_id"], "language": language, "narration_type": kind, "bucket": BUCKETS[language], "key": canonical_key(entry, kind)} for entry in plan["ranked_candidates"] for language in LANGUAGES for kind in NARRATION_TYPES]


def _texts(entry: dict[str, Any], language: str) -> dict[str, str]:
    show, theme, performer, years, qualification = (entry[key] for key in ("show_title", "theme_title", "performer", "original_broadcast_years", "qualification"))
    if language == "en":
        return {"intro": f"Number {entry['proposed_rank']}: {show}, with {theme} by {performer}.", "short_detail": f"{theme} represents {show}, a television program first broadcast from {years}.", "long_detail": f"{theme} is the approved theme selection for {show}. This recording is credited to {performer}. The program first broadcast from {years}. Recording qualification: {qualification}"}
    if language == "es":
        return {"intro": f"Número {entry['proposed_rank']}: {show}, con {theme}, interpretado por {performer}.", "short_detail": f"{theme} representa a {show}, programa de televisión emitido originalmente entre {years}.", "long_detail": f"{theme} es el tema aprobado para {show}. Esta grabación se acredita a {performer}. El programa se emitió originalmente entre {years}. Calificación de la grabación: {qualification}"}
    if language == "pt-BR":
        return {"intro": f"Número {entry['proposed_rank']}: {show}, com {theme}, interpretada por {performer}.", "short_detail": f"{theme} representa {show}, programa de televisão exibido originalmente entre {years}.", "long_detail": f"{theme} é o tema aprovado de {show}. Esta gravação é creditada a {performer}. O programa foi exibido originalmente entre {years}. Qualificação da gravação: {qualification}"}
    raise ValueError(f"unsupported language: {language}")


def build_text_bundle(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"catalog_slug": CATALOG_SLUG, "ranking": entry["proposed_rank"], "spotify_track_id": entry["spotify_track_id"], "language": language, "narration_type": kind, "text": text} for entry in plan["ranked_candidates"] for language in LANGUAGES for kind, text in _texts(entry, language).items()]


def narration_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in ("ranking", "spotify_track_id", "language", "narration_type"))


def completeness_report(expected: Iterable[dict[str, Any]], text_rows: Iterable[dict[str, Any]], audio_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = {narration_identity(row) for row in expected}
    text_ids = {narration_identity(row) for row in text_rows if str(row.get("text", "")).strip()}
    audio_rows = list(audio_rows)
    audio_ids = {narration_identity(row) for row in audio_rows if str(row.get("key", "")).strip()}
    invalid = [row for row in audio_rows if row.get("key") and row.get("key") != canonical_key({"proposed_rank": row["ranking"], "spotify_track_id": row["spotify_track_id"]}, row["narration_type"])]
    return {"expected": len(expected_ids), "text_present": len(text_ids & expected_ids), "audio_present": len(audio_ids & expected_ids), "missing_text": sorted(expected_ids - text_ids), "missing_audio": sorted(expected_ids - audio_ids), "unexpected_text": sorted(text_ids - expected_ids), "unexpected_audio": sorted(audio_ids - expected_ids), "invalid_audio_keys": len(invalid), "complete": expected_ids == text_ids == audio_ids and not invalid}


def plan_summary(manifest: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    entries = validate_production_plan(manifest, plan)
    counts = Counter(row["language"] for row in expected_narration(plan))
    return {"mode": "plan-only", "catalog_slug": CATALOG_SLUG, "catalog_id": CATALOG_ID, "ranked_candidates": len(entries), "narration_files": 171, "narration_files_by_language": dict(counts), "database_writes": 0, "storage_writes": 0, "paid_service_calls": 0}


def replace_catalog_rankings(session: Any, entries: list[dict[str, Any]], *, create_missing_tracks: bool = False) -> None:
    """Apply-only primitive: replace rankings for catalog id 63 after all tracks resolve."""
    from sqlmodel import select
    from backend.models.dbmodels import Artist, Track, TrackRanking
    ids = [entry["spotify_track_id"] for entry in entries]
    tracks = session.exec(select(Track).where(Track.spotify_track_id.in_(ids))).all()
    by_id = {track.spotify_track_id: track for track in tracks}
    missing = sorted(set(ids) - set(by_id))
    if missing and create_missing_tracks:
        for entry in entries:
            if entry["spotify_track_id"] not in missing:
                continue
            artist = session.exec(select(Artist).where(Artist.artist_name == entry["performer"])).first()
            if artist is None:
                artist = Artist(artist_name=entry["performer"])
                session.add(artist); session.flush()
            track = Track(track_name=entry["theme_title"], artist_display_name=entry["performer"], spotify_track_id=entry["spotify_track_id"], artist_id=artist.id, source_type="TV", source_title=entry["show_title"], years_on_air=entry["original_broadcast_years"], source_role="THEME", version_notes=f"{entry['classification']}. {entry['qualification']}")
            session.add(track); session.flush(); by_id[track.spotify_track_id] = track
        missing = sorted(set(ids) - set(by_id))
    if missing:
        raise ValueError("apply refused; missing production Track rows: " + ", ".join(missing))
    for ranking in session.exec(select(TrackRanking).where(TrackRanking.decade_genre_id == CATALOG_ID)).all():
        session.delete(ranking)
    session.flush()
    for entry in entries:
        session.add(TrackRanking(track_id=by_id[entry["spotify_track_id"]].id, decade_genre_id=CATALOG_ID, ranking=entry["proposed_rank"]))


def replace_catalog_narration_text(session: Any, records: list[dict[str, Any]]) -> None:
    """Apply-mode primitive: replace all 171 text fields for this catalog only."""
    from sqlmodel import select
    from backend.models.dbmodels import Track, TrackLocale, TrackRanking, TrackRankingLocale
    identities = {narration_identity(row) for row in records}
    if len(records) != 171 or len(identities) != 171:
        raise ValueError("text apply refused: the complete 171-record replacement bundle is required")
    rankings = session.exec(select(TrackRanking, Track).join(Track).where(TrackRanking.decade_genre_id == CATALOG_ID)).all()
    mapped = {(ranking.ranking, track.spotify_track_id): (ranking, track) for ranking, track in rankings}
    if len(mapped) != 19:
        raise ValueError("text apply refused: catalog does not contain exactly 19 ranked tracks")
    by_identity = {narration_identity(row): row["text"] for row in records}
    for (rank, spotify_id), (ranking, track) in mapped.items():
        ranking.intro = by_identity[(rank, spotify_id, "en", "intro")]
        track.detail = by_identity[(rank, spotify_id, "en", "long_detail")]
        track.short_detail = by_identity[(rank, spotify_id, "en", "short_detail")]
        for language in ("es", "pt-BR"):
            rank_locale = session.exec(select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id == ranking.id, TrackRankingLocale.language_code == language)).first()
            if rank_locale is None:
                rank_locale = TrackRankingLocale(track_ranking_id=ranking.id, language_code=language, intro_text="")
            rank_locale.intro_text = by_identity[(rank, spotify_id, language, "intro")]
            session.add(rank_locale)
            track_locale = session.exec(select(TrackLocale).where(TrackLocale.track_id == track.id, TrackLocale.language_code == language)).first()
            if track_locale is None:
                track_locale = TrackLocale(track_id=track.id, language_code=language, detail_text="")
            track_locale.detail_text = by_identity[(rank, spotify_id, language, "long_detail")]
            track_locale.short_detail_text = by_identity[(rank, spotify_id, language, "short_detail")]
            session.add(track_locale)
        session.add(ranking); session.add(track)


def replace_catalog_tts_mappings(session: Any, records: list[dict[str, Any]]) -> None:
    """Record canonical locale/short-detail keys after a complete replacement run."""
    from sqlmodel import select
    from backend.models.dbmodels import Track, TrackLocale, TrackRanking, TrackRankingLocale
    if len(records) != 171:
        raise ValueError("TTS mapping refused: all 171 records are required")
    rankings = session.exec(select(TrackRanking, Track).join(Track).where(TrackRanking.decade_genre_id == CATALOG_ID)).all()
    mapped = {(ranking.ranking, track.spotify_track_id): (ranking, track) for ranking, track in rankings}
    if len(mapped) != 19:
        raise ValueError("TTS mapping refused: catalog does not contain exactly 19 ranked tracks")
    for record in records:
        ranking, track = mapped[(record["ranking"], record["spotify_track_id"])]
        language, kind = record["language"], record["narration_type"]
        if language == "en" and kind == "short_detail":
            track.short_detail_tts_key = record["key"]; session.add(track)
        elif language != "en":
            if kind == "intro":
                locale = session.exec(select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id == ranking.id, TrackRankingLocale.language_code == language)).one()
                locale.tts_bucket, locale.tts_key = record["bucket"], record["key"]; session.add(locale)
            else:
                locale = session.exec(select(TrackLocale).where(TrackLocale.track_id == track.id, TrackLocale.language_code == language)).one()
                if kind == "short_detail": locale.short_detail_tts_key = record["key"]
                else: locale.tts_bucket, locale.tts_key = record["bucket"], record["key"]
                session.add(locale)


def live_database_narration_rows(session: Any, expected: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Read-only DB projection used by the completeness CLI's optional --live mode."""
    from sqlmodel import select
    from backend.models.dbmodels import Track, TrackLocale, TrackRanking, TrackRankingLocale
    rankings = session.exec(select(TrackRanking, Track).join(Track).where(TrackRanking.decade_genre_id == CATALOG_ID)).all()
    mapped = {(ranking.ranking, track.spotify_track_id): (ranking, track) for ranking, track in rankings}
    rows = []
    for item in expected:
        pair = mapped.get((item["ranking"], item["spotify_track_id"]))
        if pair is None: continue
        ranking, track = pair; language, kind = item["language"], item["narration_type"]
        if language == "en": text = ranking.intro if kind == "intro" else (track.short_detail if kind == "short_detail" else track.detail)
        elif kind == "intro":
            locale = session.exec(select(TrackRankingLocale).where(TrackRankingLocale.track_ranking_id == ranking.id, TrackRankingLocale.language_code == language)).first(); text = locale.intro_text if locale else ""
        else:
            locale = session.exec(select(TrackLocale).where(TrackLocale.track_id == track.id, TrackLocale.language_code == language)).first(); text = (locale.short_detail_text if kind == "short_detail" else locale.detail_text) if locale else ""
        rows.append({**item, "text": text or ""})
    return rows, len(mapped)
