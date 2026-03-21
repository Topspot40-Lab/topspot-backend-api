# backend/services/block_builder.py

import random
import logging
from backend.config.playback_block_config import (
    MIN_BLOCK_MINUTES,
    MAX_BLOCK_MINUTES,
    MIN_TRACKS_PER_BLOCK,
    MAX_TRACKS_PER_BLOCK,
    MS_PER_MINUTE,
)

logger = logging.getLogger(__name__)


def build_track_block(candidate_tracks, set_number: int = 1):

    if not candidate_tracks:
        return []

    shuffled_tracks = candidate_tracks[:]
    random.shuffle(shuffled_tracks)

    target_block_ms = random.randint(
        MIN_BLOCK_MINUTES * MS_PER_MINUTE,
        MAX_BLOCK_MINUTES * MS_PER_MINUTE,
    )

    selected_tracks = []
    total_ms = 0

    for row in shuffled_tracks:

        track_obj = row[0]
        duration_ms = getattr(track_obj, "duration_ms", None)

        if duration_ms is None or duration_ms <= 0:
            logger.warning("⚠️ Skipping track with bad duration: %s", track_obj)
            continue

        # ALWAYS add track first
        selected_tracks.append(row)
        total_ms += duration_ms

        # 🚫 FORCE minimum tracks FIRST
        if len(selected_tracks) < MIN_TRACKS_PER_BLOCK:
            continue

        # ✅ ONLY AFTER minimum → apply stop rules
        if total_ms >= target_block_ms:
            break

        if len(selected_tracks) >= MAX_TRACKS_PER_BLOCK:
            break

    # 🚑 HARD GUARANTEE minimum tracks
    if len(selected_tracks) < MIN_TRACKS_PER_BLOCK:
        logger.warning(
            "⚠️ Only %d tracks selected — forcing minimum fill",
            len(selected_tracks)
        )

        for row in shuffled_tracks:
            if row not in selected_tracks:
                track_obj = row[0]
                duration_ms = getattr(track_obj, "duration_ms", None)

                if duration_ms is None or duration_ms <= 0:
                    continue

                selected_tracks.append(row)

                if len(selected_tracks) >= MIN_TRACKS_PER_BLOCK:
                    break

    # Optional debug summary (quiet unless debug enabled)
    logger.debug(
        "build_track_block: candidates=%d selected=%d target=%.1f min",
        len(candidate_tracks),
        len(selected_tracks),
        target_block_ms / 60000,
    )

    return selected_tracks