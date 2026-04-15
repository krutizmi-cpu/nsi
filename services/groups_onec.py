from __future__ import annotations

"""Связь пути группы из выгрузки 1С с `NsiGroup` (последний сегмент пути → имя группы)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import NsiGroup


def ensure_group_from_onec_path(session: Session, group_path: str | None) -> int | None:
    if not group_path or not str(group_path).strip():
        return None
    raw = str(group_path).replace("\\", "/").strip()
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if not parts:
        return None
    name = parts[-1][:255]
    existing = session.execute(select(NsiGroup).where(NsiGroup.name == name)).scalar_one_or_none()
    if existing:
        return int(existing.id)
    g = NsiGroup(name=name, parent_id=None, external_id=None)
    session.add(g)
    session.flush()
    return int(g.id)
