"""Chart-hint parser tests."""
from __future__ import annotations

from src.llm import parse_chart_hint


def test_full_hint_block_is_parsed():
    raw = (
        "PLAN: ...\n"
        "```sql\nSELECT 1;\n```\n"
        "```chart\n"
        "y: CumulativeRevenue\n"
        "color: Genre\n"
        "title: Cumulative revenue by genre\n"
        "```\n"
    )
    hint = parse_chart_hint(raw)
    assert hint is not None
    assert hint.y == "CumulativeRevenue"
    assert hint.color == "Genre"
    assert hint.title == "Cumulative revenue by genre"


def test_partial_hint_is_parsed():
    raw = "```chart\ny: total_revenue\n```"
    hint = parse_chart_hint(raw)
    assert hint is not None
    assert hint.y == "total_revenue"
    assert hint.color is None
    assert hint.title is None


def test_missing_chart_block_returns_none():
    assert parse_chart_hint("just SQL here, no chart block") is None


def test_empty_chart_block_returns_none():
    assert parse_chart_hint("```chart\n\n```") is None


def test_null_placeholders_are_dropped():
    raw = "```chart\ny: total\ncolor: none\ntitle: -\nkind: auto\n```"
    hint = parse_chart_hint(raw)
    assert hint is not None
    assert hint.y == "total"
    assert hint.color is None
    assert hint.title is None
    assert hint.kind is None


def test_unknown_keys_are_ignored():
    raw = "```chart\ny: total\nfoo: bar\nsubtitle: whatever\n```"
    hint = parse_chart_hint(raw)
    assert hint is not None
    assert hint.y == "total"
    assert hint.color is None


def test_quoted_values_are_unquoted():
    raw = "```chart\ny: \"Total Revenue\"\ntitle: 'Top genres'\n```"
    hint = parse_chart_hint(raw)
    assert hint is not None
    assert hint.y == "Total Revenue"
    assert hint.title == "Top genres"


def test_refusal_response_has_no_chart_hint():
    raw = "CANNOT_ANSWER: question is too vague."
    assert parse_chart_hint(raw) is None


def test_chart_fence_is_not_extracted_as_sql():
    """A response with only a ```chart``` block (no ```sql```) must not produce SQL."""
    from src.llm import LLMError, extract_sql
    raw = "```chart\ny: total\n```"
    try:
        extract_sql(raw)
    except LLMError:
        return  # expected
    # If we got SQL back, that's a regression — the chart block was mis-extracted.
    raise AssertionError("chart block was wrongly extracted as SQL")
