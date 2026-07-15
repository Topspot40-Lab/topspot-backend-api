from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.studio.production import Production


IDENTITY_VOCABULARY = (
    # Occupations and roles
    "singer",
    "songwriter",
    "musician",
    "composer",
    "recording artist",
    "country singer",
    "pop singer",
    "rock singer",
    "latin singer",
    "ranchera singer",
    "television host",
    "radio host",
    "disc jockey",
    "producer",
    "actor",
    "actress",
    "band",
    "group",

    # Nationality / regional anchors frequently used by TopSpot
    "american",
    "mexican",
    "brazilian",
    "puerto rican",
    "cuban",
    "colombian",
    "argentine",
    "argentinian",
    "spanish",
    "british",
    "canadian",
    "italian",
    "german",
    "austrian",
    "french",

    # Music identity anchors
    "country",
    "rock and roll",
    "rock",
    "pop",
    "latin pop",
    "ranchera",
    "mariachi",
    "soul",
    "rhythm and blues",
    "r&b",
    "jazz",
    "blues",
    "folk",
    "classical",
    "television",
    "radio",
)


@dataclass(frozen=True)
class HistoricalIdentity:
    canonical_name: str
    display_name: str
    source_type: str
    source_id: int
    identity_terms: tuple[str, ...]
    aliases: tuple[str, ...]
    negative_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> HistoricalIdentity:
        return cls(
            canonical_name=str(payload["canonical_name"]),
            display_name=str(payload["display_name"]),
            source_type=str(payload["source_type"]),
            source_id=int(payload["source_id"]),
            identity_terms=tuple(
                str(value)
                for value in payload.get(
                    "identity_terms",
                    [],
                )
            ),
            aliases=tuple(
                str(value)
                for value in payload.get(
                    "aliases",
                    [],
                )
            ),
            negative_terms=tuple(
                str(value)
                for value in payload.get(
                    "negative_terms",
                    [],
                )
            ),
        )


def normalized_text(value: str) -> str:
    folded = unicodedata.normalize(
        "NFKD",
        value.casefold(),
    )
    ascii_text = folded.encode(
        "ascii",
        "ignore",
    ).decode("ascii")

    return " ".join(
        re.findall(
            r"[a-z0-9&'-]+",
            ascii_text,
        )
    )


def english_story(
    production: Production,
) -> str:
    documentary = production.documentary

    try:
        return documentary.story("en")
    except KeyError:
        if documentary.languages:
            return documentary.languages[0].story_text

    return ""


def extract_identity_terms(
    *,
    title: str,
    subtitle: str,
    story_text: str,
) -> tuple[str, ...]:
    source = normalized_text(
        " ".join(
            [
                title,
                subtitle,
                story_text[:5000],
            ]
        )
    )

    priority_terms = (
        "mexican",
        "american",
        "brazilian",
        "puerto rican",
        "cuban",
        "colombian",
        "argentine",
        "spanish",
        "british",
        "country singer",
        "latin singer",
        "ranchera singer",
        "pop singer",
        "rock singer",
        "singer",
        "television host",
        "radio host",
        "disc jockey",
        "band",
        "group",
        "latin pop",
        "ranchera",
        "mariachi",
        "country",
        "rock and roll",
        "soul",
        "jazz",
        "blues",
        "folk",
        "classical",
    )

    found: list[str] = []

    for term in priority_terms:
        normalized_term = normalized_text(term)

        if normalized_term in source:
            found.append(term)

    # Infer nationality only from strong identity phrases—not merely
    # because a country is mentioned somewhere in the biography.
    strong_identity_clues = {
        "el sol de mexico": "mexican",
        "mexican singer": "mexican",
        "mexican artist": "mexican",
        "puerto rican singer": "puerto rican",
        "brazilian singer": "brazilian",
        "colombian singer": "colombian",
        "argentine singer": "argentine",
        "cuban singer": "cuban",
        "spanish singer": "spanish",
        "british singer": "british",
        "american singer": "american",
    }

    for clue, identity_term in strong_identity_clues.items():
        if (
            normalized_text(clue) in source
            and identity_term not in found
        ):
            found.insert(0, identity_term)

    # Keep only the strongest anchors. Generic roles such as composer
    # and producer are deliberately excluded.
    return tuple(found[:4])


