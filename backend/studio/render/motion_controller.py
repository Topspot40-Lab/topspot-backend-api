from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MotionKind(str, Enum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT_TO_RIGHT = "pan_left_to_right"
    PAN_RIGHT_TO_LEFT = "pan_right_to_left"
    PAN_TOP_TO_BOTTOM = "pan_top_to_bottom"
    PAN_BOTTOM_TO_TOP = "pan_bottom_to_top"


@dataclass(frozen=True)
class MotionDecision:
    kind: MotionKind
    name: str
    zoom_expression: str
    x_expression: str
    y_expression: str


MOTION_SEQUENCE: tuple[MotionKind, ...] = (
    MotionKind.ZOOM_IN,
    MotionKind.ZOOM_OUT,
    MotionKind.PAN_LEFT_TO_RIGHT,
    MotionKind.PAN_RIGHT_TO_LEFT,
    MotionKind.PAN_TOP_TO_BOTTOM,
    MotionKind.PAN_BOTTOM_TO_TOP,
)

EMOTIONAL_WORDS = {
    "emotion",
    "emotional",
    "tear",
    "tears",
    "cry",
    "crying",
    "heart",
    "heartbreak",
    "sorrow",
    "grief",
    "pain",
    "lonely",
    "intimate",
    "close-up",
    "close up",
    "face",
    "eyes",
    "reflective",
    "vulnerable",
}

WIDE_SCENE_WORDS = {
    "wide shot",
    "landscape",
    "highway",
    "road",
    "train",
    "crowd",
    "audience",
    "stadium",
    "arena",
    "plaza",
    "stage",
    "city",
    "countryside",
    "mountain",
    "building",
    "room",
    "studio",
}

VERTICAL_SCENE_WORDS = {
    "tower",
    "building",
    "full figure",
    "full body",
    "low-angle",
    "low angle",
    "high-angle",
    "high angle",
}


def _contains_any(
    text: str,
    terms: set[str],
) -> bool:
    return any(term in text for term in terms)


def _different_motion(
    preferred: MotionKind,
    previous_kind: MotionKind | None,
    shot_number: int,
) -> MotionKind:
    if preferred is not previous_kind:
        return preferred

    fallback_index = (
        MOTION_SEQUENCE.index(preferred) + 1
    ) % len(MOTION_SEQUENCE)

    fallback = MOTION_SEQUENCE[fallback_index]

    if fallback is previous_kind:
        fallback = MOTION_SEQUENCE[
            (shot_number + 1) % len(MOTION_SEQUENCE)
        ]

    return fallback


def _choose_motion_kind(
    *,
    shot_number: int,
    source_kind: str,
    scene_text: str,
    previous_kind: MotionKind | None,
) -> MotionKind:
    text = scene_text.casefold()
    source = source_kind.casefold()

    zoom_motions = {
        MotionKind.ZOOM_IN,
        MotionKind.ZOOM_OUT,
    }

    # Historical photographs receive conservative, predictable movement.
    # This rule takes priority over prompt keywords.
    if source == "historical":
        preferred = (
            MotionKind.ZOOM_IN
            if shot_number % 2
            else MotionKind.ZOOM_OUT
        )

    elif _contains_any(text, EMOTIONAL_WORDS):
        # Emotional scenes favor a push-in, but never create a long
        # zoom-in / zoom-out ping-pong sequence.
        if previous_kind in zoom_motions:
            preferred = (
                MotionKind.PAN_LEFT_TO_RIGHT
                if shot_number % 2
                else MotionKind.PAN_RIGHT_TO_LEFT
            )
        else:
            preferred = MotionKind.ZOOM_IN

    elif _contains_any(text, VERTICAL_SCENE_WORDS):
        preferred = (
            MotionKind.PAN_BOTTOM_TO_TOP
            if shot_number % 2
            else MotionKind.PAN_TOP_TO_BOTTOM
        )

    elif _contains_any(text, WIDE_SCENE_WORDS):
        preferred = (
            MotionKind.PAN_LEFT_TO_RIGHT
            if shot_number % 2
            else MotionKind.PAN_RIGHT_TO_LEFT
        )

    else:
        preferred = MOTION_SEQUENCE[
            (shot_number - 1) % len(MOTION_SEQUENCE)
        ]

    return _different_motion(
        preferred,
        previous_kind,
        shot_number,
    )


def select_motion(
    *,
    shot_number: int,
    total_frames: int,
    duration: float,
    source_kind: str = "AI",
    scene_text: str = "",
    previous_kind: MotionKind | None = None,
) -> MotionDecision:
    """
    Automatically choose a deterministic documentary camera move.

    Decisions use storyboard text, image source, duration, and the
    previous move. No manual scene configuration is required.
    """
    if shot_number < 1:
        raise ValueError("shot_number must be at least 1")

    if total_frames < 2:
        raise ValueError("total_frames must be at least 2")

    if duration <= 0:
        raise ValueError("duration must be greater than zero")

    last_frame = total_frames - 1

    kind = _choose_motion_kind(
        shot_number=shot_number,
        source_kind=source_kind,
        scene_text=scene_text,
        previous_kind=previous_kind,
    )

    # Historical photographs and long scenes receive gentler movement.
    if source_kind.casefold() == "historical":
        zoom_amount = 0.05
    elif duration >= 12.0:
        zoom_amount = 0.06
    else:
        zoom_amount = 0.08

    max_zoom = 1.0 + zoom_amount

    if kind is MotionKind.ZOOM_IN:
        return MotionDecision(
            kind=kind,
            name="automatic zoom in",
            zoom_expression=(
                f"1.0+{zoom_amount:.2f}*on/{last_frame}"
            ),
            x_expression="iw/2-(iw/zoom/2)",
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.ZOOM_OUT:
        return MotionDecision(
            kind=kind,
            name="automatic zoom out",
            zoom_expression=(
                f"{max_zoom:.2f}-"
                f"{zoom_amount:.2f}*on/{last_frame}"
            ),
            x_expression="iw/2-(iw/zoom/2)",
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.PAN_LEFT_TO_RIGHT:
        return MotionDecision(
            kind=kind,
            name="automatic pan left to right",
            zoom_expression=f"{max_zoom:.2f}",
            x_expression=f"(iw-iw/zoom)*on/{last_frame}",
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.PAN_RIGHT_TO_LEFT:
        return MotionDecision(
            kind=kind,
            name="automatic pan right to left",
            zoom_expression=f"{max_zoom:.2f}",
            x_expression=(
                f"(iw-iw/zoom)*(1-on/{last_frame})"
            ),
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.PAN_TOP_TO_BOTTOM:
        return MotionDecision(
            kind=kind,
            name="automatic pan top to bottom",
            zoom_expression=f"{max_zoom:.2f}",
            x_expression="iw/2-(iw/zoom/2)",
            y_expression=f"(ih-ih/zoom)*on/{last_frame}",
        )

    return MotionDecision(
        kind=MotionKind.PAN_BOTTOM_TO_TOP,
        name="automatic pan bottom to top",
        zoom_expression=f"{max_zoom:.2f}",
        x_expression="iw/2-(iw/zoom/2)",
        y_expression=(
            f"(ih-ih/zoom)*(1-on/{last_frame})"
        ),
    )
