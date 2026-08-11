"""Approved 2026 docuseries release sequence and manifest builder."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


CENTRAL = ZoneInfo("America/Chicago")
LANGUAGE_TIMES = {"en": time(11), "es": time(15), "pt-BR": time(19)}
LANGUAGE_LABELS = {"en": "English", "es": "Español", "pt-BR": "Português"}
MASTER_PLAYLISTS = {
    "en": ("english_docuseries", "TopSpot40 Documentaries (English)"),
    "es": ("spanish_docuseries", "Documentales TopSpot40 (Español)"),
    "pt-BR": ("portuguese_docuseries", "Documentários TopSpot40 (Português)"),
}
COLLECTIONS = {
    "history_eras": {
        "en": "History & Eras — English",
        "es": "Historia y Épocas — Español",
        "pt-BR": "História e Épocas — Português",
    },
    "songs_stories": {
        "en": "Songs & Stories — English",
        "es": "Canciones e Historias — Español",
        "pt-BR": "Canções e Histórias — Português",
    },
    "legends_rivalries": {
        "en": "Legends & Rivalries — English",
        "es": "Leyendas y Rivalidades — Español",
        "pt-BR": "Lendas e Rivalidades — Português",
    },
}


@dataclass(frozen=True, slots=True)
class ReleaseTopic:
    collection_key: str
    slug: str
    title: str


TOPICS = (
    ReleaseTopic("history_eras", "fabulous_fifties", "The Fabulous Fifties"),
    ReleaseTopic("history_eras", "swinging_sixties", "The Swinging Sixties"),
    ReleaseTopic("history_eras", "seventies_decade_of_change", "The Seventies: A Decade of Change"),
    ReleaseTopic("history_eras", "mtv_and_the_eighties", "MTV and the Eighties"),
    ReleaseTopic("history_eras", "alternative_nation_nineties", "Alternative Nation: The Nineties"),
    ReleaseTopic("history_eras", "music_in_the_new_millennium", "Music in the New Millennium"),
    ReleaseTopic("songs_stories", "story_behind_american_pie", "The Story Behind American Pie"),
    ReleaseTopic("songs_stories", "one_hit_wonders", "One-Hit Wonders"),
    ReleaseTopic("songs_stories", "songs_banned_from_radio", "Songs Banned from Radio"),
    ReleaseTopic("songs_stories", "woodstock", "Woodstock"),
    ReleaseTopic("legends_rivalries", "beatles_vs_stones", "Beatles vs. Stones"),
    ReleaseTopic("legends_rivalries", "elvis_vs_sinatra", "Elvis vs. Sinatra"),
    ReleaseTopic("legends_rivalries", "country_traditionalists_vs_country_pop", "Country Traditionalists vs. Country Pop"),
    ReleaseTopic("legends_rivalries", "ranchera_vs_norteno", "Ranchera vs. Norteño"),
    ReleaseTopic("legends_rivalries", "vicente_fernandez_vs_antonio_aguilar", "Vicente Fernández vs. Antonio Aguilar"),
    ReleaseTopic("legends_rivalries", "bossa_nova_vs_samba", "Bossa Nova vs. Samba"),
)


def release_dates(start: date = date(2026, 8, 12)) -> tuple[date, ...]:
    """Return the 16 Wednesday/Saturday dates beginning with ``start``."""
    if start.weekday() != 2:
        raise ValueError("The first release must be a Wednesday")
    result: list[date] = []
    current = start
    while len(result) < len(TOPICS):
        if current.weekday() in {2, 5}:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def build_manifest_document(
    productions_root: Path,
    *,
    english_docuseries_playlist_id: str,
    spanish_docuseries_playlist_id: str,
    portuguese_docuseries_playlist_id: str,
    start: date = date(2026, 8, 12),
) -> dict[str, object]:
    """Build a fail-closed 48-upload manifest from verified factory outputs."""
    existing_playlist_ids = {
        "en": english_docuseries_playlist_id,
        "es": spanish_docuseries_playlist_id,
        "pt-BR": portuguese_docuseries_playlist_id,
    }
    playlists: list[dict[str, object]] = []
    for language, (key, title) in MASTER_PLAYLISTS.items():
        playlists.append(
            {
                "key": key,
                "title": title,
                "description": f"TopSpot40 music documentaries in {LANGUAGE_LABELS[language]}.",
                "privacy_status": "public",
                "existing_playlist_id": existing_playlist_ids[language],
            }
        )
    for collection_key, names in COLLECTIONS.items():
        for language, title in names.items():
            playlists.append(
                {
                    "key": f"{collection_key}_{language}",
                    "title": title,
                    "description": f"TopSpot40 {title} documentary collection.",
                    "privacy_status": "public",
                }
            )

    uploads: list[dict[str, object]] = []
    for topic, release_day in zip(TOPICS, release_dates(start), strict=True):
        factory = productions_root / topic.slug / "factory"
        for language, release_time in LANGUAGE_TIMES.items():
            metadata_path = factory / "publishing" / language / "youtube.json"
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise ValueError(f"Missing approved YouTube metadata: {metadata_path}") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid YouTube metadata: {metadata_path}") from exc
            if not isinstance(metadata, dict):
                raise ValueError(f"YouTube metadata must be an object: {metadata_path}")
            tags = metadata.get("keywords", metadata.get("tags"))
            if not isinstance(tags, list):
                raise ValueError(f"YouTube metadata requires keywords: {metadata_path}")
            master_playlist_key = MASTER_PLAYLISTS[language][0]
            playlist_keys = [master_playlist_key, f"{topic.collection_key}_{language}"]
            uploads.append(
                {
                    "slug": topic.slug,
                    "collection_key": topic.collection_key,
                    "language_code": language,
                    "video_path": str(factory / "delivery" / language / "documentary.mp4"),
                    "thumbnail_path": str(factory / "publishing" / language / "thumbnail.png"),
                    "captions_path": str(factory / "publishing" / language / "captions.vtt"),
                    "title": metadata.get("title"),
                    "description": metadata.get("description"),
                    "tags": tags,
                    "category_id": "10",
                    "made_for_kids": False,
                    "contains_synthetic_media": True,
                    "notify_subscribers": True,
                    "end_screen_required": True,
                    "visual_approval": "gary",
                    "approved_video_sha256": _sha256(factory / "delivery" / language / "documentary.mp4"),
                    "scheduled_publish_at": datetime.combine(release_day, release_time, CENTRAL).isoformat(),
                    "playlist_keys": playlist_keys,
                }
            )
    return {"schema_version": 1, "time_zone": "America/Chicago", "playlists": playlists, "uploads": uploads}


def write_manifest(document: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    try:
        handle = path.open("rb")
    except FileNotFoundError as exc:
        raise ValueError(f"Missing visually approved documentary: {path}") from exc
    digest = hashlib.sha256()
    with handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
