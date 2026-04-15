from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"

# Локально: SQLite. На сервере: postgresql+psycopg://user:pass@host/db
DATABASE_URL = os.environ.get(
    "NSI_DATABASE_URL",
    f"sqlite:///{DATA_DIR / 'nsi.db'}",
)

NAME_MAX_LEN = 100
DUPLICATE_SIMILARITY_THRESHOLD = 0.85
ARTICLE_PREFIX_SUGGESTION = "ТСР"

# Префикс батча при импорте Excel из 1С (справочник в `onec_catalog_entries`)
EXCEL_IMPORT_BATCH_PREFIX = "1c_excel_"

# --- ТН ВЭД / НДС (РФ) ---
# JSON с правилами: префиксы 10%, точные коды, ставка по умолчанию.
TNVED_VAT_CONFIG_PATH = Path(
    os.environ.get("NSI_TNVED_VAT_CONFIG", str(DATA_DIR / "tnved_vat_ru.json"))
)
# Если задан URL, перед локальными правилами пробуется GET с подстановкой кода (см. services/tnved_vat.py).
TNVED_VAT_LOOKUP_URL = os.environ.get("NSI_TNVED_VAT_LOOKUP_URL", "").strip()
# Таймаут HTTP для подсказки НДС (сек).
TNVED_VAT_LOOKUP_TIMEOUT = float(os.environ.get("NSI_TNVED_VAT_LOOKUP_TIMEOUT", "8"))

# --- Парсеры сайтов поставщиков ---
SUPPLIER_SITES_CONFIG_PATH = Path(
    os.environ.get("NSI_SUPPLIER_SITES_CONFIG", str(DATA_DIR / "supplier_sites.json"))
)
SUPPLIER_FETCH_TIMEOUT = float(os.environ.get("NSI_SUPPLIER_FETCH_TIMEOUT", "15"))
