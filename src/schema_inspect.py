"""Schema-aware analysis of validated SQL — find result-column names that are
semantically identifiers (PK or FK references) despite any aliasing.

Complements the name-based detection in visualize.py: when the LLM writes
`SELECT c.CustomerId AS Customer`, the result column is named `Customer` and
the name regex misses it, but the schema knows CustomerId is a PK.

Scope is intentionally narrow:
  - Looks only at the outermost SELECT's projection list.
  - Recognises bare columns and single-column aliases.
  - Skips aggregates, arithmetic, CASE expressions, literals, * — those
    produce a value, not a category, so they shouldn't be id-typed.
  - Does NOT chase aliases through CTEs. If a CTE projects `CustomerId AS cid`
    and the outer SELECT projects `cid`, we miss it. Acceptable for now;
    add CTE resolution if real questions surface that pattern.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from .db import Table


def identifier_result_columns(sql: str, schema: list[Table]) -> set[str]:
    """Return result-column names that map back to a PK or FK column in the schema."""
    key_cols = _collect_key_columns(schema)
    if not key_cols:
        return set()

    try:
        parsed = sqlglot.parse(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return set()

    parsed = [p for p in parsed if p is not None]
    if not parsed:
        return set()

    stmt = parsed[0]
    select = stmt if isinstance(stmt, exp.Select) else stmt.find(exp.Select)
    if select is None:
        return set()

    result_cols: set[str] = set()
    for proj in select.expressions:
        result_name, source_col = _resolve_projection(proj)
        if result_name and source_col and source_col.lower() in key_cols:
            result_cols.add(result_name)
    return result_cols


def _collect_key_columns(schema: list[Table]) -> set[str]:
    """Lowercased names of columns that are a PK or part of any FK constraint."""
    cols: set[str] = set()
    for t in schema:
        for c in t.columns:
            if c.pk:
                cols.add(c.name.lower())
        for fk in t.foreign_keys:
            for col in fk.columns:
                cols.add(col.lower())
    return cols


def _resolve_projection(proj: exp.Expression) -> tuple[str | None, str | None]:
    """Extract (result_name, source_column_name) for a SELECT projection.

    Returns (None, None) for anything that isn't a bare column or a one-column alias.
    """
    if isinstance(proj, exp.Alias):
        inner = proj.this
        if isinstance(inner, exp.Column):
            return proj.alias_or_name, inner.name
        return None, None
    if isinstance(proj, exp.Column):
        return proj.alias_or_name, proj.name
    return None, None
