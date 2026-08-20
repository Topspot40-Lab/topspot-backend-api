"""Approved 2026 docuseries release sequence and manifest builder."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


CENTRAL = ZoneInfo("America/Chicago")

LANGUAGE_TIMES = {
    "en": time(11),
    "es": time(15),
    "pt-BR": time(19),
}

LANGUAGE_LABELS = {
    "en": "English",
    "es": "Español",
    "pt-BR": "Português",
}

MASTER_PLAYLISTS = {
    "en": (
        "english_docuseries",
        "TopSpot40 Documentaries (English)",
    ),
    "es": (
        "spanish_docuseries",
        "Documentales TopSpot40 (Español)",
    ),
    "pt-BR": (
        "portuguese_docuseries",
        "Documentários TopSpot40 (Português)",
    ),
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
    "movements_revolutions": {
        "en": "Movements & Revolutions — English",
        "es": "Movimientos y Revoluciones — Español",
        "pt-BR": "Movimentos e Revoluções — Português",
    },
    "people_behind_music": {
        "en": "The People Behind the Music — English",
        "es": "La gente detrás de la música — Español",
        "pt-BR": "As pessoas por trás da música — Português",
    },
    "mysteries_tragedies": {
        "en": "Mysteries & Tragedies — English",
        "es": "Misterios y Tragedias — Español",
        "pt-BR": "Mistérios e Tragédias — Português",
    },
    "mexico_border": {
        "en": "Mexico and the Border — English",
        "es": "México y la Frontera — Español",
        "pt-BR": "México e a Fronteira — Português",
    },
    "latin_america_caribbean": {
        "en": "Latin America and the Caribbean — English",
        "es": "América Latina y el Caribe — Español",
        "pt-BR": "América Latina e o Caribe — Português",
    },
    "brazil_new_global_sounds": {
        "en": "Brazil and New Global Sounds — English",
        "es": "Brasil y Nuevos Sonidos Globales — Español",
        "pt-BR": "Brasil e Novos Sons Globais — Português",
    },
}


@dataclass(frozen=True, slots=True)
class ReleaseTopic:
    collection_key: str
    slug: str
    title: str


@dataclass(frozen=True, slots=True)
class BatchRelease:
    collection_key: str
    slug: str
    release_date: date


TOPICS = (
    ReleaseTopic(
        "history_eras",
        "fabulous_fifties",
        "The Fabulous Fifties",
    ),
    ReleaseTopic(
        "history_eras",
        "swinging_sixties",
        "The Swinging Sixties",
    ),
    ReleaseTopic(
        "history_eras",
        "seventies_decade_of_change",
        "The Seventies: A Decade of Change",
    ),
    ReleaseTopic(
        "history_eras",
        "mtv_and_the_eighties",
        "MTV and the Eighties",
    ),
    ReleaseTopic(
        "history_eras",
        "alternative_nation_nineties",
        "Alternative Nation: The Nineties",
    ),
    ReleaseTopic(
        "history_eras",
        "music_in_the_new_millennium",
        "Music in the New Millennium",
    ),
    ReleaseTopic(
        "songs_stories",
        "story_behind_american_pie",
        "The Story Behind American Pie",
    ),
    ReleaseTopic(
        "songs_stories",
        "one_hit_wonders",
        "One-Hit Wonders",
    ),
    ReleaseTopic(
        "songs_stories",
        "songs_banned_from_radio",
        "Songs Banned from Radio",
    ),
    ReleaseTopic(
        "songs_stories",
        "woodstock",
        "Woodstock",
    ),
    ReleaseTopic(
        "legends_rivalries",
        "beatles_vs_stones",
        "Beatles vs. Stones",
    ),
    ReleaseTopic(
        "legends_rivalries",
        "elvis_vs_sinatra",
        "Elvis vs. Sinatra",
    ),
    ReleaseTopic(
        "legends_rivalries",
        "country_traditionalists_vs_country_pop",
        "Country Traditionalists vs. Country Pop",
    ),
    ReleaseTopic(
        "legends_rivalries",
        "ranchera_vs_norteno",
        "Ranchera vs. Norteño",
    ),
    ReleaseTopic(
        "legends_rivalries",
        "vicente_fernandez_vs_antonio_aguilar",
        "Vicente Fernández vs. Antonio Aguilar",
    ),
    ReleaseTopic(
        "legends_rivalries",
        "bossa_nova_vs_samba",
        "Bossa Nova vs. Samba",
    ),
)


def release_dates(
    start: date = date(2026, 8, 12),
) -> tuple[date, ...]:
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
    """Build the original fail-closed 48-upload manifest."""

    existing_playlist_ids = {
        "en": english_docuseries_playlist_id,
        "es": spanish_docuseries_playlist_id,
        "pt-BR": portuguese_docuseries_playlist_id,
    }

    playlists = _build_master_playlists(existing_playlist_ids)

    for collection_key, names in COLLECTIONS.items():
        for language, title in names.items():
            playlists.append(
                {
                    "key": f"{collection_key}_{language}",
                    "title": title,
                    "description": (
                        f"TopSpot40 {title} documentary collection."
                    ),
                    "privacy_status": "public",
                }
            )

    uploads: list[dict[str, object]] = []

    for topic, release_day in zip(
        TOPICS,
        release_dates(start),
        strict=True,
    ):
        uploads.extend(
            _build_release_uploads(
                productions_root=productions_root,
                collection_key=topic.collection_key,
                slug=topic.slug,
                release_day=release_day,
            )
        )

    return {
        "schema_version": 1,
        "time_zone": "America/Chicago",
        "playlists": playlists,
        "uploads": uploads,
    }


def load_batch_plan(
    path: Path,
) -> tuple[BatchRelease, ...]:
    """Load a reusable daily YouTube batch-plan JSON file."""

    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise ValueError(
            f"Batch plan not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid batch plan JSON: {path}"
        ) from exc

    if not isinstance(value, dict):
        raise ValueError(
            "Batch plan must be a JSON object"
        )

    releases = value.get("releases")

    if not isinstance(releases, list) or not releases:
        raise ValueError(
            "Batch plan requires a non-empty releases list"
        )

    result: list[BatchRelease] = []

    for index, item in enumerate(releases, 1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Batch release {index} must be an object"
            )

        collection_key = item.get("collection_key")
        slug = item.get("slug")
        release_date_value = item.get("release_date")

        if collection_key not in COLLECTIONS:
            raise ValueError(
                f"Batch release {index} has unknown "
                f"collection_key: {collection_key}"
            )

        if not isinstance(slug, str) or not slug.strip():
            raise ValueError(
                f"Batch release {index} requires slug"
            )

        if not isinstance(release_date_value, str):
            raise ValueError(
                f"Batch release {index} requires release_date"
            )

        try:
            release_day = date.fromisoformat(
                release_date_value
            )
        except ValueError as exc:
            raise ValueError(
                f"Batch release {index} has invalid "
                f"release_date: {release_date_value}"
            ) from exc

        result.append(
            BatchRelease(
                collection_key=collection_key,
                slug=slug.strip(),
                release_date=release_day,
            )
        )

    identities = [
        (
            release.collection_key,
            release.slug,
            release.release_date,
        )
        for release in result
    ]

    if len(set(identities)) != len(identities):
        raise ValueError(
            "Batch plan contains duplicate releases"
        )

    return tuple(result)


def build_batch_manifest_document(
    productions_root: Path,
    batch_plan_path: Path,
    *,
    english_docuseries_playlist_id: str,
    spanish_docuseries_playlist_id: str,
    portuguese_docuseries_playlist_id: str,
) -> dict[str, object]:
    """
    Build a fail-closed manifest from a reusable batch plan.

    Each documentary automatically produces three uploads:
    English at 11 AM Central,
    Spanish at 3 PM Central,
    Portuguese-Brazil at 7 PM Central.
    """

    releases = load_batch_plan(
        batch_plan_path
    )

    existing_playlist_ids = {
        "en": english_docuseries_playlist_id,
        "es": spanish_docuseries_playlist_id,
        "pt-BR": portuguese_docuseries_playlist_id,
    }

    playlists = _build_master_playlists(
        existing_playlist_ids
    )

    required_collection_keys = sorted(
        {
            release.collection_key
            for release in releases
        }
    )

    for collection_key in required_collection_keys:
        names = COLLECTIONS[collection_key]

        for language, title in names.items():
            playlists.append(
                {
                    "key": (
                        f"{collection_key}_{language}"
                    ),
                    "title": title,
                    "description": (
                        f"TopSpot40 {title} "
                        f"documentary collection."
                    ),
                    "privacy_status": "public",
                }
            )

    uploads: list[dict[str, object]] = []

    for release in releases:
        uploads.extend(
            _build_release_uploads(
                productions_root=productions_root,
                collection_key=release.collection_key,
                slug=release.slug,
                release_day=release.release_date,
            )
        )

    return {
        "schema_version": 1,
        "time_zone": "America/Chicago",
        "playlists": playlists,
        "uploads": uploads,
    }


def _build_master_playlists(
    existing_playlist_ids: dict[str, str],
) -> list[dict[str, object]]:
    """Build the three existing language-master playlists."""

    playlists: list[dict[str, object]] = []

    for language, (
        key,
        title,
    ) in MASTER_PLAYLISTS.items():
        playlists.append(
            {
                "key": key,
                "title": title,
                "description": (
                    "TopSpot40 music documentaries in "
                    f"{LANGUAGE_LABELS[language]}."
                ),
                "privacy_status": "public",
                "existing_playlist_id": (
                    existing_playlist_ids[language]
                ),
            }
        )

    return playlists


def _build_release_uploads(
    *,
    productions_root: Path,
    collection_key: str,
    slug: str,
    release_day: date,
) -> list[dict[str, object]]:
    """Build the three language uploads for one documentary."""

    factory = (
        productions_root
        / slug
        / "factory"
    )

    uploads: list[dict[str, object]] = []

    for language, release_time in LANGUAGE_TIMES.items():
        metadata_path = (
            factory
            / "publishing"
            / language
            / "youtube.json"
        )

        try:
            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )
        except FileNotFoundError as exc:
            raise ValueError(
                "Missing approved YouTube metadata: "
                f"{metadata_path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Invalid YouTube metadata: "
                f"{metadata_path}"
            ) from exc

        if not isinstance(metadata, dict):
            raise ValueError(
                "YouTube metadata must be an object: "
                f"{metadata_path}"
            )

        tags = metadata.get(
            "keywords",
            metadata.get("tags"),
        )

        if (
            not isinstance(tags, list)
            or not tags
            or not all(
                isinstance(tag, str)
                and bool(tag.strip())
                for tag in tags
            )
        ):
            raise ValueError(
                "YouTube metadata requires "
                f"non-empty keywords: {metadata_path}"
            )

        video_path = (
            factory
            / "delivery"
            / language
            / "documentary.mp4"
        )

        thumbnail_path = (
            factory
            / "publishing"
            / language
            / "thumbnail.png"
        )

        captions_path = (
            factory
            / "publishing"
            / language
            / "captions.vtt"
        )

        master_playlist_key = (
            MASTER_PLAYLISTS[language][0]
        )

        playlist_keys = [
            master_playlist_key,
            f"{collection_key}_{language}",
        ]

        uploads.append(
            {
                "slug": slug,
                "collection_key": collection_key,
                "language_code": language,
                "video_path": str(video_path),
                "thumbnail_path": str(
                    thumbnail_path
                ),
                "captions_path": str(
                    captions_path
                ),
                "title": metadata.get("title"),
                "description": metadata.get(
                    "description"
                ),
                "tags": tags,
                "category_id": "10",
                "made_for_kids": False,
                "contains_synthetic_media": True,
                "notify_subscribers": True,
                "end_screen_required": True,
                "visual_approval": "gary",
                "approved_video_sha256": _sha256(
                    video_path
                ),
                "scheduled_publish_at": (
                    datetime.combine(
                        release_day,
                        release_time,
                        CENTRAL,
                    ).isoformat()
                ),
                "playlist_keys": playlist_keys,
            }
        )

    return uploads


def write_manifest(
    document: dict[str, object],
    path: Path,
) -> None:
    """Write a manifest JSON document."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256(
    path: Path,
) -> str:
    """Return the SHA-256 digest of a visually approved documentary."""

    try:
        handle = path.open("rb")
    except FileNotFoundError as exc:
        raise ValueError(
            "Missing visually approved documentary: "
            f"{path}"
        ) from exc

    digest = hashlib.sha256()

    with handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()