import asyncio
import logging
from typing import Optional

from spotipy.exceptions import SpotifyException
from backend.services.spotify.spotify_auth_user import get_spotify_user_client
from backend.state.playback_state import begin_track, status


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# Device Selection Helper (SYNC)
# ──────────────────────────────────────────────────────────
def _pick_device_id(sp, prefer_active: bool = True) -> Optional[str]:
    """
    Pick a Spotify device:
    - Prefer active device
    - Else fallback to first available
    """
    devices = sp.devices().get("devices", [])
    if not devices:
        return None

    if prefer_active:
        active = next((d for d in devices if d.get("is_active")), None)
        if active and active.get("id"):
            return active["id"]

    return devices[0].get("id")

async def ensure_spotify_ready(
    sp,
    preferred_device_id: str | None = None,
    *,
    device_attempts: int = 4,
    transfer_attempts: int = 3,
) -> str | None:
    """
    Find an available Spotify device, transfer playback to it if needed,
    and verify that Spotify reports it as active.

    Returns the ready device ID, or None when no device becomes ready.
    """

    chosen_device_id = preferred_device_id

    # Give mobile Spotify clients a few seconds to appear.
    for attempt in range(1, device_attempts + 1):
        devices = sp.devices().get("devices", [])

        logger.info(
            "🎧 Spotify device check %s/%s: %s",
            attempt,
            device_attempts,
            [
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "type": d.get("type"),
                    "active": d.get("is_active"),
                }
                for d in devices
            ],
        )

        if devices:
            if chosen_device_id:
                matching = next(
                    (
                        d for d in devices
                        if d.get("id") == chosen_device_id
                    ),
                    None,
                )

                if matching is None:
                    chosen_device_id = None

            if not chosen_device_id:
                active = next(
                    (
                        d for d in devices
                        if d.get("is_active") and d.get("id")
                    ),
                    None,
                )

                fallback = next(
                    (d for d in devices if d.get("id")),
                    None,
                )

                selected = active or fallback
                chosen_device_id = (
                    selected.get("id")
                    if selected
                    else None
                )

            if chosen_device_id:
                break

        await asyncio.sleep(0.75 * attempt)

    if not chosen_device_id:
        logger.error("🚫 No Spotify device became available.")
        return None

    # If it is already active, we are ready.
    devices = sp.devices().get("devices", [])
    selected = next(
        (
            d for d in devices
            if d.get("id") == chosen_device_id
        ),
        None,
    )

    if selected and selected.get("is_active"):
        logger.info(
            "✅ Spotify device already active: %s",
            selected.get("name"),
        )
        return chosen_device_id

    # Transfer and then verify. Spotify Connect can take a moment,
    # especially when waking a mobile app.
    for attempt in range(1, transfer_attempts + 1):
        try:
            logger.info(
                "🔄 Spotify transfer attempt %s/%s to device %s",
                attempt,
                transfer_attempts,
                chosen_device_id,
            )

            sp.transfer_playback(
                device_id=chosen_device_id,
                force_play=False,
            )

        except SpotifyException as exc:
            logger.warning(
                "⚠️ Spotify transfer attempt %s failed: %s",
                attempt,
                exc,
            )

        await asyncio.sleep(0.6 * attempt)

        devices = sp.devices().get("devices", [])
        selected = next(
            (
                d for d in devices
                if d.get("id") == chosen_device_id
            ),
            None,
        )

        if selected and selected.get("is_active"):
            logger.info(
                "✅ Spotify device ready: %s (%s)",
                selected.get("name"),
                chosen_device_id,
            )
            return chosen_device_id

    logger.error(
        "🚫 Spotify device never became active: %s",
        chosen_device_id,
    )
    return None


# ──────────────────────────────────────────────────────────
# Robust Spotify volume setter (ASYNC, but uses SYNC client)
# ──────────────────────────────────────────────────────────
async def set_device_volume(volume: int, device_id: str | None = None):
    sp = get_spotify_user_client()

    try:
        current = sp.current_playback()
        current_volume = current["device"]["volume_percent"] if current and current.get("device") else None

        # ✅ If already at target, do nothing
        if current_volume == volume:
            logger.debug(f"🔊 Spotify volume already at {volume}%, no change needed.")
            return

        sp.volume(volume, device_id=device_id)
        await asyncio.sleep(0.25)

        logger.debug(f"🔊 Spotify volume set to {volume}%")

    except SpotifyException as e:
        logger.warning(f"⚠️ Spotify volume set failed: {e}")


