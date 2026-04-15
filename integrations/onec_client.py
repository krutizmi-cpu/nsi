from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import NsiItem


@dataclass
class NomenclatureRow:
    """DTO обмена с 1С — расширяйте по мере появления HTTP-сервиса."""

    article: str
    name: str
    external_id: str | None
    barcode: str | None
    tnved_code: str | None
    vat_rate_percent: float | None = None
    length_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    weight_kg: float | None = None
    volume_m3: float | None = None
    supplier_parser_id: str | None = None


class OneCClient(Protocol):
    def fetch_nomenclature(self, session: Session, since: datetime | None) -> list[NomenclatureRow]:
        ...

    def upsert_item(self, session: Session, row: NomenclatureRow) -> str:
        """Возвращает external_id в системе 1С (или локальный surrogate)."""
        ...


class LocalOneCClient:
    """Заглушка: «интеграция» = чтение/запись той же БД НСИ."""

    def fetch_nomenclature(self, session: Session, since: datetime | None) -> list[NomenclatureRow]:
        q = select(NsiItem).order_by(NsiItem.id)
        items = session.execute(q).scalars().all()
        return [
            NomenclatureRow(
                article=i.article,
                name=i.name,
                external_id=i.external_id or str(i.id),
                barcode=i.barcode,
                tnved_code=i.tnved_code,
                vat_rate_percent=i.vat_rate_percent,
                length_mm=i.length_mm,
                width_mm=i.width_mm,
                height_mm=i.height_mm,
                weight_kg=i.weight_kg,
                volume_m3=i.volume_m3,
                supplier_parser_id=i.supplier_parser_id,
            )
            for i in items
        ]

    def upsert_item(self, session: Session, row: NomenclatureRow) -> str:
        existing = session.execute(select(NsiItem).where(NsiItem.article == row.article)).scalar_one_or_none()
        if existing:
            existing.name = row.name
            existing.barcode = row.barcode
            existing.tnved_code = row.tnved_code
            existing.vat_rate_percent = row.vat_rate_percent
            existing.length_mm = row.length_mm
            existing.width_mm = row.width_mm
            existing.height_mm = row.height_mm
            existing.weight_kg = row.weight_kg
            existing.volume_m3 = row.volume_m3
            existing.supplier_parser_id = row.supplier_parser_id
            if row.external_id:
                existing.external_id = row.external_id
            session.flush()
            return existing.external_id or str(existing.id)
        item = NsiItem(
            article=row.article,
            name=row.name[:100],
            barcode=row.barcode,
            tnved_code=row.tnved_code,
            vat_rate_percent=row.vat_rate_percent,
            length_mm=row.length_mm,
            width_mm=row.width_mm,
            height_mm=row.height_mm,
            weight_kg=row.weight_kg,
            volume_m3=row.volume_m3,
            supplier_parser_id=row.supplier_parser_id,
            external_id=row.external_id,
            source="local_onec_stub",
        )
        session.add(item)
        session.flush()
        return item.external_id or str(item.id)


def get_default_onec_client() -> OneCClient:
    return LocalOneCClient()
