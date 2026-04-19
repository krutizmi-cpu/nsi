from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class NsiGroup(Base):
    __tablename__ = "nsi_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("nsi_groups.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    parent: Mapped[NsiGroup | None] = relationship(remote_side="NsiGroup.id", backref="children")
    items: Mapped[list["NsiItem"]] = relationship(back_populates="group")


class NsiItem(Base):
    __tablename__ = "nsi_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    group_id: Mapped[int | None] = mapped_column(ForeignKey("nsi_groups.id"), nullable=True, index=True)
    tnved_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    marking_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Ставка НДС, % (например 20, 10, 0) — уточняется вручную или из подсказки по ТН ВЭД
    vat_rate_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Канон: мм и кг; объём в м³ — пересчитывается при сохранении
    length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_m3: Mapped[float | None] = mapped_column(Float, nullable=True)

    # manual | supplier_site | peer_median | import
    dimensions_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    supplier_page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_parser_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    barcode: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # supplier_lookup | auto_lookup | gs1 | manual | not_found
    barcode_status: Mapped[str] = mapped_column(String(32), default="not_found", nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(128), nullable=True)
    needs_gs1_registration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), default="local", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow, nullable=True)

    group: Mapped[NsiGroup | None] = relationship(back_populates="items")
    images: Mapped[list["NsiItemImage"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="NsiItemImage.sort_order"
    )


class NsiItemImage(Base):
    __tablename__ = "nsi_item_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("nsi_items.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    item: Mapped[NsiItem] = relationship(back_populates="images")


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (UniqueConstraint("item_id_1", "item_id_2", "reason", name="uq_dup_pair_reason"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id_1: Mapped[int] = mapped_column(ForeignKey("nsi_items.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id_2: Mapped[int] = mapped_column(ForeignKey("nsi_items.id", ondelete="CASCADE"), nullable=False, index=True)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), default="name_fuzzy", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class OnecCatalogEntry(Base):
    """Строки ручной выгрузки номенклатуры 1С (Excel) для подбора группы / ТН ВЭД / НДС."""

    __tablename__ = "onec_catalog_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_1c: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    group_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    tnved_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    vat_rate_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    import_batch: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class BulkUploadTask(Base):
    """Задачи на массовую загрузку позиций из Excel с последующим парсингом."""

    __tablename__ = "bulk_upload_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_url: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(128), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(128), nullable=True)
    length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    # Результаты обработки
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending, processing, completed, failed
    parsed_length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_width_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_height_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_tnved_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parsed_barcode: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suggested_group_id: Mapped[int | None] = mapped_column(ForeignKey("nsi_groups.id"), nullable=True)
    suggested_group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parser_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Ссылка на созданную позицию
    created_item_id: Mapped[int | None] = mapped_column(ForeignKey("nsi_items.id"), nullable=True)
    
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    created_item: Mapped[NsiItem | None] = relationship()
    suggested_group: Mapped[NsiGroup | None] = relationship()
