# backend/services/block_builder.py

import random
from backend.config.playback_block_config import (
    MIN_BLOCK_MINUTES,
    MAX_BLOCK_MINUTES,
    MIN_TRACKS_PER_BLOCK,
    MAX_TRACKS_PER_BLOCK,
    MS_PER_MINUTE,
)
import logging
logger = logging.getLogger(__name__)


def build_track_block(candidate_tracks):

    logger.info("🧪 candidate rows=%d", len(candidate_tracks))

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

        track_obj = row[0]  # first element of tuple
        duration_ms = getattr(track_obj, "duration_ms", None)

        if duration_ms is None or duration_ms <= 0:
            continue

        selected_tracks.append(row)
        total_ms += duration_ms

        if len(selected_tracks) >= MAX_TRACKS_PER_BLOCK:
            break

        if len(selected_tracks) >= MIN_TRACKS_PER_BLOCK and total_ms >= target_block_ms:
            break


    return selected_tracks