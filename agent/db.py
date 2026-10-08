"""
agent/db.py — SQLAlchemy async engine + PostGIS model for attested polygons.

The attested_polygons table lets the duplicate/overlap check query previously
minted parcels via a spatial index (PostGIS GiST).

Run migrations with Alembic:
    alembic upgrade head
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agent.config import get_settings


def _make_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False
        )
    return _session_factory


async def get_session() -> AsyncSession:
    """FastAPI dependency: yields an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


# ─── ORM models ───────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class AttestedPolygon(Base):
    """
    Stores a record of every successfully attested land parcel.

    The `geom` column holds WKT of the polygon (EPSG:4326).  For full
    PostGIS spatial queries, migrate to a Geometry column type using
    GeoAlchemy2 and the alembic migration in alembic/versions/.
    """

    __tablename__ = "attested_polygons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    geom_wkt: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    asset_type: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attestation_json: Mapped[str] = mapped_column(Text, nullable=False)  # full evidence blob
