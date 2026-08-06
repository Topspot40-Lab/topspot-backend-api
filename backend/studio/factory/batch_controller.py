"""Resumable orchestration for batches of canonical documentary factories."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from backend.database import engine
from backend.models.dbmodels import Artist, ArtistStory, MusicDocuseries
from backend.studio.documentary import Documentary, slugify
from backend.studio.factory.batch_state import (
    BatchItem,
    BatchLedger,
    BatchWorkflowLock,
    now,
)
from backend.studio.factory.documentary_factory import (
    concise_error_summary,
    create_documentary,
)
from backend.studio.factory.input_preflight import validate_factory_inputs
from backend.studio.stations.create_production import create_production
from backend.studio.studio_config import PRODUCTIONS_DIR, WORK_DIR

DEFAULT_BATCH_SIZE = 10
DEFAULT_LEDGER_PATH = WORK_DIR / "documentary_factory_batch.json"
_PARTIAL_DIRECTORY_REASON = "Production directory exists without manifest.json"


@dataclass(frozen=True, slots=True)
class DocumentarySource:
    source_type: str
    source_id: int
    slug: str
    documentary: Documentary | None
    discovery_error: str | None = None


@dataclass(frozen=True, slots=True)
class BatchRunResult:
    selected: int
    completed: int
    failed: int
    skipped: int
    dry_run: bool


Discovery = Callable[[], Iterable[DocumentarySource]]
ManifestCreator = Callable[[str, int], Path]
DocumentaryFactory = Callable[[str], object]
ProductionRoot = Callable[[str], Path]


def _create_manifest(source_type: str, source_id: int) -> Path:
    return create_production(source_type=source_type, source_id=source_id)


def _production_root(slug: str) -> Path:
    return PRODUCTIONS_DIR / slug


def discover_documentary_sources() -> tuple[DocumentarySource, ...]:
    """Read candidate source records without changing the configured database."""
    sources: list[DocumentarySource] = []
    with Session(engine) as database:
        docuseries = list(
            database.exec(
                select(MusicDocuseries)
                .where(MusicDocuseries.is_active == True)
                .order_by(MusicDocuseries.id)
            ).all()
        )
        artists = list(
            database.exec(
                select(Artist)
                .join(ArtistStory, ArtistStory.artist_id == Artist.id)
                .distinct()
                .order_by(Artist.id)
            ).all()
        )
    for item in docuseries:
        if item.id is not None:
            sources.append(_load_source("music_docuseries", int(item.id), item.slug))
    for artist in artists:
        if artist.id is not None:
            sources.append(
                _load_source("artist_story", int(artist.id), slugify(artist.artist_name))
            )
    return tuple(sources)


def _load_source(source_type: str, source_id: int, slug: str) -> DocumentarySource:
    try:
        documentary = Documentary.load(source_type=source_type, source_id=source_id)
    except (LookupError, ValueError) as exc:
        return DocumentarySource(
            source_type=source_type,
            source_id=source_id,
            slug=slug,
            documentary=None,
            discovery_error=concise_error_summary(exc),
        )
    return DocumentarySource(source_type, source_id, documentary.slug, documentary)


def _sort_key(source: DocumentarySource) -> tuple[int, int]:
    return (0 if source.source_type == "music_docuseries" else 1, source.source_id)


def _item_sort_key(item: BatchItem) -> tuple[int, int]:
    return (0 if item.source_type == "music_docuseries" else 1, item.source_id)


def _readiness(source: DocumentarySource) -> tuple[bool, str]:
    if source.discovery_error is not None:
        return False, source.discovery_error
    if source.documentary is None:
        return False, "Documentary source could not be loaded"
    try:
        validate_factory_inputs(source.documentary)
    except ValueError as exc:
        return False, concise_error_summary(exc)
    return True, "Eligible"


def _new_item(source: DocumentarySource, eligible: bool, reason: str) -> BatchItem:
    timestamp = now()
    return BatchItem(
        source_type=source.source_type,
        source_id=source.source_id,
        slug=source.slug,
        eligible=eligible,
        reason=reason,
        status="pending" if eligible else "skipped",
        attempts=0,
        created_at=timestamp,
        started_at=None,
        finished_at=None,
        updated_at=timestamp,
        error=None,
    )

def _current_identities(
    sources: Iterable[DocumentarySource],
) -> set[tuple[str, int]]:
    return {(source.source_type, source.source_id) for source in sources}



def _refresh_ledger(
    ledger: BatchLedger,
    sources: tuple[DocumentarySource, ...],
    *,
    retry_failed: bool,
    production_root: ProductionRoot,
) -> bool:
    """Refresh only current discoveries; absent ledger items remain inert."""
    changed = False
    current = _current_identities(sources)

    for identity in current:
        item = ledger.items.get(identity)
        if item is None:
            continue
        if item.status == "running":
            item.status = "pending"
            item.reason = "Interrupted batch invocation"
            item.error = "Interrupted before completion"
            item.started_at = None
            item.finished_at = None
            item.updated_at = now()
            changed = True
        elif item.status == "failed" and retry_failed:
            item.status = "pending"
            item.reason = "Retry requested"
            item.error = None
            item.finished_at = None
            item.updated_at = now()
            changed = True

    for source in sources:
        identity = (source.source_type, source.source_id)
        eligible, reason = _readiness(source)
        existing = ledger.items.get(identity)

        if existing is None:
            ledger.items[identity] = _new_item(source, eligible, reason)
            changed = True
            continue

        if (
            existing.status == "skipped"
            and existing.reason == _PARTIAL_DIRECTORY_REASON
        ):
            if (production_root(existing.slug) / "manifest.json").is_file():
                existing.status = "pending"
                existing.reason = reason
                existing.finished_at = None
                existing.error = None
                existing.updated_at = now()
                changed = True
            continue

        if (
            existing.slug != source.slug
            or existing.eligible != eligible
            or existing.reason != reason
        ):
            was_eligible = existing.eligible
            existing.slug = source.slug
            existing.eligible = eligible
            existing.reason = reason
            if existing.status == "skipped" and not was_eligible and eligible:
                existing.status = "pending"
                existing.finished_at = None
                existing.error = None
            elif existing.status == "pending" and not eligible:
                existing.status = "skipped"
                existing.finished_at = now()
            existing.updated_at = now()
            changed = True

    return changed


def _mark_partial_directory_conflicts(
        ledger: BatchLedger,
        current: set[tuple[str, int]],
        production_root: ProductionRoot,
) -> int:
    skipped = 0
    for identity in current:
        item = ledger.items[identity]
        root = production_root(item.slug)
        if item.eligible and item.status == "pending" and root.exists() and not (
                root / "manifest.json"
        ).is_file():
            item.status = "skipped"
            item.reason = _PARTIAL_DIRECTORY_REASON
            item.error = None
            item.finished_at = now()
            item.updated_at = item.finished_at
            skipped += 1
    return skipped


def _dry_run_selection(
        sources: tuple[DocumentarySource, ...],
        ledger: BatchLedger,
        *,
        batch_size: int,
        retry_failed: bool,
        production_root: ProductionRoot,
) -> tuple[DocumentarySource, ...]:
    selected: list[DocumentarySource] = []
    for source in sources:
        eligible, reason = _readiness(source)
        identity = (source.source_type, source.source_id)
        item = ledger.items.get(identity)
        if not eligible:
            print(f"SKIP {source.source_type}:{source.source_id} {source.slug}: {reason}")
            continue
        root = production_root(source.slug)
        manifest = root / "manifest.json"
        if root.exists() and not manifest.is_file():
            print(
                f"SKIP {source.source_type}:{source.source_id} {source.slug}: "
                f"{_PARTIAL_DIRECTORY_REASON}"
            )
            continue
        if item is not None and item.status == "completed":
            print(f"SKIP {source.source_type}:{source.source_id} {source.slug}: completed")
            continue
        if item is not None and item.status == "failed" and not retry_failed:
            print(f"SKIP {source.source_type}:{source.source_id} {source.slug}: failed")
            continue
        if len(selected) < batch_size:
            selected.append(source)
    for source in selected:
        action = (
            "run existing manifest"
            if (production_root(source.slug) / "manifest.json").is_file()
            else "create manifest and run"
        )
        print(f"PLAN {source.source_type}:{source.source_id} {source.slug}: {action}")
    return tuple(selected)


def run_batch(
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dry_run: bool = False,
        retry_failed: bool = False,
        ledger_path: Path = DEFAULT_LEDGER_PATH,
        discovery: Discovery = discover_documentary_sources,
        manifest_creator: ManifestCreator = _create_manifest,
        documentary_factory: DocumentaryFactory = create_documentary,
        production_root: ProductionRoot = _production_root,
) -> BatchRunResult:
    """Process up to ``batch_size`` current eligible sources in order."""
    if batch_size < 0:
        raise ValueError("batch_size must be non-negative")

    sources = tuple(sorted(discovery(), key=_sort_key))
    if dry_run:
        ledger = BatchLedger.load(ledger_path)
        selected = _dry_run_selection(
            sources,
            ledger,
            batch_size=batch_size,
            retry_failed=retry_failed,
            production_root=production_root,
        )
        return BatchRunResult(len(selected), 0, 0, 0, True)

    with BatchWorkflowLock(ledger_path):
        ledger = BatchLedger.load(ledger_path)
        current = _current_identities(sources)
        changed = _refresh_ledger(
            ledger,
            sources,
            retry_failed=retry_failed,
            production_root=production_root,
        )
        skipped = _mark_partial_directory_conflicts(ledger, current, production_root)
        if skipped:
            changed = True
        if changed:
            ledger.save()

        pending = sorted(
            (
                item
                for identity, item in ledger.items.items()
                if identity in current and item.eligible and item.status == "pending"
            ),
            key=_item_sort_key,
        )
        selected_items = pending[:batch_size]
        completed = 0
        failed = 0

        for item in selected_items:
            root = production_root(item.slug)
            manifest = root / "manifest.json"
            item.status = "running"
            item.attempts += 1
            item.started_at = now()
            item.finished_at = None
            item.error = None
            item.updated_at = item.started_at
            ledger.save()
            try:
                if not root.exists():
                    manifest_creator(item.source_type, item.source_id)
                if not manifest.is_file():
                    raise RuntimeError(
                        "Manifest creation did not produce expected manifest: "
                        f"{manifest}"
                    )
                documentary_factory(item.slug)
            except Exception as exc:
                item.status = "failed"
                item.error = concise_error_summary(exc)
                item.finished_at = now()
                item.updated_at = item.finished_at
                ledger.save()
                failed += 1
                continue

            item.status = "completed"
            item.error = None
            item.finished_at = now()
            item.updated_at = item.finished_at
            ledger.save()
            completed += 1

    return BatchRunResult(len(selected_items), completed, failed, skipped, False)


def _non_negative(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("batch size must be non-negative")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a resumable batch of canonical documentaries."
    )
    parser.add_argument("--batch-size", type=_non_negative, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--ledger-path", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = run_batch(
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        retry_failed=args.retry_failed,
        ledger_path=args.ledger_path or DEFAULT_LEDGER_PATH,
    )
    mode = "dry run" if result.dry_run else "completed"
    print(
        f"Batch {mode}: selected={result.selected} "
        f"completed={result.completed} failed={result.failed} skipped={result.skipped}"
    )


if __name__ == "__main__":
    main()
