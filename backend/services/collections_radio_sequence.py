from __future__ import annotations

import asyncio
import logging
import random

from backend.state.playback_state import status, mark_playing, update_phase
from backend.state.playback_flags import flags
from backend.state.narration import track_done_event
from backend.services.collections_radio_loader import get_valid_collections, load_collection_rows

logger = logging.getLogger(__name__)


async def run_collections_radio_sequence(
    *,
    tts_language: str = "en",
    collection_group_slug: str | None = None,
) -> None:
    selection = getattr(status, "selection", {}) or {}
    voices = selection.get("voices", [])

    play_intro = "intro" in voices
    play_detail = "detail" in voices
    play_artist = "artist" in voices

    logger.info(
        "🎛️ COLLECTIONS RADIO FLAGS | intro=%s detail=%s artist=%s",
        play_intro,
        play_detail,
        play_artist,
    )

    status.stopped = False
    status.cancel_requested = False
    status.language = tts_language

    flags.is_playing = True
    flags.stopped = False
    flags.cancel_requested = False
    flags.mode = "collections_radio"

    mark_playing(
        mode="collection",
        language=tts_language,
        context={
            "mode": "collections_radio",
            "collection_group_slug": collection_group_slug or "ALL",
        },
    )

    from backend.database import get_db_session

    try:
        with get_db_session() as session:
            collections = get_valid_collections(session, collection_group_slug)

        if not collections:
            logger.warning("No collections found for group=%s", collection_group_slug)
            return

        random.shuffle(collections)

        set_number = 0

        while True:
            for collection_meta in collections:
                if status.stopped:
                    logger.info("🛑 Collections radio stopped")
                    return

                set_number += 1

                collection_slug = collection_meta["collection_slug"]
                collection_name = collection_meta["collection_name"]
                group_slug = collection_meta["collection_group_slug"]
                group_name = collection_meta["collection_group_name"]

                logger.info(
                    "🎲 COLLECTION SET chosen: %s (%s)",
                    collection_name,
                    group_name,
                )

                update_phase(
                    "loading",
                    track_name="",
                    artist_name="",
                    context={
                        "mode": "collections_radio",
                        "collection_slug": collection_slug,
                        "collection_name": collection_name,
                        "collection_group_slug": group_slug,
                        "collection_group_name": group_name,
                        "set_number": set_number,
                    },
                )

                with get_db_session() as session:
                    rows = await asyncio.to_thread(load_collection_rows, session, collection_slug)

                if not rows:
                    logger.warning("No rows for collection=%s", collection_slug)
                    continue

                # For now: use all rows, or slice later if you want block sizing
                block_rows = rows

                for idx, (track, artist, ctr, collection) in enumerate(block_rows, start=1):
                    if status.stopped:
                        logger.info("🛑 Collections radio stopped")
                        return

                    rank = ctr.ranking
                    status.current_rank = rank
                    status.current_ranking_id = ctr.id
                    flags.current_rank = rank

                    radio_context = {
                        "mode": "collections_radio",
                        "collection_slug": collection_slug,
                        "collection_name": collection_name,
                        "collection_group_slug": group_slug,
                        "collection_group_name": group_name,
                        "set_number": set_number,
                        "block_size": len(block_rows),
                        "block_position": idx,
                        "ranking_id": ctr.id,
                        "album_artwork": getattr(track, "album_artwork", None),
                        "artist_artwork": getattr(artist, "artist_artwork", None),
                    }

                    # We'll wire liner / set_intro / intro-detail-artist / track next
                    logger.info(
                        "🎵 COLLECTION TRACK %d/%d | %s — %s",
                        idx,
                        len(block_rows),
                        track.track_name,
                        artist.artist_name,
                    )

                    # placeholder for now so structure is in place
                    if getattr(track, "spotify_track_id", None):
                        track_done_event.clear()

                        update_phase(
                            "track",
                            track_name=track.track_name,
                            artist_name=artist.artist_name,
                            current_rank=rank,
                            context={
                                **radio_context,
                                "mode": "spotify",
                                "spotify_track_id": track.spotify_track_id,

                                # ✅ ADD THESE
                                "collection_name": collection_name,
                                "collection_group_name": group_name,
                            },
                        )

                        await track_done_event.wait()

    except asyncio.CancelledError:
        logger.info("⛔ Collections radio cancelled")
        raise

    finally:
        flags.is_playing = False
        flags.stopped = True
        logger.info("📻 Collections radio stopped")