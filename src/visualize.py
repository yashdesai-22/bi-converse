"""Heuristic: pick a sensible Plotly chart from a result DataFrame."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


@dataclass
class Chart:
    figure: go.Figure | None
    kind: str  # "answer" | "list" | "line" | "bar" | "scatter" | "table" | "empty"
    caption: str


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


def pick_chart(df: pd.DataFrame) -> Chart:
    if df is None or df.empty:
        return Chart(figure=None, kind="empty", caption="No rows returned.")

    rows, cols = df.shape
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    non_numeric = [c for c in df.columns if c not in numeric_cols]

    # Single-value or single-row answers — no chart, render as text
    if rows == 1:
        return Chart(figure=None, kind="answer", caption="")

    # Single-column result — list, not chart
    if cols == 1:
        return Chart(figure=None, kind="list", caption=df.columns[0])

    # Time series -> line
    temporal = [c for c in df.columns if _is_temporal(df[c])]
    if temporal and numeric_cols:
        x = temporal[0]
        y = numeric_cols[0]
        plot_df = df.copy()
        plot_df[x] = pd.to_datetime(plot_df[x], errors="coerce")
        plot_df = plot_df.sort_values(x)
        fig = px.line(plot_df, x=x, y=y, markers=True)
        return Chart(figure=fig, kind="line", caption=f"{y} over {x}")

    # One categorical + one numeric -> bar
    if non_numeric and numeric_cols and cols <= 3:
        x = non_numeric[0]
        y = numeric_cols[0]
        plot_df = df.sort_values(y, ascending=False).head(50)
        color = non_numeric[1] if len(non_numeric) > 1 else None
        fig = px.bar(plot_df, x=x, y=y, color=color)
        fig.update_layout(xaxis={"categoryorder": "total descending"})
        return Chart(figure=fig, kind="bar", caption=f"{y} by {x}")

    # Two numerics -> scatter
    if len(numeric_cols) >= 2 and not temporal:
        x, y = numeric_cols[0], numeric_cols[1]
        color = non_numeric[0] if non_numeric else None
        fig = px.scatter(df, x=x, y=y, color=color)
        return Chart(figure=fig, kind="scatter", caption=f"{y} vs {x}")

    return Chart(figure=None, kind="table", caption=f"{rows} rows × {cols} cols")
