import random
from typing import Literal


def order_rows_for_mode(rows, mode: Literal["count_up", "count_down", "random"]):
    """
    Sort or shuffle rows according to playback mode.
    """
    if not rows:
        return rows

    if mode == "count_up":
        rows.sort(key=lambda r: r[2].ranking)
    elif mode == "count_down":
        rows.sort(key=lambda r: r[2].ranking, reverse=True)
    else:
        random.shuffle(rows)

    return rows
