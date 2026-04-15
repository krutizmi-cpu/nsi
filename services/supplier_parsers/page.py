from __future__ import annotations

import httpx

from config import SUPPLIER_FETCH_TIMEOUT

from services.supplier_parsers.base import SupplierParseResult
from services.supplier_parsers.registry import get_parser_for_url


def fetch_and_parse_supplier_product(url: str) -> SupplierParseResult:
    headers = {"User-Agent": "NSI-Supplier/1.0 (+internal)"}
    with httpx.Client(follow_redirects=True, timeout=SUPPLIER_FETCH_TIMEOUT, headers=headers) as client:
        r = client.get(url)
        r.raise_for_status()
        html = r.text
    parser = get_parser_for_url(url)
    return parser.parse(html, url)
