# backend/state/narration.py
from backend.state.playback_runtime import RuntimeEventProxy

narration_done_event = RuntimeEventProxy("narration_done_event")
track_done_event = RuntimeEventProxy("track_done_event")
