"""SQLite connection, schema introspection, and read-only query execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, inspect, text

from .datedim import ensure_date_dim
from .seed import DB_PATH, ensure_database


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    pk: bool


@dataclass
class ForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


@dataclass
class Table:
    name: str
    columns: list[Column]
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    sample_rows: list[dict] = field(default_factory=list)


@lru_cache(maxsize=1)
def get_engine(db_path: Path = DB_PATH) -> Engine:
    ensure_database(db_path)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    ensure_date_dim(engine)
    return engine


def introspect(engine: Engine | None = None, sample_rows: int = 3) -> list[Table]:
    engine = engine or get_engine()
    insp = inspect(engine)
    tables: list[Table] = []

    for name in sorted(insp.get_table_names()):
        cols = [
            Column(
                name=c["name"],
                type=str(c["type"]),
                nullable=bool(c.get("nullable", True)),
                pk=bool(c.get("primary_key", False)),
            )
            for c in insp.get_columns(name)
        ]
        fks = [
            ForeignKey(
                columns=list(fk["constrained_columns"]),
                ref_table=fk["referred_table"],
                ref_columns=list(fk["referred_columns"]),
            )
            for fk in insp.get_foreign_keys(name)
        ]
        samples: list[dict] = []
        if sample_rows > 0:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f'SELECT * FROM "{name}" LIMIT :n'), {"n": sample_rows}
                ).mappings().all()
                samples = [dict(r) for r in rows]
        tables.append(Table(name=name, columns=cols, foreign_keys=fks, sample_rows=samples))

    return tables


_DATE_DIM_NOTE = (
    "-- HELPER: date_dim is a calendar dimension covering the Invoice date range.\n"
    "-- For ANY time-bucketing question (per quarter, per week, fiscal year, "
    "YoY, QoQ, etc.), JOIN it on DATE(Invoice.InvoiceDate) = date_dim.Date\n"
    "-- and pick the bucket column directly (Quarter, Month, Week, Year, "
    "DayOfWeek, …) instead of computing it with strftime."
)


def render_schema(tables: list[Table]) -> str:
    """Compact schema description for prompting the LLM."""
    lines: list[str] = []
    for t in tables:
        col_strs = []
        for c in t.columns:
            tag = " PK" if c.pk else ""
            null = "" if c.nullable else " NOT NULL"
            col_strs.append(f"{c.name} {c.type}{null}{tag}")
        lines.append(f"TABLE {t.name} (\n  " + ",\n  ".join(col_strs) + "\n);")
        for fk in t.foreign_keys:
            lines.append(
                f"-- FK {t.name}({', '.join(fk.columns)}) -> "
                f"{fk.ref_table}({', '.join(fk.ref_columns)})"
            )
        if t.sample_rows:
            preview = t.sample_rows[0]
            preview_str = ", ".join(f"{k}={_short(v)}" for k, v in preview.items())
            lines.append(f"-- sample: {preview_str}")
        if t.name.lower() == "date_dim":
            lines.append(_DATE_DIM_NOTE)
        lines.append("")
    return "\n".join(lines).strip()


def _short(v: object, limit: int = 30) -> str:
    s = repr(v)
    return s if len(s) <= limit else s[: limit - 1] + "…'"


def run_query(sql: str, engine: Engine | None = None) -> pd.DataFrame:
    engine = engine or get_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn)
