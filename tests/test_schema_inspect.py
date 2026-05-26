"""Schema-aware ID detection — alias resolution against PK/FK columns."""
from __future__ import annotations

import pytest

from src.db import get_engine, introspect
from src.schema_inspect import _collect_key_columns, identifier_result_columns


@pytest.fixture(scope="module")
def schema():
    return introspect(get_engine())


def test_pks_and_fks_are_collected(schema):
    keys = _collect_key_columns(schema)
    # Chinook PKs (all named <Entity>Id)
    for name in ["customerid", "employeeid", "trackid", "albumid", "artistid",
                 "genreid", "invoiceid", "invoicelineid", "mediatypeid", "playlistid"]:
        assert name in keys, name


def test_alias_of_pk_column_is_detected(schema):
    sql = (
        'SELECT c.CustomerId AS Customer, SUM(i.Total) AS Revenue '
        'FROM "Customer" c JOIN "Invoice" i ON c.CustomerId = i.CustomerId '
        'GROUP BY c.CustomerId ORDER BY Revenue DESC LIMIT 10'
    )
    cols = identifier_result_columns(sql, schema)
    assert cols == {"Customer"}


def test_bare_pk_column_is_detected(schema):
    sql = 'SELECT c.CustomerId, SUM(i.Total) AS Revenue FROM "Customer" c JOIN "Invoice" i ON c.CustomerId = i.CustomerId GROUP BY c.CustomerId'
    cols = identifier_result_columns(sql, schema)
    assert cols == {"CustomerId"}


def test_fk_column_is_also_an_identifier(schema):
    # Invoice.CustomerId is an FK -> should also be treated as identifier.
    sql = 'SELECT i.CustomerId AS Buyer, SUM(i.Total) AS Spend FROM "Invoice" i GROUP BY i.CustomerId'
    cols = identifier_result_columns(sql, schema)
    assert cols == {"Buyer"}


def test_aggregate_over_id_is_not_an_identifier(schema):
    # MAX(CustomerId) is a single number, not a category.
    sql = 'SELECT MAX(c.CustomerId) AS BiggestId FROM "Customer" c'
    cols = identifier_result_columns(sql, schema)
    assert cols == set()


def test_non_key_column_is_not_an_identifier(schema):
    sql = 'SELECT c.Country, COUNT(*) AS N FROM "Customer" c GROUP BY c.Country'
    cols = identifier_result_columns(sql, schema)
    assert cols == set()


def test_unparseable_sql_returns_empty_set(schema):
    assert identifier_result_columns("this is not sql at all", schema) == set()


def test_mixed_projection_returns_only_id_aliases(schema):
    sql = (
        'SELECT c.CustomerId AS Customer, c.Country, COUNT(i.InvoiceId) AS Orders '
        'FROM "Customer" c LEFT JOIN "Invoice" i ON c.CustomerId = i.CustomerId '
        'GROUP BY c.CustomerId, c.Country'
    )
    cols = identifier_result_columns(sql, schema)
    assert cols == {"Customer"}
