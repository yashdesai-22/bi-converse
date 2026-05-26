"""Pattern library — canonical SQL recipes injected into the prompt by question intent.

LLMs reliably stumble on certain BI query shapes even with a clean schema:
top-N-per-group collapsed into a plain ORDER BY, period-over-period written as
two separate queries, anti-joins implemented as inner joins with filters, etc.
This module keeps worked examples for those shapes out of the system prompt
(where they'd dilute attention on simple questions) and injects exactly one
into the user prompt when the question matches a known pattern.

Each Pattern carries:
  - triggers: regexes matched against the raw question (case-insensitive)
  - example_question / example_sql: worked example using the Chinook schema
  - rationale: one-line note on why the naive shape is wrong

select_pattern(question) returns the first matching Pattern or None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    name: str
    rationale: str
    example_question: str
    example_sql: str
    triggers: tuple[re.Pattern, ...]


def _re(*pats: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in pats)


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        name="top-n-per-group",
        rationale=(
            "'top/best/highest X per/each Y' means ONE winning row per Y. "
            "Plain ORDER BY returns every row sorted, not the winners. "
            "Use ROW_NUMBER() OVER (PARTITION BY Y ORDER BY metric DESC) and filter rn = 1."
        ),
        example_question="What is the top-selling genre each year?",
        example_sql=(
            "WITH yearly AS (\n"
            "  SELECT strftime('%Y', i.InvoiceDate) AS Year, g.Name AS Genre,\n"
            "         SUM(il.Quantity) AS TotalSales\n"
            "  FROM Invoice i\n"
            "  JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId\n"
            "  JOIN Track t        ON il.TrackId  = t.TrackId\n"
            "  JOIN Genre g        ON t.GenreId   = g.GenreId\n"
            "  GROUP BY Year, g.Name\n"
            "),\n"
            "ranked AS (\n"
            "  SELECT *, ROW_NUMBER() OVER (PARTITION BY Year ORDER BY TotalSales DESC) AS rn\n"
            "  FROM yearly\n"
            ")\n"
            "SELECT Year, Genre, TotalSales FROM ranked WHERE rn = 1 ORDER BY Year"
        ),
        # "by revenue" / "by sales" is a measure, not a grouping — must not trigger this pattern.
        # Only "per/each" or "by <time-or-dimension-noun>" qualify.
        triggers=_re(
            r"\b(top|best|highest|most|biggest|largest|leading|lowest|worst)\b[\w\s\-]{1,40}?\b(per|each|in\s+each|for\s+each)\b",
            r"\b(top|best|highest|most|leading|biggest|lowest|worst)\b.{1,40}?\bby\s+(year|month|quarter|day|week|country|genre|artist|album|customer|employee)\b",
        ),
    ),
    Pattern(
        name="period-over-period",
        rationale=(
            "Comparing two periods needs conditional aggregation in ONE query: "
            "SUM(CASE WHEN period = A) AS a, SUM(CASE WHEN period = B) AS b, "
            "and a derived delta if helpful — not two separate queries joined."
        ),
        example_question="Revenue this year vs last year by genre.",
        example_sql=(
            "WITH params AS (\n"
            "  SELECT CAST(strftime('%Y', MAX(InvoiceDate)) AS INTEGER) AS curr_year FROM Invoice\n"
            ")\n"
            "SELECT g.Name AS Genre,\n"
            "       SUM(CASE WHEN CAST(strftime('%Y', i.InvoiceDate) AS INTEGER) = (SELECT curr_year FROM params)     THEN il.UnitPrice * il.Quantity ELSE 0 END) AS ThisYear,\n"
            "       SUM(CASE WHEN CAST(strftime('%Y', i.InvoiceDate) AS INTEGER) = (SELECT curr_year FROM params) - 1 THEN il.UnitPrice * il.Quantity ELSE 0 END) AS LastYear\n"
            "FROM Invoice i\n"
            "JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId\n"
            "JOIN Track t        ON il.TrackId  = t.TrackId\n"
            "JOIN Genre g        ON t.GenreId   = g.GenreId\n"
            "GROUP BY g.Name\n"
            "ORDER BY ThisYear DESC"
        ),
        # "vs" / "versus" / "compared to" only count when sitting next to a time reference;
        # otherwise "country vs year" (a pivot phrasing) false-positives here.
        triggers=_re(
            r"\b(year|month|quarter|q[1-4]|\d{4}|this|last|prior|previous|current|today|yesterday)\b\s.{0,25}\b(vs\.?|versus|compared\s+to|against)\b",
            r"\b(year[-\s]?over[-\s]?year|yoy|month[-\s]?over[-\s]?month|mom|quarter[-\s]?over[-\s]?quarter|qoq)\b",
            r"\bthis\s+(year|month|quarter)\b.{1,30}\blast\s+(year|month|quarter)\b",
        ),
    ),
    Pattern(
        name="cumulative-total",
        rationale=(
            "'Cumulative' / 'running total' needs a window SUM: "
            "SUM(metric) OVER (ORDER BY time ROWS UNBOUNDED PRECEDING). "
            "A plain GROUP BY gives period totals, not the running sum."
        ),
        example_question="Cumulative revenue by month.",
        example_sql=(
            "SELECT Month, MonthlyRevenue,\n"
            "       SUM(MonthlyRevenue) OVER (ORDER BY Month ROWS UNBOUNDED PRECEDING) AS CumulativeRevenue\n"
            "FROM (\n"
            "  SELECT strftime('%Y-%m', i.InvoiceDate) AS Month,\n"
            "         SUM(i.Total) AS MonthlyRevenue\n"
            "  FROM Invoice i\n"
            "  GROUP BY Month\n"
            ")\n"
            "ORDER BY Month"
        ),
        triggers=_re(
            r"\b(cumulative|running\s+(total|sum)|growing\s+total)\b",
        ),
    ),
    Pattern(
        name="anti-join",
        rationale=(
            "'Who never did X' / 'who has no Y' is an anti-join. "
            "Use NOT EXISTS or LEFT JOIN ... WHERE other.id IS NULL. "
            "An inner join with a filter on the other table silently returns the wrong set."
        ),
        example_question="Which customers have never purchased a Jazz track?",
        example_sql=(
            "SELECT c.CustomerId, c.FirstName, c.LastName\n"
            "FROM Customer c\n"
            "WHERE NOT EXISTS (\n"
            "  SELECT 1\n"
            "  FROM Invoice i\n"
            "  JOIN InvoiceLine il ON i.InvoiceId = il.InvoiceId\n"
            "  JOIN Track t        ON il.TrackId  = t.TrackId\n"
            "  JOIN Genre g        ON t.GenreId   = g.GenreId\n"
            "  WHERE i.CustomerId = c.CustomerId AND g.Name = 'Jazz'\n"
            ")\n"
            "ORDER BY c.CustomerId"
        ),
        triggers=_re(
            r"\b(never|haven'?t|hasn'?t|didn'?t|did\s+not|do\s+not|does\s+not|doesn'?t)\b",
            r"\b(without\s+(any|a|an)|with\s+no)\b",
            r"\bno\s+\w+\s+(of|in|from|for)\b",
        ),
    ),
    Pattern(
        name="ratio-with-filter",
        rationale=(
            "'% of X that did Y' / 'share of X from Y' is ONE query with two aggregates: "
            "100.0 * SUM(CASE WHEN cond) / COUNT(*) (or COUNT DISTINCT for entities). "
            "Don't run two queries and divide externally."
        ),
        example_question="What percentage of customers have purchased Rock?",
        example_sql=(
            "SELECT ROUND(\n"
            "  100.0 * COUNT(DISTINCT CASE WHEN g.Name = 'Rock' THEN c.CustomerId END)\n"
            "       / COUNT(DISTINCT c.CustomerId),\n"
            "  2\n"
            ") AS PercentRockBuyers\n"
            "FROM Customer c\n"
            "LEFT JOIN Invoice i      ON c.CustomerId = i.CustomerId\n"
            "LEFT JOIN InvoiceLine il ON i.InvoiceId  = il.InvoiceId\n"
            "LEFT JOIN Track t        ON il.TrackId   = t.TrackId\n"
            "LEFT JOIN Genre g        ON t.GenreId    = g.GenreId"
        ),
        triggers=_re(
            r"\b(percent(age)?|share|fraction|proportion|ratio)\s+of\b",
            r"\bwhat\s+(percent|percentage|share|fraction|proportion)\b",
            r"%\s+of\b",
        ),
    ),
    Pattern(
        name="time-bucketing",
        rationale=(
            "Quarter/week/fiscal-period bucketing has no native SQLite token "
            "(strftime gives year/month/day only). Use the date_dim table: "
            "JOIN it on DATE(Invoice.InvoiceDate) = date_dim.Date and read the "
            "Quarter/Week/Month/Year column directly. Never invent strftime "
            "expressions for quarters."
        ),
        example_question="New customers acquired per quarter (by first invoice date).",
        example_sql=(
            "WITH firsts AS (\n"
            "  SELECT CustomerId, MIN(DATE(InvoiceDate)) AS FirstInvoiceDate\n"
            "  FROM Invoice\n"
            "  GROUP BY CustomerId\n"
            ")\n"
            "SELECT d.Quarter AS Quarter,\n"
            "       COUNT(*) AS NewCustomers\n"
            "FROM firsts f\n"
            "JOIN date_dim d ON d.Date = f.FirstInvoiceDate\n"
            "GROUP BY d.Quarter\n"
            "ORDER BY d.Quarter"
        ),
        # Triggers cover quarter/week/fiscal as bucket dimensions, plus the
        # *-over-* abbreviations that imply chronological grouping. "by month"
        # and "by year" are intentionally omitted — strftime('%Y-%m', ...) and
        # strftime('%Y', ...) already give the model the right answer there,
        # so injecting a worked example would be pure token waste.
        triggers=_re(
            r"\b(per|each|by)\s+(quarter|week|fiscal\s+year|iso\s+week|day\s+of\s+week|weekday)\b",
            r"\bquarter(ly|s)?\b",
            r"\bweek(ly|s)?\b",
            r"\bfiscal\s+(year|quarter|period)\b",
            r"\b(qoq|wow)\b",
            r"\btrailing\s+\d+\s+(quarter|week|month|year)s?\b",
        ),
    ),
    Pattern(
        name="pivot-conditional-aggregation",
        rationale=(
            "SQLite has no native PIVOT. To turn a category into columns, "
            "use SUM(CASE WHEN cat = 'X' THEN metric END) AS X, one CASE per output column."
        ),
        example_question="Revenue by country, with one column per year.",
        example_sql=(
            "SELECT i.BillingCountry AS Country,\n"
            "       SUM(CASE WHEN strftime('%Y', i.InvoiceDate) = '2009' THEN i.Total END) AS Y2009,\n"
            "       SUM(CASE WHEN strftime('%Y', i.InvoiceDate) = '2010' THEN i.Total END) AS Y2010,\n"
            "       SUM(CASE WHEN strftime('%Y', i.InvoiceDate) = '2011' THEN i.Total END) AS Y2011,\n"
            "       SUM(CASE WHEN strftime('%Y', i.InvoiceDate) = '2012' THEN i.Total END) AS Y2012,\n"
            "       SUM(CASE WHEN strftime('%Y', i.InvoiceDate) = '2013' THEN i.Total END) AS Y2013\n"
            "FROM Invoice i\n"
            "GROUP BY i.BillingCountry\n"
            "ORDER BY Country"
        ),
        triggers=_re(
            r"\b(pivot|cross[-\s]?tab|crosstab)\b",
            r"\bone\s+column\s+(per|for\s+each)\b",
            r"\bcolumns?\s+(per|for\s+each)\b",
        ),
    ),
)


def select_pattern(question: str) -> Pattern | None:
    """Return the first Pattern whose triggers match the question, or None.

    Patterns are evaluated in registry order — more specific patterns first.
    """
    q = question.strip()
    for pat in PATTERNS:
        for trigger in pat.triggers:
            if trigger.search(q):
                return pat
    return None


def format_pattern_block(pattern: Pattern) -> str:
    """Render a Pattern as a worked example for injection into the prompt."""
    return (
        "RELEVANT PATTERN — this question resembles a known query shape:\n"
        f"  Pattern: {pattern.name}\n"
        f"  Why it matters: {pattern.rationale}\n"
        f"  Example question: {pattern.example_question}\n"
        "  Example SQL:\n"
        "```sql\n"
        f"{pattern.example_sql}\n"
        "```\n"
        "Adapt the STRUCTURE of the example to the user's actual question. "
        "Substitute the tables, columns, filter values, and grouping keys to match what the question asks. "
        "Do not copy the example's literal identifiers if they don't fit."
    )
