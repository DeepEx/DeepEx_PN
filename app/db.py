import os
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = URL.create(
    "postgresql+psycopg",
    username=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    host=os.environ.get("POSTGRES_HOST", "db"),
    port=int(os.environ.get("POSTGRES_PORT", "5432")),
    database=os.environ["POSTGRES_DB"],
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Colonne aggiunte dopo la prima installazione: create_all non altera tabelle esistenti,
# quindi le aggiungiamo in modo idempotente all'avvio (PostgreSQL: ADD COLUMN IF NOT EXISTS).
PART_NUMBER_ADDED_COLUMNS = [
    ("massa_secco_g", "NUMERIC(12, 1)"),
    ("peso_acqua_g", "NUMERIC(12, 1)"),
    ("volume_cm3", "NUMERIC(14, 1)"),
    ("dim_lunghezza_mm", "NUMERIC(10, 1)"),
    ("dim_larghezza_mm", "NUMERIC(10, 1)"),
    ("dim_altezza_mm", "NUMERIC(10, 1)"),
    ("proprieta_fonte", "VARCHAR(20)"),
    ("proprieta_data", "DATE"),
    ("proprieta_note", "TEXT"),
]


def ensure_schema(bind=None):
    from sqlalchemy import text
    bind = bind or engine
    with bind.begin() as conn:
        for name, sql_type in PART_NUMBER_ADDED_COLUMNS:
            conn.execute(text(f"ALTER TABLE part_numbers ADD COLUMN IF NOT EXISTS {name} {sql_type}"))
