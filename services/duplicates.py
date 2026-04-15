from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from config import DUPLICATE_SIMILARITY_THRESHOLD
from models import DuplicateCandidate, NsiItem
from rapidfuzz import fuzz


def find_similar_items(session: Session, name: str, exclude_id: int | None = None) -> list[tuple[NsiItem, float]]:
    """Возвращает пары (позиция, score 0..1) выше порога."""
    rows = session.execute(select(NsiItem.id, NsiItem.name)).all()
    out: list[tuple[NsiItem, float]] = []
    name_clean = (name or "").strip()
    if not name_clean:
        return out

    for pid, pname in rows:
        if exclude_id is not None and pid == exclude_id:
            continue
        score = fuzz.token_sort_ratio(name_clean, (pname or "").strip()) / 100.0
        if score >= DUPLICATE_SIMILARITY_THRESHOLD:
            item = session.get(NsiItem, pid)
            if item:
                out.append((item, score))
    out.sort(key=lambda x: -x[1])
    return out


def _ensure_duplicate_row(session: Session, a: int, b: int, score: float, reason: str) -> None:
    exists = session.execute(
        select(DuplicateCandidate.id).where(
            DuplicateCandidate.item_id_1 == a,
            DuplicateCandidate.item_id_2 == b,
            DuplicateCandidate.reason == reason,
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(
            DuplicateCandidate(
                item_id_1=a,
                item_id_2=b,
                similarity_score=score,
                reason=reason,
            )
        )


def record_duplicate_candidates(
    session: Session,
    new_item: NsiItem,
    similar: list[tuple[NsiItem, float]],
) -> None:
    for other, score in similar:
        a, b = sorted([new_item.id, other.id])
        _ensure_duplicate_row(session, a, b, score, "name_fuzzy")


def refresh_duplicates_for_item(session: Session, item_id: int) -> None:
    item = session.get(NsiItem, item_id)
    if not item:
        return
    session.execute(
        delete(DuplicateCandidate).where(
            (DuplicateCandidate.item_id_1 == item_id) | (DuplicateCandidate.item_id_2 == item_id)
        )
    )
    similar = find_similar_items(session, item.name, exclude_id=item_id)
    record_duplicate_candidates(session, item, similar)
