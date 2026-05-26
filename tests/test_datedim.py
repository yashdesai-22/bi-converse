"""date_dim tests — build + populate from Invoice, bucket labels, idempotency."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

from src.datedim import ensure_date_dim


def _make_invoice_db(tmp_path: Path, dates: list[str]) -> Path:
    db_path = tmp_path / "tiny.sqlite"
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    with eng.begin() as c:
        c.execute(text(
            "CREATE TABLE Invoice (InvoiceId INTEGER PRIMARY KEY, InvoiceDate TEXT)"
        ))
        for i, d in enumerate(dates, start=1):
            c.execute(
                text("INSERT INTO Invoice (InvoiceId, InvoiceDate) VALUES (:i, :d)"),
                {"i": i, "d": d},
            )
    eng.dispose()
    return db_path


def test_ensure_date_dim_creates_and_pads(tmp_path):
    db = _make_invoice_db(tmp_path, ["2021-06-15 00:00:00", "2022-03-01 00:00:00"])
    eng = create_engine(f"sqlite:///{db}", future=True)

    n = ensure_date_dim(eng)
    assert n > 0

    with eng.connect() as c:
        # Range pads one year on each side: 2020-01-01 .. 2023-12-31 inclusive.
        lo, hi = c.execute(text("SELECT MIN(Date), MAX(Date) FROM date_dim")).one()
        assert lo == "2020-01-01"
        assert hi == "2023-12-31"

        # Total days across 4 full years (1 leap = 2020).
        expected_days = 366 + 365 + 365 + 365
        assert c.execute(text("SELECT COUNT(*) FROM date_dim")).scalar() == expected_days


def test_ensure_date_dim_is_idempotent(tmp_path):
    db = _make_invoice_db(tmp_path, ["2021-01-01 00:00:00"])
    eng = create_engine(f"sqlite:///{db}", future=True)

    n1 = ensure_date_dim(eng)
    n2 = ensure_date_dim(eng)
    assert n1 == n2

    with eng.connect() as c:
        rows = c.execute(text("SELECT COUNT(*) FROM date_dim")).scalar()
        assert rows == n1


def test_bucket_labels_for_known_dates(tmp_path):
    db = _make_invoice_db(tmp_path, ["2023-04-15 00:00:00"])
    eng = create_engine(f"sqlite:///{db}", future=True)
    ensure_date_dim(eng)

    with eng.connect() as c:
        # 2023-04-15 is a Saturday, in Q2, ISO week 15, April.
        row = c.execute(text(
            "SELECT Year, Quarter, QuarterNum, Month, MonthName, "
            "       Week, DayOfWeek, DayOfWeekNum, MonthStart, QuarterStart, YearStart "
            "FROM date_dim WHERE Date = '2023-04-15'"
        )).one()
        assert row == (
            2023, "2023-Q2", 2, "2023-04", "April",
            "2023-W15", "Saturday", 6, "2023-04-01", "2023-04-01", "2023-01-01",
        )


def test_quarter_start_aligns_with_quarter(tmp_path):
    db = _make_invoice_db(tmp_path, ["2022-01-01 00:00:00", "2022-12-31 00:00:00"])
    eng = create_engine(f"sqlite:///{db}", future=True)
    ensure_date_dim(eng)

    with eng.connect() as c:
        # Each calendar quarter has exactly one distinct QuarterStart.
        starts = c.execute(text(
            "SELECT Quarter, COUNT(DISTINCT QuarterStart) "
            "FROM date_dim WHERE Year = 2022 GROUP BY Quarter ORDER BY Quarter"
        )).all()
        assert starts == [
            ("2022-Q1", 1), ("2022-Q2", 1), ("2022-Q3", 1), ("2022-Q4", 1),
        ]


def test_join_against_invoice_date_works(tmp_path):
    db = _make_invoice_db(tmp_path, [
        "2021-02-10 00:00:00", "2021-05-20 00:00:00", "2021-08-30 00:00:00",
    ])
    eng = create_engine(f"sqlite:///{db}", future=True)
    ensure_date_dim(eng)

    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT d.Quarter, COUNT(*) AS cnt "
            "FROM Invoice i "
            "JOIN date_dim d ON d.Date = DATE(i.InvoiceDate) "
            "GROUP BY d.Quarter ORDER BY d.Quarter"
        )).all()
        assert rows == [("2021-Q1", 1), ("2021-Q2", 1), ("2021-Q3", 1)]


def test_empty_invoice_table_still_creates_dim(tmp_path):
    db = _make_invoice_db(tmp_path, [])
    eng = create_engine(f"sqlite:///{db}", future=True)
    n = ensure_date_dim(eng)
    assert n == 0  # No invoice rows = no calendar to populate.
    with eng.connect() as c:
        # Table exists.
        c.execute(text("SELECT COUNT(*) FROM date_dim")).scalar()
