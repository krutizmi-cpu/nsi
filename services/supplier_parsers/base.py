from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SupplierParseResult:
    """Результат разбора страницы товара у поставщика."""

    parser_id: str
    length_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    weight_kg: float | None = None
    tnved_code: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def raw_note(self) -> str:
        return " ".join(self.notes) if self.notes else ""


class SupplierProductParser(Protocol):
    id: str

    def parse(self, html: str, url: str) -> SupplierParseResult:
        ...