# ──────────────────────────────────────────────────────────
# INTERNAL async implementation
# ──────────────────────────────────────────────────────────
async def _play_spotify_track_async(track_id: str, device_id: Optional[str] = None) -> bool:
    try:
        client = get_spotify_user_client()

        device_id = await ensure_spotify_ready(
            client,
            preferred_device_id=device_id,
        )

        if not device_id:
            logger.error("🚫 Spotify playback aborted: no ready device.")
            return False

        # 🔥 START SPOTIFY PLAYBACK
        playback_started = False

        for attempt in range(1, 3):
            try:
                client.start_playback(
                    device_id=device_id,
                    uris=[f"spotify:track:{track_id}"],
                )
                playback_started = True
                break

            except SpotifyException as exc:
                logger.warning(
                    "⚠️ Spotify start attempt %s/2 failed: %s",
                    attempt,
                    exc,
                )

                if attempt < 2:
                    await asyncio.sleep(0.8)

        if not playback_started:
            logger.error(
                "🚫 Spotify could not start track after retries: %s",
                track_id,
            )
            return False

        # ⏱ ARM THE TRACK CLOCK HERE
        track = client.track(track_id)  # fetch metadata
        duration_sec = track["duration_ms"] / 1000

        begin_track(track_duration_seconds=duration_sec)

        logger.info(f"🎵 Track clock started: {duration_sec:.2f}s")

        # Spotify needs a brief pause before volume adjustment
        await asyncio.sleep(0.30)

        # Ensure main track plays at full volume
        await set_device_volume(100, device_id)

        logger.debug(f"🎵 Spotify track started at 100% volume: {track_id}")
        return True

    except SpotifyException as e:
        logger.error(f"❌ Failed to play Spotify track: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error in _play_spotify_track_async: {e}")
        return False



# ──────────────────────────────────────────────────────────
# PUBLIC API (LEGACY-SAFE SYNC WRAPPER)
# ──────────────────────────────────────────────────────────
async def play_spotify_track(track_id: str, device_id: Optional[str] = None) -> bool:
    return await _play_spotify_track_async(track_id, device_id)



# ──────────────────────────────────────────────────────────
# HARD STOP (for skip / next / prev)
# ──────────────────────────────────────────────────────────
def stop_spotify_track(*, device_id: Optional[str] = None) -> bool:
    """
    Immediate stop (pause) without fade — used for hard skip/next.
    """
    try:
        sp = get_spotify_user_client()

        chosen_device_id = device_id or _pick_device_id(sp, prefer_active=True)
        if not chosen_device_id:
            logger.debug("No device to stop.")
            return False

        sp.pause_playback(device_id=chosen_device_id)
        logger.info("⏸️ Spotify paused on device %s", chosen_device_id)
        return True

    except SpotifyException as e:
        # Spotify API-level failure (401, 404 device, etc.)
        logger.warning("⚠️ stop_spotify_track Spotify error: %s", e)
        return False
    except (ConnectionError, TimeoutError) as e:
        logger.warning("⚠️ stop_spotify_track network error: %s", e)
        return False


# ──────────────────────────────────────────────────────────
# SOFT STOP (Fade-Out) — with Spotify "restriction" safety patch
# ──────────────────────────────────────────────────────────
async def stop_spotify_playback(fade_out_seconds: float = 1.5, steps: int = 10) -> None:
    """
    Fade Spotify volume gradually to 0, then pause safely.
    Prevents 403 'Restriction violated' errors during fast transitions.
    """
    try:
        sp = get_spotify_user_client()

        # ──────────────────────────────────────────────
        # Locate active device
        # ──────────────────────────────────────────────
        devices = sp.devices().get("devices", [])
        if not devices:
            logger.debug("No Spotify devices found — nothing to fade.")
            return

        device = next((d for d in devices if d.get("is_active")), devices[0])
        device_id = device.get("id")

        logger.debug("🔉 Fading Spotify playback on %s (%s)", device.get("name"), device_id)

        # ──────────────────────────────────────────────
        # Determine starting volume safely
        # ──────────────────────────────────────────────
        pb = None
        current_vol = 100
        try:
            pb = sp.current_playback()
            if pb and pb.get("device"):
                current_vol = int(pb["device"].get("volume_percent") or 100)
        except Exception:
            pass

        # ──────────────────────────────────────────────
        # Fade loop
        # ──────────────────────────────────────────────
        steps = max(1, steps)
        delay = fade_out_seconds / steps
        decrement = max(1, current_vol // steps)

        vol = current_vol

        while vol > 0:
            vol = max(0, vol - decrement)
            try:
                sp.volume(vol, device_id=device_id)
            except Exception:
                break
            await asyncio.sleep(max(0.05, delay))

        # ──────────────────────────────────────────────
        # SAFE PAUSE — prevents Spotify 403 restriction errors
        # ──────────────────────────────────────────────
        try:
            # Refresh state right before pausing
            pb2 = sp.current_playback()

            # Only pause if Spotify reports "is_playing": True
            if pb2 and pb2.get("is_playing"):
                try:
                    sp.pause_playback(device_id=device_id)
                    logger.debug("⏸️ Fade-out complete.")
                except Exception as e:
                    # Spotify timing glitch — safe to ignore
                    if hasattr(e, "http_status") and e.http_status == 403:
                        logger.warning("⚠️ Spotify pause skipped due to timing restriction.")
                    else:
                        logger.warning("⚠️ Unexpected pause error: %s", e)
            else:
                logger.debug("Device already paused — skip pause call.")
        except Exception as inner:
            logger.warning("⚠️ safe pause check failed: %s", inner)

    except Exception as e:
        logger.warning("⚠️ stop_spotify_playback error: %s", e)

async def ensure_active_device():
    sp = get_spotify_user_client()
    devices = sp.devices().get("devices", [])
    if not devices:
        raise RuntimeError("No Spotify devices available")

    active = next((d for d in devices if d["is_active"]), None)
    if active:
        return

    # Activate the first device
    device_id = devices[0]["id"]
    sp.transfer_playback(device_id=device_id, force_play=True)
