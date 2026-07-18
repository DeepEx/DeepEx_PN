from sqlalchemy import String, Integer, DateTime, ForeignKey, Numeric, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy import Boolean
from sqlalchemy import Numeric, ForeignKey
from sqlalchemy.orm import relationship

from db import Base

from decimal import Decimal
from datetime import datetime

from sqlalchemy.orm import joinedload



class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Abbreviation(Base):
    __tablename__ = "abbreviations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # CAT o TIPO
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    abbr: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("kind", "name", name="uq_abbr_kind_name"),
        UniqueConstraint("kind", "abbr", name="uq_abbr_kind_abbr"),
    )

class PNSequence(Base):
    __tablename__ = "pn_sequences"
    scope: Mapped[str] = mapped_column(String(80), primary_key=True)  # es "EL|PCB"
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    piva: Mapped[str | None] = mapped_column(String(40))
    indirizzo: Mapped[str | None] = mapped_column(String(250))
    citta: Mapped[str | None] = mapped_column(String(120))
    cap: Mapped[str | None] = mapped_column(String(20))
    nazione: Mapped[str | None] = mapped_column(String(80))
    sito_web: Mapped[str | None] = mapped_column(String(250))

    referente_nome: Mapped[str | None] = mapped_column(String(120))
    referente_email: Mapped[str | None] = mapped_column(String(200))
    referente_tel: Mapped[str | None] = mapped_column(String(50))
    iban: Mapped[str | None] = mapped_column(String(60))
    payment_terms: Mapped[str | None] = mapped_column(String(80))



class PartNumber(Base):
    __tablename__ = "part_numbers"
    pn: Mapped[str] = mapped_column(String(80), primary_key=True)

    cat_abbr: Mapped[str] = mapped_column(String(20), nullable=False)
    tipo_abbr: Mapped[str] = mapped_column(String(20), nullable=False)
    progressivo: Mapped[int] = mapped_column(Integer, nullable=False)

    rev: Mapped[str] = mapped_column(String(20), nullable=False)
    val: Mapped[str] = mapped_column(String(50), nullable=False)

    descrizione: Mapped[str | None] = mapped_column(String(500))

    classificazione: Mapped[str] = mapped_column(String(20), nullable=False, default="BUY")  # MAKE/BUY/STANDARD
    costo_standard: Mapped[float | None] = mapped_column(Numeric(12, 2))
    valuta: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")

    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("suppliers.id"))
    supplier_pn: Mapped[str | None] = mapped_column(String(120))

    stato: Mapped[str] = mapped_column(String(20), nullable=False, default="BOZZA")  # BOZZA/REVISIONE/RILASCIATO/OBSOLETO

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    supplier = relationship("Supplier")

    unita_misura: Mapped[str | None] = mapped_column(String(20))
    lead_time_giorni: Mapped[int | None] = mapped_column(Integer)
    moq: Mapped[int | None] = mapped_column(Integer)

    link: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)


class PNHistory(Base):
    __tablename__ = "pn_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pn: Mapped[str] = mapped_column(String(80), ForeignKey("part_numbers.pn"), nullable=False)
    ts: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text)



class BOMItem(Base):
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    parent_pn: Mapped[str] = mapped_column(String, ForeignKey("part_numbers.pn", ondelete="CASCADE"), nullable=False)
    child_pn: Mapped[str] = mapped_column(String, ForeignKey("part_numbers.pn", ondelete="RESTRICT"), nullable=False)

    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    scrap_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # opzionale: relazioni (comode nei template)
    parent: Mapped["PartNumber"] = relationship("PartNumber", foreign_keys=[parent_pn])
    child: Mapped["PartNumber"] = relationship("PartNumber", foreign_keys=[child_pn])
