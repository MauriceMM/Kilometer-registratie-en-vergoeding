"""Database setup en sessie-management."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/kmv.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables() -> None:
    """Maak alle tabellen aan als ze nog niet bestaan."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: geeft een database sessie terug."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
