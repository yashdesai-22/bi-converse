"""Build a Kimball-style date dimension table for time-bucketing questions.

The Chinook schema has no native quarter / fiscal-period / ISO-week columns,
and SQLite's `strftime` cannot produce a quarter token. Rather than teach the
LLM the quirky SQLite expressions (`'-Q' || ((CAST(...)-1)/3+1)`), we expose
a `date_dim` table whose rows cover the full range of `Invoice.InvoiceDate`
with one column per common bucket. The model joins against it like any other
dimension and reads the bucket it needs.

Built once per DB on first use; subsequent calls are a cheap existence check.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Engine, text

DATE_DIM_TABLE = "date_dim"

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {DATE_DIM_TABLE} (
    Date         TEXT PRIMARY KEY,  -- 'YYYY-MM-DD'; join to DATE(Invoice.InvoiceDate)
    Year         INTEGER NOT NULL,
    Quarter      TEXT    NOT NULL,  -- 'YYYY-Qn', e.g. '2013-Q2'
    QuarterNum   INTEGER NOT NULL,  -- 1..4
    Month        TEXT    NOT NULL,  -- 'YYYY-MM', e.g. '2013-04'
    MonthNum     INTEGER NOT NULL,  -- 1..12
    MonthName    TEXT    NOT NULL,  -- 'April'
    Week         TEXT    NOT NULL,  -- 'YYYY-Www', ISO-style Monday-start
    DayOfWeek    TEXT    NOT NULL,  -- 'Tuesday'
    DayOfWeekNum INTEGER NOT NULL,  -- 1=Mon..7=Sun
    MonthStart   TEXT    NOT NULL,  -- 'YYYY-MM-01'
    QuarterStart TEXT    NOT NULL,  -- first day of the quarter
    YearStart    TEXT    NOT NULL   -- 'YYYY-01-01'
)
"""

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _row(d: date) -> tuple:
    q = (d.month - 1) // 3 + 1
    iso_year, iso_week, iso_dow = d.isocalendar()
    return (
        d.isoformat(),
        d.year,
        f"{d.year:04d}-Q{q}",
        q,
        f"{d.year:04d}-{d.month:02d}",
        d.month,
        _MONTH_NAMES[d.month - 1],
        f"{iso_year:04d}-W{iso_week:02d}",
        _DAY_NAMES[iso_dow - 1],
        iso_dow,
        f"{d.year:04d}-{d.month:02d}-01",
        f"{d.year:04d}-{3 * (q - 1) + 1:02d}-01",
        f"{d.year:04d}-01-01",
    )


def _invoice_date_range(conn) -> tuple[date, date] | None:
    """Return (min, max) calendar dates from Invoice.InvoiceDate, or None if empty."""
    res = conn.execute(text(
        "SELECT MIN(DATE(InvoiceDate)), MAX(DATE(InvoiceDate)) FROM Invoice"
    )).fetchone()
    if not res or res[0] is None or res[1] is None:
        return None
    return date.fromisoformat(res[0]), date.fromisoformat(res[1])


def ensure_date_dim(engine: Engine) -> int:
    """Create date_dim and populate it from the Invoice date range. Idempotent.

    Returns the row count after the call.
    """
    with engine.begin() as conn:
        conn.execute(text(_CREATE_SQL))
        existing = conn.execute(
            text(f"SELECT COUNT(*) FROM {DATE_DIM_TABLE}")
        ).scalar() or 0
        if existing > 0:
            return int(existing)

        rng = _invoice_date_range(conn)
        if rng is None:
            return 0  # No Invoice rows yet; dim stays empty (still exists).
        start, end = rng

        # Cover full calendar years on both sides, plus one trailing year of
        # padding so "next quarter" / forward-looking phrasings still resolve.
        start = date(start.year - 1, 1, 1)
        end = date(end.year + 1, 12, 31)

        rows = []
        d = start
        one_day = timedelta(days=1)
        while d <= end:
            rows.append(_row(d))
            d += one_day

        conn.execute(text(
            f"INSERT INTO {DATE_DIM_TABLE} "
            "(Date, Year, Quarter, QuarterNum, Month, MonthNum, MonthName, "
            " Week, DayOfWeek, DayOfWeekNum, MonthStart, QuarterStart, YearStart) "
            "VALUES (:Date, :Year, :Quarter, :QuarterNum, :Month, :MonthNum, :MonthName, "
            " :Week, :DayOfWeek, :DayOfWeekNum, :MonthStart, :QuarterStart, :YearStart)"
        ), [
            {
                "Date": r[0], "Year": r[1], "Quarter": r[2], "QuarterNum": r[3],
                "Month": r[4], "MonthNum": r[5], "MonthName": r[6],
                "Week": r[7], "DayOfWeek": r[8], "DayOfWeekNum": r[9],
                "MonthStart": r[10], "QuarterStart": r[11], "YearStart": r[12],
            }
            for r in rows
        ])
        return len(rows)
