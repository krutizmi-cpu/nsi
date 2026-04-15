from __future__ import annotations

"""
Статистические подсказки по габаритам: медиана по другим позициям в той же группе 1С/НСИ.
Нужно достаточно наблюдений, иначе возвращаем пусто.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import NsiItem

_MIN_SAMPLES = 3


def median(nums: list[float]) -> float | None:
    if not nums:
        return None
    s = sorted(nums)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (float(s[mid - 1]) + float(s[mid])) / 2.0


def suggest_peer_medians(
    session: Session,
    *,
    group_id: int | None,
    exclude_item_id: int | None = None,
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """
    Возвращает медианы (L,W,H мм, вес кг, объём м³) по позициям с заполненными полями в той же group_id.
    """
    if group_id is None:
        return None, None, None, None, None

    q = select(NsiItem).where(NsiItem.group_id == group_id)
    rows = session.execute(q).scalars().all()
    if exclude_item_id is not None:
        rows = [r for r in rows if r.id != exclude_item_id]

    def collect(attr: str) -> list[float]:
        out: list[float] = []
        for r in rows:
            v = getattr(r, attr, None)
            if v is not None:
                out.append(float(v))
        return out

    ls, ws, hs, wgs, vs = (
        collect("length_mm"),
        collect("width_mm"),
        collect("height_mm"),
        collect("weight_kg"),
        collect("volume_m3"),
    )
    if len(ls) < _MIN_SAMPLES:
        return None, None, None, None, None

    return median(ls), median(ws), median(hs), median(wgs) if len(wgs) >= _MIN_SAMPLES else None, median(vs) if len(vs) >= _MIN_SAMPLES else None
