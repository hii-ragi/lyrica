"""LRC export, independent of the future alignment engine."""

import math
from decimal import Decimal, ROUND_HALF_UP


def render_lrc(lines: list[dict]) -> str:
    if not isinstance(lines, list) or not lines:
        raise ValueError("lines must be a non-empty list")
    output = []
    previous = -1.0
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("each line must be an object")
        start, text = line.get("start"), line.get("text")
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            raise ValueError("start must be a number")
        if not math.isfinite(start) or not 0 <= start <= 86400:
            raise ValueError("start must be between 0 and 86400 seconds")
        if start < previous:
            raise ValueError("timestamps must be in ascending order")
        if not isinstance(text, str) or any(char in text for char in "\r\n\x00"):
            raise ValueError("text must be a single line without NUL characters")
        # Decimal avoids binary float rounding errors at centisecond boundaries.
        centiseconds = int((Decimal(str(start)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        minutes, remainder = divmod(centiseconds, 6000)
        seconds, fraction = divmod(remainder, 100)
        output.append(f"[{minutes:02d}:{seconds:02d}.{fraction:02d}]{text}")
        previous = start
    return "\n".join(output) + "\n"
