"""SQLite schema for tender / lot / supplier / KTRU / ST-KZ data."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


class Tender(Base):
    """Закупка верхнего уровня (объявление)."""

    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), index=True)  # 'goszakup' | 'samruk'
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    number_anno: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(Text)
    customer_bin: Mapped[str | None] = mapped_column(String(16), index=True)
    customer_name: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(String(64))  # способ закупки
    status: Mapped[str | None] = mapped_column(String(64))
    total_sum: Mapped[float | None] = mapped_column(Float)
    publish_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)
    raw_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lots: Mapped[list["Lot"]] = relationship(back_populates="tender", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_tender_source_extid"),
        Index("ix_tender_publish_source", "source", "publish_date"),
    )


class Lot(Base):
    """Лот тендера — конкретная позиция с привязкой к КТРУ."""

    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    number: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    ktru_code: Mapped[str | None] = mapped_column(String(32), index=True)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    price_per_unit: Mapped[float | None] = mapped_column(Float)
    total_sum: Mapped[float | None] = mapped_column(Float)
    country_origin: Mapped[str | None] = mapped_column(String(8), index=True)  # ISO-2: KZ / RU / CN / ...
    status: Mapped[str | None] = mapped_column(String(64))
    winner_bin: Mapped[str | None] = mapped_column(String(16), index=True)
    winner_name: Mapped[str | None] = mapped_column(Text)
    is_st_kz_available: Mapped[bool | None] = mapped_column(Boolean, index=True)

    tender: Mapped[Tender] = relationship(back_populates="lots")

    __table_args__ = (UniqueConstraint("tender_id", "external_id", name="uq_lot_tender_extid"),)


class Supplier(Base):
    """Поставщик/победитель (БИН/ИИН)."""

    __tablename__ = "suppliers"

    bin: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(8))
    is_resident: Mapped[bool | None] = mapped_column(Boolean)


class KtruItem(Base):
    """Справочник КТРУ (Каталог товаров, работ, услуг РК)."""

    __tablename__ = "ktru"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_ru: Mapped[str | None] = mapped_column(Text)
    name_kz: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64))
    parent_code: Mapped[str | None] = mapped_column(String(32), index=True)
    is_goods: Mapped[bool] = mapped_column(Boolean, default=True)


class StKzCertificate(Base):
    """Реестр индустриальных сертификатов СТ-KZ.

    Если по коду КТРУ есть хотя бы один действующий СТ-KZ — товар уже
    производится в РК, локализация не нужна.
    """

    __tablename__ = "st_kz_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    certificate_no: Mapped[str] = mapped_column(String(64), unique=True)
    producer_bin: Mapped[str] = mapped_column(String(16), index=True)
    producer_name: Mapped[str | None] = mapped_column(Text)
    ktru_code: Mapped[str | None] = mapped_column(String(32), index=True)
    product_name: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    local_content_pct: Mapped[float | None] = mapped_column(Float)


def get_engine(db_path: Path | None = None):
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


def init_db(engine=None) -> None:
    engine = engine or get_engine()
    Base.metadata.create_all(engine)


def make_session(engine=None) -> sessionmaker:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)


def bulk_upsert_lots(session, lots: Iterable[dict]) -> int:
    """Простой UPSERT по (tender_id, external_id)."""
    n = 0
    for payload in lots:
        existing = (
            session.query(Lot)
            .filter_by(tender_id=payload["tender_id"], external_id=payload["external_id"])
            .one_or_none()
        )
        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
        else:
            session.add(Lot(**payload))
        n += 1
    return n
