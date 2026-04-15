from __future__ import annotations

"""
Совместимость и тонкая обёртка: разбор страницы поставщика через реестр парсеров.

Новый код: `services.supplier_parsers.fetch_and_parse_supplier_product`.
"""

from services.supplier_parsers import SupplierParseResult, fetch_and_parse_supplier_product


def fetch_dimensions_from_supplier_url(url: str) -> SupplierParseResult:
    return fetch_and_parse_supplier_product(url)
