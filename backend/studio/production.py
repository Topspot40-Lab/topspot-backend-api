from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.studio.studio_config import (
    PRODUCTIONS_DIR,
    WORK_DIR,
)


class Production:
    """
    Represents one TopSpot40 Studio production.

    Source metadata lives in:
        backend/studio/productions/<slug>/manifest.json

    Generated and downloaded media lives in:
        backend/studio/work/<slug>/
    """

    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.production_root = PRODUCTIONS_DIR / slug
        self.work_root = WORK_DIR / slug
        self.manifest_path = self.production_root / "manifest.json"

        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"Production manifest not found: {self.manifest_path}"
            )

        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict[str, Any]:
        try:
            return json.loads(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid production manifest JSON: {self.manifest_path}"
            ) from exc

    @property
    def title(self) -> str:
        return str(self.manifest["title"])

    @property
    def subtitle(self) -> str:
        return str(self.manifest.get("subtitle", ""))

    @property
    def docuseries_id(self) -> int | None:
        value = self.manifest.get("docuseries_id")
        return int(value) if value is not None else None

    @property
    def languages(self) -> list[dict[str, Any]]:
        return list(self.manifest.get("languages", []))

    def language(self, language_code: str) -> dict[str, Any]:
        for entry in self.languages:
            if entry.get("language_code") == language_code:
                return entry

        raise KeyError(
            f"Language not found in production "
            f"{self.slug}: {language_code}"
        )

    def card(self, name: str) -> Path:
        cards = self.manifest.get("cards", {})

        if name not in cards:
            raise KeyError(
                f"Card not found in production "
                f"{self.slug}: {name}"
            )

        return self.work_root / cards[name]

    def audio(self, language_code: str) -> Path:
        entry = self.language(language_code)
        local_audio = entry.get("local_audio")

        if not local_audio:
            raise KeyError(
                f"Local audio path missing for "
                f"{self.slug}: {language_code}"
            )

        return self.work_root / local_audio

    def output(self, name: str) -> Path:
        outputs = self.manifest.get("output", {})

        if name not in outputs:
            raise KeyError(
                f"Output not found in production "
                f"{self.slug}: {name}"
            )

        return self.work_root / outputs[name]

    def ensure_work_dirs(self) -> None:
        self.work_root.mkdir(parents=True, exist_ok=True)
        (self.work_root / "audio").mkdir(parents=True, exist_ok=True)
        (self.work_root / "cards").mkdir(parents=True, exist_ok=True)
        (self.work_root / "images").mkdir(parents=True, exist_ok=True)
        (self.work_root / "output").mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        """
        Return a list of missing required files.
        An empty list means the production is valid.
        """
        missing: list[str] = []

        for language in self.languages:
            language_code = language.get("language_code")

            if not language_code:
                missing.append("Manifest language entry missing language_code")
                continue

            try:
                audio_path = self.audio(str(language_code))
            except KeyError as exc:
                missing.append(str(exc))
                continue

            if not audio_path.exists():
                missing.append(str(audio_path))

        for card_name in ("logo", "languages", "title"):
            try:
                card_path = self.card(card_name)
            except KeyError as exc:
                missing.append(str(exc))
                continue

            if not card_path.exists():
                missing.append(str(card_path))

        return missing
