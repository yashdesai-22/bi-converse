"""Pattern router tests — covers positive routes, no-route cases, and known traps."""
from __future__ import annotations

import pytest

from src.patterns import PATTERNS, select_pattern


@pytest.mark.parametrize("question,expected", [
    # top-N-per-group: "per/each" or "by <time/dimension>" only
    ("What is the top-selling genre each year?", "top-n-per-group"),
    ("Best customer per country", "top-n-per-group"),
    ("Highest-grossing artist by year", "top-n-per-group"),
    ("Most popular track in each genre", "top-n-per-group"),
    ("Worst-selling album per quarter", "top-n-per-group"),

    # period-over-period
    ("Revenue this year vs last year by genre", "period-over-period"),
    ("Sales year over year", "period-over-period"),
    ("Total invoices YoY", "period-over-period"),
    ("Q4 sales compared to Q3", "period-over-period"),

    # cumulative
    ("Cumulative revenue by month", "cumulative-total"),
    ("Running total of invoices", "cumulative-total"),
    ("Running sum of tracks sold", "cumulative-total"),

    # anti-join
    ("Customers who have never purchased a Jazz track", "anti-join"),
    ("Tracks without any sales", "anti-join"),
    ("Albums with no invoice lines", "anti-join"),
    ("Employees who didn't make a sale last year", "anti-join"),

    # ratio
    ("What percentage of customers have purchased Rock?", "ratio-with-filter"),
    ("Share of revenue from USA", "ratio-with-filter"),
    ("What fraction of tracks are Jazz?", "ratio-with-filter"),

    # pivot
    ("Revenue by country with one column per year", "pivot-conditional-aggregation"),
    ("Pivot revenue by genre across years", "pivot-conditional-aggregation"),
    ("Cross-tab of country vs year", "pivot-conditional-aggregation"),
])
def test_router_matches(question, expected):
    pat = select_pattern(question)
    assert pat is not None, f"no pattern matched: {question!r}"
    assert pat.name == expected, f"{question!r} routed to {pat.name}, expected {expected}"


@pytest.mark.parametrize("question", [
    # Plain ranking is NOT top-N-per-group — "by revenue/sales" is a measure, not a grouping.
    "Top 10 customers by revenue",
    "Best-selling albums",
    "Highest grossing tracks by sales",
    # Simple aggregates
    "How many customers do we have?",
    "Total revenue",
    "Average track length",
    "List all genres",
    "Count of invoices in 2010",
])
def test_router_returns_none_for_non_pattern_questions(question):
    pat = select_pattern(question)
    assert pat is None, f"{question!r} unexpectedly routed to {pat.name if pat else None}"


def test_all_patterns_have_unique_names():
    names = [p.name for p in PATTERNS]
    assert len(names) == len(set(names))


def test_format_pattern_block_contains_sql_fence():
    from src.patterns import format_pattern_block
    block = format_pattern_block(PATTERNS[0])
    assert "```sql" in block and "```" in block.split("```sql", 1)[1]
