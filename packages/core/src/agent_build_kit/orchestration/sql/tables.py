"""The units store's schema, as SQLAlchemy Core tables."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, MetaData, String, Table

METADATA = MetaData()

# One row per unit: its JSON body and the version `put_if` compares.
UNITS = Table(
    "units",
    METADATA,
    Column("id", String, primary_key=True),
    Column("body", JSON, nullable=False),
    Column("version", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# One row per history entry, ordered by its sequence within the unit.
UNIT_HISTORY = Table(
    "unit_history",
    METADATA,
    Column("unit_id", String, ForeignKey("units.id"), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("entry", JSON, nullable=False),
)
