from __future__ import annotations

"""
Импорт выгрузки номенклатуры 1С из Excel (ручной файл).

Колонки ищутся по «гибким» заголовкам (регистр и пробелы не важны).
При необходимости расширьте `COLUMN_ALIASES` под ваш шаблон выгрузки.
"""

import io
import re
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from config import EXCEL_IMPORT_BATCH_PREFIX
from models import OnecCatalogEntry

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "code_1c": ("код", "код номенклатуры", "article", "артикул", "код 1с"),
    "name": ("наименование", "название", "name", "номенклатура"),
    "group_path": ("группа", "путь", "группа номенклатуры", "parent", "иерархия", "полное имя"),
    "tnved_code": ("тн вэд", "тнвэд", "tnved", "код тн вэд"),
    "vat_rate_percent": ("ндс", "ставка ндс", "vat", "% ндс", "налог"),
}


def _norm(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _find_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    headers = {c: _norm(c) for c in df.columns}
    alias_set = {_norm(a) for a in aliases}
    for col, hn in headers.items():
        if hn in alias_set:
            return col
    for col, hn in headers.items():
        for a in alias_set:
            if a in hn or hn in a:
                return col
    return None


def import_onec_catalog_from_excel(
    session: Session,
    source: str | Path | BinaryIO,
    *,
    replace_all: bool = False,
) -> tuple[int, str | None]:
    """
    Читает первый лист Excel, сопоставляет колонки, пишет в `onec_catalog_entries`.
    Возвращает (количество строк, сообщение об ошибке).
    """
    try:
        if isinstance(source, (str, Path)):
            df = pd.read_excel(source, dtype=str)
        else:
            df = pd.read_excel(source, dtype=str)
    except Exception as e:  # noqa: BLE001
        return 0, str(e)

    df = df.dropna(how="all")
    if df.empty:
        return 0, "Файл пустой или нет строк данных."

    col_map: dict[str, str] = {}
    for key, aliases in COLUMN_ALIASES.items():
        c = _find_column(df, aliases)
        if c:
            col_map[key] = c

    if "name" not in col_map and "code_1c" not in col_map:
        return (
            0,
            "Не найдены колонки с наименованием или кодом. Заголовки: "
            + ", ".join(str(c) for c in df.columns[:20]),
        )

    batch = f"{EXCEL_IMPORT_BATCH_PREFIX}{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    if replace_all:
        session.execute(delete(OnecCatalogEntry))

    n = 0
    for _, row in df.iterrows():
        code = str(row.get(col_map.get("code_1c", ""), "") or "").strip() if "code_1c" in col_map else ""
        name = str(row.get(col_map["name"], "") or "").strip() if "name" in col_map else ""
        if not name and not code:
            continue
        gpath = ""
        if "group_path" in col_map:
            gpath = str(row.get(col_map["group_path"], "") or "").strip()
        tnved = None
        if "tnved_code" in col_map:
            tnved = str(row.get(col_map["tnved_code"], "") or "").strip() or None
        vat = None
        if "vat_rate_percent" in col_map:
            raw = str(row.get(col_map["vat_rate_percent"], "") or "").strip()
            raw = raw.replace("%", "").replace(",", ".").strip()
            if raw:
                try:
                    vat = float(raw)
                except ValueError:
                    vat = None

        session.add(
            OnecCatalogEntry(
                code_1c=code or None,
                name=name or (code or "—"),
                group_path=gpath or None,
                tnved_code=tnved,
                vat_rate_percent=vat,
                import_batch=batch,
            )
        )
        n += 1

    session.flush()
    return n, None


def import_onec_catalog_from_bytes(
    session: Session,
    data: bytes,
    *,
    replace_all: bool = False,
) -> tuple[int, str | None]:
    return import_onec_catalog_from_excel(session, io.BytesIO(data), replace_all=replace_all)


def suggest_catalog_matches(session: Session, name: str, *, limit: int = 10) -> list[tuple[OnecCatalogEntry, float]]:
    """Подбор строк справочника 1С по похожести наименования (для группы / ТН ВЭД / НДС)."""
    from rapidfuzz import fuzz
    from sqlalchemy import select

    q = session.execute(select(OnecCatalogEntry)).scalars().all()
    if not q:
        return []
    needle = (name or "").strip()
    scored: list[tuple[OnecCatalogEntry, float]] = []
    for row in q:
        score = fuzz.token_sort_ratio(needle, (row.name or "").strip()) / 100.0
        scored.append((row, score))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]
