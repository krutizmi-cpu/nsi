from __future__ import annotations

"""
Сервис массовой загрузки новых позиций из Excel с автоматическим парсингом данных.

1. Загрузка Excel-файла с колонками:
   - supplier_article (артикул поставщика) - обязательно
   - name (наименование) - обязательно  
   - supplier_name (наименование поставщика) - обязательно
   - supplier_url (ссылка на сайт поставщика) - обязательно
   - barcode (штрихкод) - необязательно
   - length_mm, width_mm, height_mm, weight_kg - необязательно

2. Для каждой строки создаётся задача BulkUploadTask со статусом "pending"

3. Обработка задач:
   - Парсинг страницы поставщика для получения габаритов/веса/ТН ВЭД
   - Определение категории (группы) по схожести наименования с существующей базой
   - Создание позиции NsiItem после успешной обработки
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import BulkUploadTask, NsiGroup, NsiItem
from services.supplier_parsers import SupplierParseResult, fetch_and_parse_supplier_product
from services.onec_excel import suggest_catalog_matches


@dataclass
class BulkUploadRow:
    """Данные одной строки из Excel для массовой загрузки."""
    supplier_article: str
    name: str
    supplier_name: str
    supplier_url: str
    barcode: str | None = None
    length_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    weight_kg: float | None = None


@dataclass
class UploadValidationResult:
    """Результат валидации строки перед загрузкой."""
    ok: bool
    errors: list[str]
    row_data: BulkUploadRow | None = None


REQUIRED_COLUMNS = {
    "supplier_article": "Артикул поставщика",
    "name": "Наименование",
    "supplier_name": "Наименование поставщика", 
    "supplier_url": "Ссылка на сайт поставщика",
}

OPTIONAL_COLUMNS = {"barcode", "length_mm", "width_mm", "height_mm", "weight_kg"}


def validate_excel_columns(df: pd.DataFrame) -> tuple[bool, list[str]]:
    """Проверка наличия обязательных колонок в DataFrame."""
    missing = []
    for col, desc in REQUIRED_COLUMNS.items():
        if col not in df.columns:
            missing.append(f"Отсутствует обязательная колонка: {desc} ({col})")
    
    if missing:
        return False, missing
    
    return True, []


def validate_row(row: dict[str, Any]) -> UploadValidationResult:
    """Валидация отдельной строки данных."""
    errors = []
    
    # Проверка обязательных полей
    for col in REQUIRED_COLUMNS:
        val = row.get(col)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"Поле '{col}' не заполнено")
    
    if errors:
        return UploadValidationResult(ok=False, errors=errors)
    
    # Проверка URL
    url = str(row.get("supplier_url", "")).strip()
    if not url.startswith(("http://", "https://")):
        errors.append(f"Некорректный URL: {url}")
    
    if errors:
        return UploadValidationResult(ok=False, errors=errors)
    
    bulk_row = BulkUploadRow(
        supplier_article=str(row["supplier_article"]).strip(),
        name=str(row["name"]).strip(),
        supplier_name=str(row["supplier_name"]).strip(),
        supplier_url=url,
        barcode=str(row["barcode"]).strip() if row.get("barcode") else None,
        length_mm=float(row["length_mm"]) if pd.notna(row.get("length_mm")) else None,
        width_mm=float(row["width_mm"]) if pd.notna(row.get("width_mm")) else None,
        height_mm=float(row["height_mm"]) if pd.notna(row.get("height_mm")) else None,
        weight_kg=float(row["weight_kg"]) if pd.notna(row.get("weight_kg")) else None,
    )
    
    return UploadValidationResult(ok=True, errors=[], row_data=bulk_row)


def create_upload_task(
    session: Session,
    row: BulkUploadRow,
    batch_id: str,
) -> BulkUploadTask:
    """Создание задачи на обработку."""
    task = BulkUploadTask(
        supplier_name=row.supplier_name,
        supplier_url=row.supplier_url,
        supplier_article=row.supplier_article,
        barcode=row.barcode,
        length_mm=row.length_mm,
        width_mm=row.width_mm,
        height_mm=row.height_mm,
        weight_kg=row.weight_kg,
        status="pending",
        batch_id=batch_id,
    )
    session.add(task)
    return task


def process_upload_task(
    session: Session,
    task: BulkUploadTask,
) -> BulkUploadTask:
    """
    Обработка одной задачи массовой загрузки:
    1. Парсинг страницы поставщика
    2. Определение группы по базе
    3. Создание позиции NsiItem
    """
    from services.nomenclature import validate_article, validate_name
    from services.duplicates import find_similar_items, record_duplicate_candidates
    from services.dimensions_service import volume_m3_from_mm
    from services.tnved_vat import normalize_tnved, suggest_vat_percent_by_tnved
    from config import NAME_MAX_LEN
    
    try:
        task.status = "processing"
        session.flush()
        
        # 1. Парсинг страницы поставщика
        try:
            parse_result: SupplierParseResult = fetch_and_parse_supplier_product(task.supplier_url)
            task.parsed_length_mm = parse_result.length_mm
            task.parsed_width_mm = parse_result.width_mm
            task.parsed_height_mm = parse_result.height_mm
            task.parsed_weight_kg = parse_result.weight_kg
            task.parsed_tnved_code = parse_result.tnved_code
            task.parser_id = parse_result.parser_id
        except Exception as e:
            task.error_message = f"Ошибка парсинга: {str(e)}"
            task.status = "failed"
            session.flush()
            return task
        
        # 2. Определение группы по схожести наименования
        matches = suggest_catalog_matches(session, task.supplier_article, limit=5)
        if matches:
            best_match, score = matches[0]
            if score > 0.5:  # Порог схожести
                from services.groups_onec import ensure_group_from_onec_path
                group_id = ensure_group_from_onec_path(session, best_match.group_path)
                if group_id:
                    group = session.get(NsiGroup, group_id)
                    task.suggested_group_id = group_id
                    task.suggested_group_name = group.name if group else None
        
        # Если группа не найдена, используем группу по умолчанию
        if task.suggested_group_id is None:
            default_group = session.execute(
                select(NsiGroup).where(NsiGroup.parent_id.is_(None)).limit(1)
            ).scalar_one_or_none()
            if default_group:
                task.suggested_group_id = default_group.id
                task.suggested_group_name = default_group.name
        
        # 3. Подготовка данных для создания позиции
        article = task.supplier_article
        if not article.startswith("SUP-"):
            article = f"SUP-{article}"
        
        # Валидация артикула и наименования
        art_valid = validate_article(article)
        name_valid, name_msg = validate_name(task.supplier_article)
        
        if not art_valid.ok or not name_valid:
            task.error_message = f"Ошибка валидации: {art_valid.message or name_msg}"
            task.status = "failed"
            session.flush()
            return task
        
        # Использование распарсенных или загруженных данных
        length_mm = task.parsed_length_mm or task.length_mm
        width_mm = task.parsed_width_mm or task.width_mm
        height_mm = task.parsed_height_mm or task.height_mm
        weight_kg = task.parsed_weight_kg or task.weight_kg
        
        l_mm = length_mm if length_mm and length_mm > 0 else None
        w_mm = width_mm if width_mm and width_mm > 0 else None
        h_mm = height_mm if height_mm and height_mm > 0 else None
        w_kg = weight_kg if weight_kg and weight_kg > 0 else None
        volume = volume_m3_from_mm(l_mm, w_mm, h_mm)
        
        tnved = normalize_tnved(task.parsed_tnved_code)
        vat = suggest_vat_percent_by_tnved(tnved) if tnved else None
        
        # 4. Создание позиции
        item = NsiItem(
            article=article,
            name=task.supplier_article[:NAME_MAX_LEN],
            group_id=task.suggested_group_id,
            tnved_code=tnved,
            vat_rate_percent=vat,
            length_mm=l_mm,
            width_mm=w_mm,
            height_mm=h_mm,
            weight_kg=w_kg,
            volume_m3=volume,
            dimensions_source="bulk_upload",
            supplier_page_url=task.supplier_url,
            supplier_parser_id=task.parser_id,
            supplier_article=task.supplier_article,
            barcode=task.parsed_barcode or task.barcode,
            barcode_status="supplier_lookup" if task.parsed_barcode else "manual",
            source="bulk_upload",
        )
        session.add(item)
        session.flush()
        
        # Проверка на дубликаты
        similar = find_similar_items(session, item.name, exclude_id=item.id)
        record_duplicate_candidates(session, item, similar)
        
        task.created_item_id = item.id
        task.status = "completed"
        task.processed_at = datetime.utcnow()
        
    except Exception as e:
        task.error_message = f"Ошибка обработки: {str(e)}"
        task.status = "failed"
    
    session.flush()
    return task


def upload_excel_batch(
    session: Session,
    file_bytes: bytes,
    supplier_name_override: str | None = None,
) -> tuple[int, str | None]:
    """
    Загрузка Excel-файла и создание задач на обработку.
    
    Returns:
        (количество созданных задач, ошибка или None)
    """
    try:
        df = pd.read_excel(BytesIO(file_bytes), engine="openpyxl")
    except Exception as e:
        return 0, f"Ошибка чтения Excel: {str(e)}"
    
    # Проверка колонок
    valid, errors = validate_excel_columns(df)
    if not valid:
        return 0, "; ".join(errors)
    
    batch_id = str(uuid.uuid4())[:8]
    created_count = 0
    
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        
        # Переопределение имени поставщика если указано
        if supplier_name_override:
            row_dict["supplier_name"] = supplier_name_override
        
        validation = validate_row(row_dict)
        if not validation.ok:
            continue
        
        if validation.row_data:
            create_upload_task(session, validation.row_data, batch_id)
            created_count += 1
    
    return created_count, None


def get_pending_tasks(session: Session, limit: int = 100) -> list[BulkUploadTask]:
    """Получение задач ожидающих обработки."""
    return list(
        session.execute(
            select(BulkUploadTask)
            .where(BulkUploadTask.status == "pending")
            .order_by(BulkUploadTask.created_at)
            .limit(limit)
        ).scalars().all()
    )


def process_all_pending_tasks(session: Session) -> tuple[int, int]:
    """
    Обработка всех ожидающих задач.
    
    Returns:
        (успешно обработано, всего обработано)
    """
    tasks = get_pending_tasks(session)
    success_count = 0
    
    for task in tasks:
        processed_task = process_upload_task(session, task)
        if processed_task.status == "completed":
            success_count += 1
    
    session.commit()
    return success_count, len(tasks)


def get_bulk_upload_stats(session: Session, batch_id: str | None = None) -> dict[str, int]:
    """Статистика по задачам массовой загрузки."""
    query = select(
        BulkUploadTask.status,
        func.count(BulkUploadTask.id)
    ).group_by(BulkUploadTask.status)
    
    if batch_id:
        query = query.where(BulkUploadTask.batch_id == batch_id)
    
    results = session.execute(query).all()
    
    stats = {
        "total": sum(count for _, count in results),
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
    }
    
    for status, count in results:
        if status in stats:
            stats[status] = count
    
    return stats
