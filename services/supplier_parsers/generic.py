from __future__ import annotations

import re

from bs4 import BeautifulSoup

from services.supplier_parsers.base import SupplierParseResult
from services.units import LengthUnit, WeightUnit, length_to_mm, weight_to_kg

_MM_TRIPLE = re.compile(
    r"(\d+[.,]?\d*)\s*[xх×]\s*(\d+[.,]?\d*)\s*[xх×]\s*(\d+[.,]?\d*)\s*(мм|mm|см|cm|м\b|m)",
    re.IGNORECASE,
)
_WEIGHT = re.compile(r"(\d+[.,]?\d*)\s*(кг|kg|г(?![а-яё])|g|lb|фунт)", re.IGNORECASE)
_TNVED = re.compile(r"(?:тн\s*вэд|тнвэд|tn\s*ved)[^\d]{0,24}(\d{8,10})\b", re.IGNORECASE)


def _parse_float(s: str) -> float:
    return float(s.replace(",", ".").strip())


def _dim_unit_from_suffix(suffix: str) -> LengthUnit:
    t = suffix.lower().strip()
    if t in ("мм", "mm"):
        return LengthUnit.MM
    if t in ("см", "cm"):
        return LengthUnit.CM
    if t in ("м", "m"):
        return LengthUnit.M
    return LengthUnit.MM


def _weight_from_match(m: re.Match[str]) -> float | None:
    val, suf = m.group(1), m.group(2)
    v = _parse_float(val)
    u = suf.lower()
    if u in ("кг", "kg"):
        return weight_to_kg(v, WeightUnit.KG)
    if u in ("г", "g"):
        return weight_to_kg(v, WeightUnit.G)
    if u in ("lb", "фунт"):
        return weight_to_kg(v, WeightUnit.LB)
    return None


class GenericSupplierParser:
    """Универсальный разбор: текст страницы + типовые шаблоны размеров/веса/ТН ВЭД."""

    id = "generic"

    def parse(self, html: str, url: str) -> SupplierParseResult:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        notes: list[str] = []
        length_mm = width_mm = height_mm = weight_kg = None
        tnved_code = None

        m = _MM_TRIPLE.search(text)
        if m:
            a, b, c, suf = m.groups()
            unit = _dim_unit_from_suffix(suf)
            length_mm = length_to_mm(_parse_float(a), unit)
            width_mm = length_to_mm(_parse_float(b), unit)
            height_mm = length_to_mm(_parse_float(c), unit)
            notes.append("Габариты: шаблон «A×B×C + единица» в тексте страницы.")

        wm = _WEIGHT.search(text)
        if wm:
            w = _weight_from_match(wm)
            if w is not None:
                weight_kg = w
                notes.append("Вес: найден в тексте.")

        tm = _TNVED.search(text)
        if tm:
            tnved_code = tm.group(1)[:10]
            notes.append("ТН ВЭД: найден рядом с маркером в тексте (проверьте).")

        if not notes:
            notes.append(
                "Парсер «generic»: типовые паттерны не найдены. Добавьте домен в "
                "`data/supplier_sites.json` и при необходимости свой модуль в `supplier_parsers/sites/`."
            )

        return SupplierParseResult(
            parser_id=self.id,
            length_mm=length_mm,
            width_mm=width_mm,
            height_mm=height_mm,
            weight_kg=weight_kg,
            tnved_code=tnved_code,
            notes=notes,
        )