def extract_aliases(
    *,
    title: str,
    story_text: str,
) -> tuple[str, ...]:
    aliases: list[str] = []

    # Capture phrases presented as a known nickname:
    # known as "El Sol de México"
    patterns = (
        r'known as[,\s]+"([^"]{2,80})"',
        r'known as[,\s]+“([^”]{2,80})”',
        r'nicknamed[,\s]+"([^"]{2,80})"',
        r'nicknamed[,\s]+“([^”]{2,80})”',
        r'called[,\s]+"([^"]{2,80})"',
        r'called[,\s]+“([^”]{2,80})”',
        r'nickname(?:\s+fits)?[^.]{0,120}?'
        r'\b(El\s+Sol\s+de\s+M[eé]xico)\b',
        r'\b(?:he|she)\s+is\s+'
        r'(El\s+Sol\s+de\s+M[eé]xico)\b',
        r'\b(?:called|known as|nicknamed)\s+'
        r'(El\s+Sol\s+de\s+M[eé]xico)\b',
    )

    for pattern in patterns:
        for match in re.findall(
            pattern,
            story_text,
            flags=re.IGNORECASE,
        ):
            alias = " ".join(match.split()).strip()

            if (
                alias
                and alias.casefold() != title.casefold()
                and alias not in aliases
            ):
                aliases.append(alias)

    return tuple(aliases[:5])


def build_identity(
    production: Production,
) -> HistoricalIdentity:
    documentary = production.documentary
    story_text = english_story(production)

    aliases = extract_aliases(
        title=documentary.title,
        story_text=story_text,
    )

    identity_terms = list(
        extract_identity_terms(
            title=documentary.title,
            subtitle=documentary.subtitle,
            story_text=story_text,
        )
    )

    alias_text = normalized_text(
        " ".join(aliases)
    )

    if (
        "el sol de mexico" in alias_text
        and "mexican" not in identity_terms
    ):
        identity_terms.insert(0, "mexican")

    # Remove weak genre words unless they appear as a strong identity
    # phrase. They are too noisy for person disambiguation.
    weak_terms = {
        "soul",
        "pop",
        "rock",
        "television",
        "radio",
    }

    identity_terms = [
        term
        for term in identity_terms
        if term not in weak_terms
    ]

    # Keep the profile compact and high-signal.
    identity_terms = identity_terms[:4]

    return HistoricalIdentity(
        canonical_name=documentary.title.strip(),
        display_name=documentary.title.strip(),
        source_type=documentary.source_type,
        source_id=documentary.source_id,
        identity_terms=tuple(identity_terms),
        aliases=aliases,
        negative_terms=(),
    )


def identity_path(
    production: Production,
) -> Path:
    return (
        production.work_root
        / "historical_identity.json"
    )


def save_identity(
    path: Path,
    identity: HistoricalIdentity,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(".json.tmp")

    temporary.write_text(
        json.dumps(
            identity.to_dict(),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def load_or_build_identity(
    production: Production,
    *,
    force: bool = False,
) -> HistoricalIdentity:
    path = identity_path(production)

    if path.exists() and not force:
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )

            if isinstance(payload, dict):
                return HistoricalIdentity.from_dict(
                    payload
                )

        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            pass

    identity = build_identity(production)
    save_identity(path, identity)

    return identity


def strengthen_query(
    query: str,
    identity: HistoricalIdentity,
) -> str:
    parts: list[str] = [
        identity.canonical_name,
    ]

    # Three strong identity terms are normally enough to disambiguate
    # the subject without overwhelming the scene-specific phrase.
    parts.extend(identity.identity_terms[:3])

    cleaned_query = " ".join(query.split()).strip()

    if cleaned_query:
        parts.append(cleaned_query)

    combined: list[str] = []
    seen: set[str] = set()

    for part in parts:
        cleaned = " ".join(part.split()).strip()
        key = cleaned.casefold()

        if cleaned and key not in seen:
            combined.append(cleaned)
            seen.add(key)

    return " ".join(combined)


def build_search_queries(
    query: str,
    identity: HistoricalIdentity,
) -> list[str]:
    """
    Build several concise archive queries instead of one over-constrained
    query. Identity-aware ranking evaluates the combined results.
    """
    original = " ".join(query.split()).strip()

    strongest_terms = list(
        identity.identity_terms[:2]
    )

    candidates = [
        original,
        " ".join(
            [
                identity.canonical_name,
                original,
            ]
        ),
        " ".join(
            [
                identity.canonical_name,
                *strongest_terms,
            ]
        ),
        identity.canonical_name,
    ]

    for alias in identity.aliases[:2]:
        candidates.append(
            " ".join(
                [
                    identity.canonical_name,
                    alias,
                ]
            )
        )

    queries: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        cleaned = " ".join(candidate.split()).strip()
        key = cleaned.casefold()

        if cleaned and key not in seen:
            queries.append(cleaned)
            seen.add(key)

    return queries
