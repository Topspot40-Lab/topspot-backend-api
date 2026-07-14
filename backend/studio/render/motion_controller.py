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
    """
    Complete camera-motion decision for one documentary shot.

    The renderer does not need to know why a motion was selected.
    It only consumes the resulting FFmpeg expressions.
    """

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


def select_motion(
    *,
    shot_number: int,
    total_frames: int,
    duration: float,
) -> MotionDecision:
    """
    Choose a deterministic Ken Burns camera move.

    Version 1 of the controller deliberately preserves the approved V2
    sequence and motion strength. Future versions can consider storyboard
    content, image composition, scene emotion, or previous motions here
    without changing the renderer.
    """
    if shot_number < 1:
        raise ValueError("shot_number must be at least 1")

    if total_frames < 2:
        raise ValueError("total_frames must be at least 2")

    if duration <= 0:
        raise ValueError("duration must be greater than zero")

    last_frame = total_frames - 1
    kind = MOTION_SEQUENCE[
        (shot_number - 1) % len(MOTION_SEQUENCE)
    ]

    if kind is MotionKind.ZOOM_IN:
        return MotionDecision(
            kind=kind,
            name="zoom in",
            zoom_expression=f"1.0+0.08*on/{last_frame}",
            x_expression="iw/2-(iw/zoom/2)",
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.ZOOM_OUT:
        return MotionDecision(
            kind=kind,
            name="zoom out",
            zoom_expression=f"1.08-0.08*on/{last_frame}",
            x_expression="iw/2-(iw/zoom/2)",
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.PAN_LEFT_TO_RIGHT:
        return MotionDecision(
            kind=kind,
            name="pan left to right",
            zoom_expression="1.08",
            x_expression=f"(iw-iw/zoom)*on/{last_frame}",
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.PAN_RIGHT_TO_LEFT:
        return MotionDecision(
            kind=kind,
            name="pan right to left",
            zoom_expression="1.08",
            x_expression=(
                f"(iw-iw/zoom)*(1-on/{last_frame})"
            ),
            y_expression="ih/2-(ih/zoom/2)",
        )

    if kind is MotionKind.PAN_TOP_TO_BOTTOM:
        return MotionDecision(
            kind=kind,
            name="pan top to bottom",
            zoom_expression="1.08",
            x_expression="iw/2-(iw/zoom/2)",
            y_expression=f"(ih-ih/zoom)*on/{last_frame}",
        )

    return MotionDecision(
        kind=MotionKind.PAN_BOTTOM_TO_TOP,
        name="pan bottom to top",
        zoom_expression="1.08",
        x_expression="iw/2-(iw/zoom/2)",
        y_expression=(
            f"(ih-ih/zoom)*(1-on/{last_frame})"
        ),
    )
