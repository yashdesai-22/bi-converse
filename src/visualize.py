"""Heuristic: pick a sensible Plotly chart from a result DataFrame."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Matches identifier-like column names — categorical despite an integer dtype.
# `[a-z]Id` covers CamelCase (CustomerId), `_id`/`_Id` covers snake_case,
# `ID` covers ALL_CAPS. "valid" / "paid" don't match (no capital I, no underscore).
_ID_SUFFIX = re.compile(r"(?:[a-z]Id|_[iI]d|ID)$")


def _looks_like_identifier(name: str) -> bool:
    return bool(_ID_SUFFIX.search(name))


@dataclass
class Chart:
    figure: go.Figure | None
    kind: str  # "answer" | "list" | "line" | "bar" | "scatter" | "table" | "empty"
    caption: str


@dataclass
class ChartHint:
    """LLM-proposed visualization spec, parsed from the model's chart block.

    Every field is advisory: pick_chart validates each against the actual
    DataFrame and silently falls back to its heuristics on any mismatch.
    `kind` is accepted but not currently honored (planned).
    """
    y: str | None = None
    color: str | None = None
    title: str | None = None
    kind: str | None = None


def _is_temporal(s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if s.dtype == object:
        try:
            parsed = pd.to_datetime(s, errors="coerce")
            return parsed.notna().mean() > 0.8
        except (ValueError, TypeError):
            return False
    return False


def pick_chart(
    df: pd.DataFrame,
    schema_id_cols: set[str] | None = None,
    hint: ChartHint | None = None,
) -> Chart:
    if df is None or df.empty:
        return Chart(figure=None, kind="empty", caption="No rows returned.")

    rows, cols = df.shape
    # ID-like columns (CustomerId, employee_id, …) are categorical for plotting,
    # even though their dtype is integer. `schema_id_cols` catches aliased IDs
    # that the name regex misses (e.g. `SELECT CustomerId AS Customer`).
    extra = schema_id_cols or set()
    id_cols = [c for c in df.columns if _looks_like_identifier(c) or c in extra]
    numeric_cols = [
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c]) and c not in id_cols
    ]
    non_numeric = [c for c in df.columns if c not in numeric_cols]

    # Single-value or single-row answers — no chart, render as text
    if rows == 1:
        return Chart(figure=None, kind="answer", caption="")

    # Single-column result — list, not chart
    if cols == 1:
        return Chart(figure=None, kind="list", caption=df.columns[0])

    # Cast ID columns to string so Plotly draws them as discrete categories
    # (axis ticks, legend entries) instead of a continuous numeric scale.
    plot_base = df.copy()
    for c in id_cols:
        plot_base[c] = plot_base[c].astype(str)

    # Time series -> line (multi-series when an extra categorical column is present)
    temporal = [c for c in plot_base.columns if _is_temporal(plot_base[c])]
    if temporal and numeric_cols:
        x = temporal[0]
        y = _hint_y_or_default(hint, numeric_cols)
        plot_df = plot_base.copy()
        plot_df[x] = pd.to_datetime(plot_df[x], errors="coerce")

        series_candidates = [c for c in non_numeric if c not in temporal]
        cand = _resolve_color(hint, plot_df.columns, series_candidates, exclude={x, y})
        color: str | None = None
        caption_suffix = ""
        if cand:
            n_series = plot_df[cand].nunique(dropna=True)
            MAX_SERIES = 12
            if 2 <= n_series <= MAX_SERIES:
                color = cand
                caption_suffix = f" by {cand}"
            elif n_series > MAX_SERIES:
                # Too many lines would be unreadable — keep the top-N categories by total y.
                top = (
                    plot_df.groupby(cand, dropna=True)[y]
                    .sum()
                    .sort_values(ascending=False)
                    .head(MAX_SERIES)
                    .index
                )
                plot_df = plot_df[plot_df[cand].isin(top)]
                color = cand
                caption_suffix = f" by {cand} (top {MAX_SERIES})"

        plot_df = plot_df.sort_values(x)
        fig = px.line(plot_df, x=x, y=y, color=color, markers=True)
        return Chart(figure=fig, kind="line",
                     caption=_caption(hint, f"{y} over {x}{caption_suffix}"))

    # One categorical + one numeric -> bar
    if non_numeric and numeric_cols and cols <= 3:
        x = non_numeric[0]
        y = _hint_y_or_default(hint, numeric_cols)
        plot_df = plot_base.sort_values(y, ascending=False).head(50)
        default_color = non_numeric[1] if len(non_numeric) > 1 else None
        color = _resolve_color(
            hint, plot_df.columns, [default_color] if default_color else [], exclude={x, y}
        )
        fig = px.bar(plot_df, x=x, y=y, color=color)
        fig.update_layout(xaxis={"categoryorder": "total descending"})
        return Chart(figure=fig, kind="bar", caption=_caption(hint, f"{y} by {x}"))

    # Two numerics -> scatter
    if len(numeric_cols) >= 2 and not temporal:
        default_y = numeric_cols[1]
        y = hint.y if (hint and hint.y in numeric_cols and hint.y != numeric_cols[0]) else default_y
        x = next((c for c in numeric_cols if c != y), numeric_cols[0])
        color = _resolve_color(hint, plot_base.columns, non_numeric, exclude={x, y})
        fig = px.scatter(plot_base, x=x, y=y, color=color)
        return Chart(figure=fig, kind="scatter", caption=_caption(hint, f"{y} vs {x}"))

    return Chart(figure=None, kind="table",
                 caption=_caption(hint, f"{rows} rows × {cols} cols"))


def _hint_y_or_default(hint: ChartHint | None, numeric_cols: list[str]) -> str:
    """Honor hint.y if it names a real numeric column; otherwise default to the first."""
    if hint and hint.y and hint.y in numeric_cols:
        return hint.y
    return numeric_cols[0]


def _resolve_color(
    hint: ChartHint | None,
    available: pd.Index | list[str],
    fallback_candidates: list[str | None],
    exclude: set[str],
) -> str | None:
    """Pick a color column: hint.color if valid, else the first usable fallback."""
    if hint and hint.color and hint.color in available and hint.color not in exclude:
        return hint.color
    for c in fallback_candidates:
        if c and c in available and c not in exclude:
            return c
    return None


def _caption(hint: ChartHint | None, default: str) -> str:
    """Use hint.title as the caption if provided; otherwise the auto-generated default."""
    if hint and hint.title:
        return hint.title
    return default
