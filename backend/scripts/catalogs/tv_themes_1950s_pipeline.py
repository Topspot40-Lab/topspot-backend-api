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

# Covers published on the approved tracks' public, unauthenticated Spotify web
# pages. These are fixed catalog metadata, not runtime Spotify API lookups.
ALBUM_ARTWORK_BY_SPOTIFY_TRACK_ID = {
    "5lSfu6Bb1lZHvEA5Lp3FSo": "https://i.scdn.co/image/ab67616d0000b273151141f5d992c02322847648",
    "2esm55sr13FFKqoP6qwjUz": "https://i.scdn.co/image/ab67616d0000b273f2b8fc493fcd8d6738efaff4",
    "71qlBJvHesvpK3TJXGN95O": "https://i.scdn.co/image/ab67616d0000b27363221fdf21ea6e83737b93cb",
    "301w6yavJnABE4APW72ynW": "https://i.scdn.co/image/ab67616d0000b2739db8c7a0afd569bb31a0fb7d",
    "3Gr3f20ajbTXP25lmrg2Qb": "https://i.scdn.co/image/ab67616d0000b273d704338a0b33cb86ab8c5a0d",
    "3PowPOuvw8BE8Dx2XkzPHF": "https://i.scdn.co/image/ab67616d0000b273c48bc2c274fd1f02bc3717ef",
    "7up8IVBnHisqNGn2ewyuyk": "https://i.scdn.co/image/ab67616d0000b273009f72a9d461bd07ebb5eab0",
    "5BO1NDOaXxuEN0mqMaapnC": "https://i.scdn.co/image/ab67616d0000b273d28f834e4643004bb860cf0c",
    "1aiXLeKljeTCbX5fVPISTS": "https://i.scdn.co/image/ab67616d0000b2730f6cd9f8d9e8b7b978bdf199",
    "1uLyJWPzDJeMCSi3dH6jEb": "https://i.scdn.co/image/ab67616d0000b273671ddfff4ddb439040375417",
    "1FaiVQR1BUHxttxYUMAQiW": "https://i.scdn.co/image/ab67616d0000b2735dcd6b1e8b96e6e55bd4fe10",
    "5As4kPiB9eZ5Q9EVBaYqHs": "https://i.scdn.co/image/ab67616d0000b273c3e1d62c7991ecfc000c059c",
    "1F6N0vw7S55QK7SckEDhhY": "https://i.scdn.co/image/ab67616d0000b2731ac214238ae6f9f43a6e2265",
    "5qc4Q3sRK0mjKdomhfMqxN": "https://i.scdn.co/image/ab67616d0000b273ac459e1fb6478fc38ab1114b",
    "7BOhsPHziYhIIQmPdYS6c0": "https://i.scdn.co/image/ab67616d0000b27355ed9506b1a321b6a1495fba",
    "5MFrmRlOVi1hBoZvgFNFvI": "https://i.scdn.co/image/ab67616d0000b2739cfd468cf6f6445b49a95481",
    "1u1mZ6NgPmLohzNAVMExhh": "https://i.scdn.co/image/ab67616d0000b273364c299394362dc7fe98a477",
    "2N4bp5eHNlL6pNogf4DpTR": "https://i.scdn.co/image/ab67616d0000b27324b851c72b54e6fbaac46af6",
    "1kEauajzb7929zqiIVW9fQ": "https://i.scdn.co/image/ab67616d0000b273e14a925519e0a6ebf5b19a54",
}


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


