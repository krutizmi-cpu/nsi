from __future__ import annotations

"""Объём по габаритам в мм → м³."""


def volume_m3_from_mm(
    length_mm: float | None,
    width_mm: float | None,
    height_mm: float | None,
) -> float | None:
    if length_mm is None or width_mm is None or height_mm is None:
        return None
    if length_mm <= 0 or width_mm <= 0 or height_mm <= 0:
        return None
    mm3 = float(length_mm) * float(width_mm) * float(height_mm)
    return mm3 / 1_000_000_000.0
