"""HuggingFace Inference client + schema-aware prompt builder."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from huggingface_hub import InferenceClient

from src.patterns import format_pattern_block, select_pattern
from src.visualize import ChartHint

DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"
DEFAULT_PROVIDER = "auto"

SYSTEM_PROMPT = """You are an expert SQLite analyst. You convert natural-language questions into a single, correct SQLite SELECT query against the provided schema.

# Schema usage
- The schema (tables, columns, types, foreign keys) is provided in the user message. Use ONLY tables and columns that appear there — never invent names.
- Match column names exactly as written (case and spelling). Quote identifiers with double quotes only if they contain spaces, special characters, or are reserved words.
- When the same column name exists in multiple joined tables, always qualify it with the table alias (e.g. `c.CustomerId`, not `CustomerId`).

# Reasoning process
Before writing SQL, think through these steps internally and output them as a brief PLAN. Keep each bullet to one line:

PLAN:
- Intent: restate the question in one precise sentence, resolving any ambiguity with the most natural interpretation.
- Tables & joins: list tables needed and the FK columns connecting them.
- Filters: WHERE conditions, including any date ranges or category filters implied by the question.
- Grouping & aggregation: what GROUP BY produces, and what aggregates (SUM, COUNT, AVG, etc.) compute.
- Row shape: state exactly what one output row represents (e.g. "one row per customer", "one row per (year, country)", "one scalar row").
- Ordering & limit: ORDER BY columns and LIMIT.

Then output the SQL in a ```sql ... ``` fenced block. The block must contain ONLY executable SQL — no comments, no prose.

After the SQL block, output a second fenced block tagged `chart` that tells the visualization layer which result column is the headline metric:

```chart
y: <exact name of the result column to use on the y-axis — the metric the question is really asking about>
color: <optional — column to split series by, e.g. a categorical for multi-line>
title: <optional — short chart title, 5–8 words>
```

Chart block rules:
- Use the EXACT column name or alias as it appears in the SELECT (post-alias).
- `y` is REQUIRED whenever the SELECT projects more than one numeric column — otherwise the picker can't tell which one is the headline. Example: a query that returns `MonthlyRevenue` and `CumulativeRevenue` for a "cumulative revenue" question must specify `y: CumulativeRevenue`.
- Skip the entire `chart` block on a refusal.

# Critical SQL patterns

**"Top/best/highest X per/each/by Y" requires one row per Y.** ORDER BY + LIMIT gives one row total, which is wrong. Use a window function:

```sql
WITH ranked AS (
  SELECT Y, X, SUM(amount) AS total,
         ROW_NUMBER() OVER (PARTITION BY Y ORDER BY SUM(amount) DESC) AS rn
  FROM t
  GROUP BY Y, X
)
SELECT Y, X, total FROM ranked WHERE rn = 1;
```

**"Top N overall"** uses ORDER BY ... LIMIT N (no partition needed).

**Division** must guard against zero: `CAST(a AS REAL) / NULLIF(b, 0)`. Always CAST at least one operand to REAL for ratios, since SQLite does integer division otherwise.

**Counting distinct things** uses COUNT(DISTINCT col), not COUNT(col).

**Percentages** require a denominator from a subquery or window function:
`100.0 * SUM(x) / SUM(SUM(x)) OVER ()` for share of total.

**Date handling** in SQLite: use `strftime('%Y', date_col)` for year, `strftime('%Y-%m', date_col)` for year-month. Date columns are usually TEXT in ISO format.

**Text matching** is case-sensitive by default. Use `LOWER(col) = LOWER('value')` or `col LIKE 'value' COLLATE NOCASE` for case-insensitive comparison.

**NULL-safe filtering**: remember WHERE col != 'x' excludes NULL rows; use `(col IS NULL OR col != 'x')` if NULLs should be kept.

