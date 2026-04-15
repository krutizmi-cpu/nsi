from __future__ import annotations

"""Приведение габаритов и веса к канону НСИ: длина/ширина/высота в мм, вес в кг."""

from enum import Enum


class LengthUnit(str, Enum):
    MM = "mm"
    CM = "cm"
    M = "m"
    INCH = "inch"


class WeightUnit(str, Enum):
    KG = "kg"
    G = "g"
    LB = "lb"


def length_to_mm(value: float, unit: str | LengthUnit) -> float:
    u = unit if isinstance(unit, LengthUnit) else LengthUnit(str(unit).lower())
    v = float(value)
    if u == LengthUnit.MM:
        return v
    if u == LengthUnit.CM:
        return v * 10.0
    if u == LengthUnit.M:
        return v * 1000.0
    if u == LengthUnit.INCH:
        return v * 25.4
    raise ValueError(f"Неизвестная единица длины: {unit}")


def weight_to_kg(value: float, unit: str | WeightUnit) -> float:
    u = unit if isinstance(unit, WeightUnit) else WeightUnit(str(unit).lower())
    v = float(value)
    if u == WeightUnit.KG:
        return v
    if u == WeightUnit.G:
        return v / 1000.0
    if u == WeightUnit.LB:
        return v * 0.45359237
    raise ValueError(f"Неизвестная единица веса: {unit}")


def normalize_dimensions_mm(
    length: float | None,
    width: float | None,
    height: float | None,
    *,
    unit: str | LengthUnit,
) -> tuple[float | None, float | None, float | None]:
    if length is None and width is None and height is None:
        return None, None, None
    return (
        length_to_mm(length, unit) if length is not None else None,
        length_to_mm(width, unit) if width is not None else None,
        length_to_mm(height, unit) if height is not None else None,
    )


def normalize_weight_kg(value: float | None, *, unit: str | WeightUnit) -> float | None:
    if value is None:
        return None
    return weight_to_kg(value, unit)
