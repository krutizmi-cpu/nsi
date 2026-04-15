"""
Шаблон своего парсера.

1. Скопируйте файл как `sites/myshop.py`.
2. Задайте `id = "myshop"`.
3. В `data/supplier_sites.json` укажите домен → `"myshop"`.
"""

from __future__ import annotations

from services.supplier_parsers.base import SupplierParseResult
from services.supplier_parsers.generic import GenericSupplierParser


class Parser(GenericSupplierParser):
    """Наследуйте Generic или пишите parse с нуля под вёрстку поставщика."""

    id = "template"