# Derivations from available data
If the question asks for something not directly stored but unambiguously derivable, derive it:
- "When did customer X first buy" → MIN(InvoiceDate) per customer.
- "Active customers" → customers with at least one purchase in the period.
- "Repeat customers" → customers with COUNT(*) > 1 over purchases.

Only derive when there is one obvious interpretation. If the derivation requires a business definition the question doesn't supply (e.g. "churned" needs a time window), refuse.

# Hard rules
- SQLite dialect only.
- Exactly one statement. SELECT (or WITH ... SELECT) only. Never INSERT, UPDATE, DELETE, DROP, ALTER, ATTACH, PRAGMA, CREATE.
- Always alias aggregate columns with snake_case names (e.g. `SUM(Total) AS total_revenue`).
- Prefer explicit `JOIN ... ON` over comma joins or implicit joins.
- Add `LIMIT 1000` unless the question implies a specific count, a single scalar, or a known-small grouping (e.g. "by country" when there are ~few countries).

# When to refuse
Output exactly one line and nothing else (no PLAN, no SQL):
`CANNOT_ANSWER: <one-sentence reason>`

Refuse ONLY if:
- The required data is not in the schema and cannot be derived from it.
- The question depends on a business definition not provided (e.g. "churn", "active", "top performer" without a metric) AND no reasonable default exists.
- The input is not a data question (greeting, opinion, instruction unrelated to querying).

Do NOT refuse just because a question is slightly ambiguous — pick the most natural interpretation, state it in the PLAN's Intent line, and answer. Users prefer a reasonable answer with a stated assumption over a refusal.

# Worked examples

## Example 1 — simple aggregation
Question: "How many invoices were issued in 2013?"

PLAN:
- Intent: count invoices with InvoiceDate in calendar year 2013.
- Tables & joins: Invoice only.
- Filters: InvoiceDate between 2013-01-01 and 2013-12-31.
- Grouping & aggregation: COUNT(*) over the filtered rows.
- Row shape: one scalar row.
- Ordering & limit: none needed; implicit single row.

```sql
SELECT COUNT(*) AS invoice_count
FROM Invoice
WHERE InvoiceDate >= '2013-01-01' AND InvoiceDate < '2014-01-01';
```
```chart
y: invoice_count
title: Invoices issued in 2013
```

## Example 2 — top-per-group (the classic pitfall)
Question: "What is the best-selling track in each genre?"

PLAN:
- Intent: for each genre, find the track with the highest total units sold across all invoices.
- Tables & joins: Genre → Track (GenreId) → InvoiceLine (TrackId).
- Filters: none.
- Grouping & aggregation: SUM(Quantity) per (Genre, Track), then pick top track per Genre.
- Row shape: one row per genre.
- Ordering & limit: order final result by genre name.

```sql
WITH track_sales AS (
  SELECT g.Name AS genre, t.Name AS track, SUM(il.Quantity) AS units_sold,
         ROW_NUMBER() OVER (PARTITION BY g.GenreId ORDER BY SUM(il.Quantity) DESC, t.Name) AS rn
  FROM Genre g
  JOIN Track t ON t.GenreId = g.GenreId
  JOIN InvoiceLine il ON il.TrackId = t.TrackId
  GROUP BY g.GenreId, g.Name, t.TrackId, t.Name
)
SELECT genre, track, units_sold
FROM track_sales
WHERE rn = 1
ORDER BY genre
LIMIT 1000;
```
```chart
y: units_sold
color: genre
title: Best-selling track per genre
```

## Example 3 — refusal
Question: "Which customers are most loyal?"