def album_artwork_records(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the complete, catalog-scoped established album-artwork mapping."""
    approved_ids = {entry["spotify_track_id"] for entry in entries}
    if approved_ids != set(ALBUM_ARTWORK_BY_SPOTIFY_TRACK_ID):
        raise ValueError("album artwork mapping must match exactly the 19 approved catalog tracks")
    return [
        {
            "ranking": entry["proposed_rank"],
            "spotify_track_id": entry["spotify_track_id"],
            "album_artwork": ALBUM_ARTWORK_BY_SPOTIFY_TRACK_ID[entry["spotify_track_id"]],
        }
        for entry in entries
    ]


def expected_narration(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"catalog_slug": CATALOG_SLUG, "catalog_id": CATALOG_ID, "ranking": entry["proposed_rank"], "spotify_track_id": entry["spotify_track_id"], "language": language, "narration_type": kind, "bucket": BUCKETS[language], "key": canonical_key(entry, kind)} for entry in plan["ranked_candidates"] for language in LANGUAGES for kind in NARRATION_TYPES]


_LINEAGE = {
    "5lSfu6Bb1lZHvEA5Lp3FSo": ("It is an approved recognizable cover, not the original broadcast recording.", "Es una versión reconocible aprobada, no la grabación original de emisión.", "É uma versão reconhecível aprovada, não a gravação original de transmissão."),
    "71qlBJvHesvpK3TJXGN95O": ("It is an approved recognizable cover, not the original broadcast recording.", "Es una versión reconocible aprobada, no la grabación original de emisión.", "É uma versão reconhecível aprovada, não a gravação original de transmissão."),
    "2esm55sr13FFKqoP6qwjUz": ("This is Bernard Herrmann's 1959 first-season theme, not the later Marius Constant theme.", "Es el tema de la primera temporada de 1959 de Bernard Herrmann, no el tema posterior de Marius Constant.", "É o tema da primeira temporada de 1959 de Bernard Herrmann, não o tema posterior de Marius Constant."),
    "301w6yavJnABE4APW72ynW": ("It is an approved recognizable cover; original-broadcast lineage is not claimed.", "Es una versión reconocible aprobada; no se afirma que proceda de la emisión original.", "É uma versão reconhecível aprovada; não se afirma que venha da transmissão original."),
    "7up8IVBnHisqNGn2ewyuyk": ("It targets Jerome Moross's 1959 instrumental, although the exact Spotify release lineage remains uncertain.", "Apunta al instrumental de 1959 de Jerome Moross, aunque la procedencia exacta de la edición de Spotify sigue siendo incierta.", "Remete ao instrumental de 1959 de Jerome Moross, embora a procedência exata da edição do Spotify permaneça incerta."),
    "3Gr3f20ajbTXP25lmrg2Qb": ("It is a 1969 rerecording, not the confirmed 1954 broadcast recording.", "Es una regrabación de 1969, no la grabación de emisión confirmada de 1954.", "É uma regravação de 1969, não a gravação de transmissão confirmada de 1954."),
    "5BO1NDOaXxuEN0mqMaapnC": ("This is a later-issued release, and its broadcast-master lineage is unconfirmed.", "Es una edición publicada posteriormente y no se ha confirmado su procedencia como máster de emisión.", "É um lançamento posterior, e sua procedência como matriz de transmissão não foi confirmada."),
    "5qc4Q3sRK0mjKdomhfMqxN": ("It is Count Basie's second- and third-season theme, distinct from Stanley Wilson's first-season theme.", "Es el tema de Count Basie de la segunda y tercera temporadas, distinto del tema de la primera temporada de Stanley Wilson.", "É o tema de Count Basie da segunda e da terceira temporadas, distinto do tema da primeira temporada de Stanley Wilson."),
    "2N4bp5eHNlL6pNogf4DpTR": ("The Wray, Corwin, and Bill Lee attribution, possible David Rose pseudonym, and exact release lineage remain qualified.", "La atribución a Wray, Corwin y Bill Lee, el posible seudónimo de David Rose y la procedencia exacta de la edición siguen siendo inciertos.", "A atribuição a Wray, Corwin e Bill Lee, o possível pseudônimo de David Rose e a procedência exata do lançamento continuam incertos."),
    "5As4kPiB9eZ5Q9EVBaYqHs": ("It is a later cover recreation and is not verified as the broadcast master.", "Es una recreación posterior y no está verificada como el máster de emisión.", "É uma recriação posterior e não foi verificada como a matriz de transmissão."),
    "1F6N0vw7S55QK7SckEDhhY": ("It is a 2009 recreation, not an original recording.", "Es una recreación de 2009, no una grabación original.", "É uma recriação de 2009, não uma gravação original."),
    "1kEauajzb7929zqiIVW9fQ": ("It is an approved 26-second recognizable cover of the 1958 series theme.", "Es una versión reconocible aprobada de 26 segundos del tema de la serie de 1958.", "É uma versão reconhecível aprovada de 26 segundos do tema da série de 1958."),
    "5MFrmRlOVi1hBoZvgFNFvI": ("It is David Rose's 1943 commercial composition associated with the show; broadcast-master use is unverified.", "Es la composición comercial de David Rose de 1943 asociada con el programa; no se ha verificado su uso como máster de emisión.", "É a composição comercial de David Rose de 1943 associada ao programa; seu uso como matriz de transmissão não foi verificado."),
    "1u1mZ6NgPmLohzNAVMExhh": ("It is an approved later recognizable cover.", "Es una versión reconocible posterior aprobada.", "É uma versão reconhecível posterior aprovada."),
    "3PowPOuvw8BE8Dx2XkzPHF": ("It is an approved later recognizable cover of the Buttolph and Webster theme.", "Es una versión reconocible posterior aprobada del tema de Buttolph y Webster.", "É uma versão reconhecível posterior aprovada do tema de Buttolph e Webster."),
    "1aiXLeKljeTCbX5fVPISTS": ("It is an approved later recognizable recreation of David Rose's composition.", "Es una recreación reconocible posterior aprobada de la composición de David Rose.", "É uma recriação reconhecível posterior aprovada da composição de David Rose."),
    "1uLyJWPzDJeMCSi3dH6jEb": ("It is an approved later recognizable cover.", "Es una versión reconocible posterior aprobada.", "É uma versão reconhecível posterior aprovada."),
    "7BOhsPHziYhIIQmPdYS6c0": ("It is an original commercial-recording reissue; use as the exact broadcast master is not asserted.", "Es una reedición de una grabación comercial original; no se afirma que sea el máster exacto de emisión.", "É uma reedição de uma gravação comercial original; não se afirma que seja a matriz exata de transmissão."),
    "1FaiVQR1BUHxttxYUMAQiW": ("Spotify's compilation metadata is later, while the underlying recording is identified as a 1952 commercial release.", "Los metadatos de la recopilación de Spotify son posteriores, pero la grabación subyacente se identifica como un lanzamiento comercial de 1952.", "Os metadados da coletânea no Spotify são posteriores, mas a gravação subjacente é identificada como um lançamento comercial de 1952."),
}


def _texts(entry: dict[str, Any], language: str) -> dict[str, str]:
    show, theme, performer, years = (entry[key] for key in ("show_title", "theme_title", "performer", "original_broadcast_years"))
    lineage = _LINEAGE[entry["spotify_track_id"]][LANGUAGES.index(language)]
    if language == "en":
        return {"intro": f"At number {entry['proposed_rank']}, {show}: {theme}, performed by {performer}.", "short_detail": f"The approved recording of {theme}, credited to {performer}, recalls {show}, the television program originally broadcast from {years}, in this selection.", "long_detail": f"{show} originally aired from {years}. The approved recording of {theme} is credited to {performer}. Its placement recognizes the program's lasting place in television history. {lineage}"}
    if language == "es":
        return {"intro": f"En el número {entry['proposed_rank']}, {show}: {theme}, interpretado por {performer}.", "short_detail": f"La grabación aprobada de {theme}, acreditada a {performer}, evoca a {show}, programa emitido originalmente entre {years}, en esta selección.", "long_detail": f"{show} se emitió originalmente entre {years}. La grabación aprobada de {theme} se acredita a {performer}. Su lugar reconoce la importancia duradera del programa en la historia de la televisión. {lineage}"}
    if language == "pt-BR":
        return {"intro": f"No número {entry['proposed_rank']}, {show}: {theme}, interpretada por {performer}.", "short_detail": f"A gravação aprovada de {theme}, creditada a {performer}, remete a {show}, programa exibido originalmente entre {years}, nesta seleção musical.", "long_detail": f"{show} foi exibido originalmente entre {years}. A gravação aprovada de {theme} é creditada a {performer}. Sua inclusão reconhece a importância duradoura do programa na história da televisão. {lineage}"}
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


def approved_english_intros(entries: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[tuple[int, str], str]:
    """Validate the exact English rank-intro subset before any apply transaction."""
    expected = {(entry["proposed_rank"], entry["spotify_track_id"]): entry for entry in entries}
    intros = [row for row in records if row.get("language") == "en" and row.get("narration_type") == "intro"]
    identities = [(row.get("ranking"), row.get("spotify_track_id")) for row in intros]
    if len(intros) != 19 or len(identities) != len(set(identities)) or set(identities) != set(expected):
        raise ValueError("text bundle must contain exactly one English intro for each approved rank and Spotify ID")
    result = {}
    for row in intros:
        identity = (row["ranking"], row["spotify_track_id"])
        text = str(row.get("text", "")).strip()
        entry = expected[identity]
        if not text or entry["show_title"] not in text or entry["theme_title"] not in text or entry["performer"] not in text:
            raise ValueError(f"invalid English intro identity for rank {identity[0]}")
        result[identity] = text
    return result


def replace_catalog_rankings(session: Any, entries: list[dict[str, Any]], english_intros: dict[tuple[int, str], str], *, create_missing_tracks: bool = False) -> None:
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
        identity = (entry["proposed_rank"], entry["spotify_track_id"])
        intro = english_intros.get(identity)
        if not intro:
            raise ValueError(f"apply refused: missing English intro for rank {entry['proposed_rank']}")
        session.add(TrackRanking(track_id=by_id[entry["spotify_track_id"]].id, decade_genre_id=CATALOG_ID, ranking=entry["proposed_rank"], intro=intro))


def apply_catalog_rankings(session: Any, entries: list[dict[str, Any]], english_intros: dict[tuple[int, str], str], *, create_missing_tracks: bool) -> None:
    """Commit one atomic catalog-only ranking replacement, rolling back on any failure."""
    try:
        replace_catalog_rankings(session, entries, english_intros, create_missing_tracks=create_missing_tracks)
        session.commit()
    except Exception:
        session.rollback()
        raise


def apply_catalog_album_artwork(session: Any, records: list[dict[str, Any]]) -> None:
    """Atomically update only the 19 unshared Track rows used by catalog 63."""
    from sqlmodel import select
    from backend.models.dbmodels import Track, TrackRanking

    expected = {record["spotify_track_id"]: record["album_artwork"] for record in records}
    if len(expected) != 19 or any(not url for url in expected.values()):
        raise ValueError("album artwork apply refused: complete 19-record mapping required")
    try:
        rows = session.exec(
            select(TrackRanking, Track)
            .join(Track, Track.id == TrackRanking.track_id)
            .where(TrackRanking.decade_genre_id == CATALOG_ID)
        ).all()
        mapped = {track.spotify_track_id: track for ranking, track in rows}
        if len(mapped) != 19 or set(mapped) != set(expected):
            raise ValueError("album artwork apply refused: catalog tracks do not exactly match the approved mapping")
        track_ids = [track.id for track in mapped.values()]
        shared = session.exec(select(TrackRanking).where(TrackRanking.track_id.in_(track_ids))).all()
        if any(ranking.decade_genre_id != CATALOG_ID for ranking in shared):
            raise ValueError("album artwork apply refused: catalog Track rows are shared by another catalog")
        for spotify_track_id, track in mapped.items():
            track.album_artwork = expected[spotify_track_id]
            session.add(track)
        session.commit()
    except Exception:
        session.rollback()
        raise


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
