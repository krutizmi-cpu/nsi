from __future__ import annotations

from services.supplier_parsers.base import SupplierParseResult
from services.supplier_parsers.page import fetch_and_parse_supplier_product
from services.supplier_parsers.registry import get_parser_for_url, reload_supplier_site_config, resolve_parser_id_for_url

__all__ = [
    "SupplierParseResult",
    "fetch_and_parse_supplier_product",
    "get_parser_for_url",
    "reload_supplier_site_config",
    "resolve_parser_id_for_url",
]
