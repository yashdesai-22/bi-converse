"""Validator tests — happy path + safety rejections."""
from __future__ import annotations

import pytest

from src.db import get_engine, introspect
from src.sql_validator import ValidationError, validate


@pytest.fixture(scope="module")
def schema_and_engine():
    engine = get_engine()
    schema = introspect(engine)
    return schema, engine


def test_simple_select_passes(schema_and_engine):
    schema, engine = schema_and_engine
    result = validate('SELECT * FROM "Customer" LIMIT 5', schema, engine)
    assert "Customer" in result.referenced_tables


def test_join_and_aggregate_passes(schema_and_engine):
    schema, engine = schema_and_engine
    sql = (
        'SELECT c.Country, SUM(i.Total) AS total_revenue '
        'FROM "Customer" c JOIN "Invoice" i ON c.CustomerId = i.CustomerId '
        'GROUP BY c.Country ORDER BY total_revenue DESC LIMIT 10'
    )
    result = validate(sql, schema, engine)
    assert {"Customer", "Invoice"}.issubset(set(result.referenced_tables))


@pytest.mark.parametrize("sql", [
    'DROP TABLE "Customer"',
    'DELETE FROM "Customer"',
    'UPDATE "Customer" SET Email = NULL',
    'INSERT INTO "Customer" (FirstName) VALUES (\'X\')',
])
def test_write_statements_rejected(sql, schema_and_engine):
    schema, engine = schema_and_engine
    with pytest.raises(ValidationError):
        validate(sql, schema, engine)


def test_multi_statement_rejected(schema_and_engine):
    schema, engine = schema_and_engine
    with pytest.raises(ValidationError):
        validate('SELECT 1; SELECT 2', schema, engine)


def test_unknown_table_rejected(schema_and_engine):
    schema, engine = schema_and_engine
    with pytest.raises(ValidationError, match="Unknown table"):
        validate('SELECT * FROM "NotARealTable"', schema, engine)


def test_unknown_column_rejected(schema_and_engine):
    schema, engine = schema_and_engine
    with pytest.raises(ValidationError, match="Unknown column"):
        validate('SELECT NotARealColumn FROM "Customer"', schema, engine)


def test_aliased_column_in_order_by_passes(schema_and_engine):
    schema, engine = schema_and_engine
    sql = (
        'SELECT c.CustomerId, c.FirstName, c.LastName, '
        'SUM(i.Total) AS TotalSpend '
        'FROM "Customer" c JOIN "Invoice" i ON c.CustomerId = i.CustomerId '
        'GROUP BY c.CustomerId, c.FirstName, c.LastName '
        'ORDER BY TotalSpend DESC LIMIT 10'
    )
    result = validate(sql, schema, engine)
    assert {"Customer", "Invoice"}.issubset(set(result.referenced_tables))


def test_cte_alias_allowed(schema_and_engine):
    schema, engine = schema_and_engine
    sql = (
        'WITH customer_totals AS ('
        '  SELECT CustomerId, SUM(Total) AS spend FROM "Invoice" GROUP BY CustomerId'
        ') SELECT CustomerId, spend FROM customer_totals ORDER BY spend DESC LIMIT 5'
    )
    validate(sql, schema, engine)


def test_garbage_rejected(schema_and_engine):
    schema, engine = schema_and_engine
    with pytest.raises(ValidationError):
        validate('this is not sql', schema, engine)
