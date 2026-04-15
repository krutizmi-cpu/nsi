from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BarcodeResolution:
    barcode: str | None
    status: str  # supplier_lookup | auto_lookup | gs1 | manual | not_found
    note: str


def resolve_barcode(
    *,
    supplier_barcode: str | None,
    manual_barcode: str | None,
) -> BarcodeResolution:
    """
    Цепочка: сначала данные поставщика, затем автопоиск (заглушка), затем ГС1 (заглушка).
    Пока: если есть ручной штрихкод — manual; иначе если есть у поставщика — supplier_lookup; иначе not_found.
    """
    if manual_barcode and manual_barcode.strip():
        return BarcodeResolution(manual_barcode.strip(), "manual", "Введён вручную")
    if supplier_barcode and supplier_barcode.strip():
        return BarcodeResolution(supplier_barcode.strip(), "supplier_lookup", "Из данных поставщика")
    # TODO: auto_lookup по внутреннему индексу, затем запрос к ГС1
    return BarcodeResolution(None, "not_found", "Автопоиск и ГС1 — в разработке")