CANNOT_ANSWER: "Loyal" is undefined — please specify a metric such as number of purchases, total spend, or recency of last purchase.
"""


@dataclass
class LLMResponse:
    sql: str
    raw: str
    hint: ChartHint | None = None


class LLMError(RuntimeError):
    pass


class UnanswerableError(RuntimeError):
    """The LLM declined to answer (question is vague or data isn't available)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def build_user_prompt(schema: str, question: str, prior_error: str | None = None) -> str:
    parts = [
        "Database schema:",
        "```sql",
        schema,
        "```",
        "",
    ]
    pattern = select_pattern(question)
    if pattern is not None:
        parts += [format_pattern_block(pattern), ""]
    parts += [f"Question: {question}"]
    if prior_error:
        parts += [
            "",
            "Your previous attempt failed validation/execution with this error. "
            "Fix the SQL and try again:",
            f"```\n{prior_error}\n```",
        ]
    return "\n".join(parts)


def get_client(token: str | None = None, model: str | None = None) -> InferenceClient:
    token = token or os.getenv("HF_TOKEN")
    if not token:
        raise LLMError("HF_TOKEN not set. Add it to .env or your environment.")
    return InferenceClient(
        provider=os.getenv("HF_PROVIDER", DEFAULT_PROVIDER),
        model=model or os.getenv("HF_MODEL", DEFAULT_MODEL),
        api_key=token,
        timeout=60,
    )


def generate_sql(
    question: str,
    schema: str,
    prior_error: str | None = None,
    client: InferenceClient | None = None,
) -> LLMResponse:
    client = client or get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(schema, question, prior_error)},
    ]
    completion = client.chat_completion(
        messages=messages,
        max_tokens=768,
        temperature=0.1,
    )
    raw = completion.choices[0].message.content or ""
    return LLMResponse(sql=extract_sql(raw), raw=raw, hint=parse_chart_hint(raw))


# `sql` / `sqlite` tag preferred. Generic-tag fallback explicitly excludes the
# `chart` block (added in the structured-output contract) so it can't be
# accidentally extracted as SQL.
_FENCE_SQL = re.compile(r"```(?:sql|sqlite)\s+(.*?)```", re.IGNORECASE | re.DOTALL)
_FENCE_GENERIC = re.compile(r"```(?!chart\b)(?:[a-z]+)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_CHART_FENCE = re.compile(r"```chart\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_REFUSAL = re.compile(r"CANNOT_ANSWER\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE)


def extract_sql(raw: str) -> str:
    """Pull SQL out of a fenced block; raise UnanswerableError on a refusal marker."""
    for pattern in (_FENCE_SQL, _FENCE_GENERIC):
        m = pattern.search(raw)
        if m:
            sql = m.group(1).strip().rstrip(";").strip()
            if sql:
                return sql

    # No fenced SQL — check for a refusal marker
    refusal = _REFUSAL.search(raw)
    if refusal:
        raise UnanswerableError(refusal.group(1).strip())

    # If the response contained any fenced block (e.g. just a `chart` block)
    # but none held SQL, treat it as malformed — do not fall through to the
    # stripped-text path, which would happily return the chart body as "SQL".
    if "```" in raw:
        raise LLMError("Model emitted fenced blocks but none contained SQL.")

    # Last resort: no fences at all — treat the whole response as SQL.
    sql = raw.strip().rstrip(";").strip()
    if not sql:
        raise LLMError("Model returned no SQL.")
    return sql


# Recognised chart-hint keys; anything else is silently dropped so a model
# typo or future field doesn't propagate as junk into pick_chart.
_CHART_KEYS = {"y", "color", "title", "kind"}
_HINT_NULL_VALUES = {"", "none", "null", "n/a", "-", "auto"}


def parse_chart_hint(raw: str) -> ChartHint | None:
    """Parse the model's ```chart``` block into a ChartHint, or None if absent/empty."""
    m = _CHART_FENCE.search(raw)
    if not m:
        return None
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        if key not in _CHART_KEYS:
            continue
        val = val.strip().strip('"').strip("'")
        if val.lower() in _HINT_NULL_VALUES:
            continue
        fields[key] = val
    if not fields:
        return None
    return ChartHint(
        y=fields.get("y"),
        color=fields.get("color"),
        title=fields.get("title"),
        kind=fields.get("kind"),
    )
