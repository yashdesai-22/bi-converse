"""Safety + correctness checks for LLM-generated SQL before execution."""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlalchemy import Engine, text
from sqlglot import exp

from .db import Table, get_engine

FORBIDDEN = {
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.TruncateTable, exp.Command, exp.Pragma,
}


class ValidationError(ValueError):
    pass


@dataclass
class ValidatedSQL:
    sql: str
    referenced_tables: list[str]


def validate(sql: str, schema: list[Table], engine: Engine | None = None) -> ValidatedSQL:
    """Parse SQL, enforce SELECT-only, check identifiers, and dry-run via EXPLAIN."""
    try:
        parsed = sqlglot.parse(sql, read="sqlite")
    except sqlglot.errors.ParseError as e:
        raise ValidationError(f"SQL did not parse: {e}") from e

    parsed = [p for p in parsed if p is not None]
    if not parsed:
        raise ValidationError("No SQL statement found.")
    if len(parsed) > 1:
        raise ValidationError("Only a single statement is allowed.")

    stmt = parsed[0]

    # SELECT-only (CTEs with WITH wrap a Select)
    if not isinstance(stmt, (exp.Select, exp.Union)) and stmt.find(exp.Select) is None:
        raise ValidationError("Only SELECT statements are allowed.")

    for node in stmt.walk():
        if isinstance(node, tuple(FORBIDDEN)):
            raise ValidationError(
                f"Forbidden statement type: {type(node).__name__.upper()}"
            )

    # Identifier whitelist
    schema_tables = {t.name.lower(): {c.name.lower() for c in t.columns} for t in schema}
    referenced: set[str] = set()
    for tbl in stmt.find_all(exp.Table):
        tname = tbl.name
        if tname.lower() not in schema_tables:
            raise ValidationError(f"Unknown table: {tname}")
        referenced.add(tname)

    all_known_cols = {c for cols in schema_tables.values() for c in cols}
    for col in stmt.find_all(exp.Column):
        cname = col.name
        if not cname or cname == "*":
            continue
        if cname.lower() not in all_known_cols:
            raise ValidationError(f"Unknown column: {cname}")

    # Dry-run via EXPLAIN — catches anything the parser missed
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text(f"EXPLAIN {sql}"))
    except Exception as e:  # noqa: BLE001
        raise ValidationError(f"EXPLAIN failed: {e}") from e

    return ValidatedSQL(sql=sql, referenced_tables=sorted(referenced))
