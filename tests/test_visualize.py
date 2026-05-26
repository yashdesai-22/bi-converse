"""Chart-picker tests — focused on the multi-series line branch plus regressions."""
from __future__ import annotations

import pandas as pd

from src.visualize import ChartHint, _looks_like_identifier, pick_chart


def _years(*ys):
    return pd.to_datetime([f"{y}-01-01" for y in ys])


def test_single_series_line_when_no_categorical():
    df = pd.DataFrame({"Year": _years(2010, 2011, 2012), "Revenue": [100, 150, 200]})
    chart = pick_chart(df)
    assert chart.kind == "line"
    assert len(chart.figure.data) == 1
    assert chart.caption == "Revenue over Year"


def test_multi_series_line_uses_categorical_as_color():
    df = pd.DataFrame({
        "Year": list(_years(2010, 2010, 2011, 2011, 2012, 2012)),
        "Genre": ["Rock", "Jazz", "Rock", "Jazz", "Rock", "Jazz"],
        "Revenue": [10, 5, 20, 7, 30, 9],
    })
    chart = pick_chart(df)
    assert chart.kind == "line"
    assert len(chart.figure.data) == 2  # one trace per genre
    assert chart.caption == "Revenue over Year by Genre"


def test_multi_series_line_caps_at_twelve_series_by_total():
    # 15 categories, with cat_00..cat_11 carrying the largest totals.
    rows = []
    for i in range(15):
        weight = 100 - i  # cat_00 highest, cat_14 lowest
        for year in (2010, 2011, 2012):
            rows.append({"Year": f"{year}-01-01", "Cat": f"cat_{i:02d}", "Value": weight})
    df = pd.DataFrame(rows)
    df["Year"] = pd.to_datetime(df["Year"])

    chart = pick_chart(df)
    assert chart.kind == "line"
    assert len(chart.figure.data) == 12
    assert "top 12" in chart.caption
    # The smallest-total categories must be dropped.
    plotted = {trace.name for trace in chart.figure.data}
    assert "cat_14" not in plotted and "cat_13" not in plotted and "cat_12" not in plotted


def test_single_category_does_not_introduce_color_grouping():
    # Only one distinct category -> no point splitting into series.
    df = pd.DataFrame({
        "Year": list(_years(2010, 2011, 2012)),
        "Genre": ["Rock", "Rock", "Rock"],
        "Revenue": [10, 20, 30],
    })
    chart = pick_chart(df)
    assert chart.kind == "line"
    assert len(chart.figure.data) == 1
    assert chart.caption == "Revenue over Year"


def test_single_row_returns_answer():
    df = pd.DataFrame({"total": [123]})
    chart = pick_chart(pd.DataFrame({"total_revenue": [123.45]}))
    assert chart.kind == "answer"
    assert chart.figure is None


def test_single_column_returns_list():
    df = pd.DataFrame({"Genre": ["Rock", "Jazz", "Metal"]})
    chart = pick_chart(df)
    assert chart.kind == "list"
    assert chart.figure is None
    assert chart.caption == "Genre"


def test_empty_returns_empty():
    chart = pick_chart(pd.DataFrame())
    assert chart.kind == "empty"
    assert chart.figure is None


# --- identifier detection -----------------------------------------------------

def test_identifier_name_detection_positive():
    for name in ["CustomerId", "EmployeeId", "customer_id", "Customer_Id", "USER_ID", "TrackID"]:
        assert _looks_like_identifier(name), name


def test_identifier_name_detection_negative():
    for name in ["valid", "paid", "Revenue", "Total", "id_name", "Name", "Country", "InvoiceDate"]:
        assert not _looks_like_identifier(name), name


def test_two_numerics_with_id_renders_bar_not_scatter():
    # SELECT CustomerId, SUM(Total) AS Revenue ... — both columns are int dtype.
    df = pd.DataFrame({"CustomerId": [1, 2, 3, 4], "Revenue": [10, 30, 20, 40]})
    chart = pick_chart(df)
    assert chart.kind == "bar"
    assert chart.caption == "Revenue by CustomerId"
    # The x-axis values should be strings (so Plotly draws discrete category ticks).
    x_values = list(chart.figure.data[0].x)
    assert all(isinstance(v, str) for v in x_values), x_values


def test_id_column_with_temporal_becomes_series_color():
    # SELECT InvoiceDate, CustomerId, Total ... — CustomerId becomes the line series.
    df = pd.DataFrame({
        "InvoiceDate": pd.to_datetime([
            "2010-01-01", "2010-01-01",
            "2011-01-01", "2011-01-01",
            "2012-01-01", "2012-01-01",
        ]),
        "CustomerId": [1, 2, 1, 2, 1, 2],
        "Total": [100, 50, 120, 60, 140, 70],
    })
    chart = pick_chart(df)
    assert chart.kind == "line"
    assert len(chart.figure.data) == 2
    assert "by CustomerId" in chart.caption


def test_all_id_columns_falls_back_to_table():
    # No usable numeric measure — picker has nothing to plot.
    df = pd.DataFrame({"CustomerId": [1, 2, 3], "EmployeeId": [10, 20, 30]})
    chart = pick_chart(df)
    assert chart.kind == "table"


def test_non_id_int_column_still_numeric():
    # A regular numeric column ("Year" as int) keeps numeric semantics.
    df = pd.DataFrame({"Country": ["USA", "UK", "DE"], "Year": [2010, 2011, 2012]})
    chart = pick_chart(df)
    assert chart.kind == "bar"
    assert chart.caption == "Year by Country"


def test_schema_id_cols_catches_aliased_identifier():
    # SELECT c.CustomerId AS Customer, SUM(...) AS Revenue --
    # the result column is `Customer` so the name regex misses it,
    # but the schema-aware caller knows it's a PK reference.
    df = pd.DataFrame({"Customer": [1, 2, 3, 4], "Revenue": [10, 30, 20, 40]})
    chart = pick_chart(df, schema_id_cols={"Customer"})
    assert chart.kind == "bar"
    assert chart.caption == "Revenue by Customer"
    assert all(isinstance(v, str) for v in chart.figure.data[0].x)


def test_schema_id_cols_none_falls_back_to_name_heuristic_only():
    # Same df, no schema hint — column "Customer" looks like an int measure to the
    # name regex, so we'd land on scatter rather than bar.
    df = pd.DataFrame({"Customer": [1, 2, 3, 4], "Revenue": [10, 30, 20, 40]})
    chart = pick_chart(df)
    assert chart.kind == "scatter"


# --- chart hints --------------------------------------------------------------

def _cumulative_df():
    """Mimics the 'cumulative revenue over time' query: temporal + 2 numerics."""
    months = pd.to_datetime(["2010-01-01", "2010-02-01", "2010-03-01"])
    return pd.DataFrame({
        "Month": months,
        "MonthlyRevenue": [100, 150, 200],
        "CumulativeRevenue": [100, 250, 450],
    })


def test_hint_y_overrides_default_in_line_branch():
    # Default picks first numeric (MonthlyRevenue); hint forces CumulativeRevenue.
    df = _cumulative_df()
    chart = pick_chart(df, hint=ChartHint(y="CumulativeRevenue"))
    assert chart.kind == "line"
    # Plotly's y values for the single trace should match cumulative, not monthly.
    assert list(chart.figure.data[0].y) == [100, 250, 450]
    assert chart.caption.startswith("CumulativeRevenue")


def test_invalid_hint_y_falls_back_to_default():
    df = _cumulative_df()
    chart = pick_chart(df, hint=ChartHint(y="DoesNotExist"))
    assert chart.kind == "line"
    assert list(chart.figure.data[0].y) == [100, 150, 200]  # default = first numeric


def test_hint_title_replaces_caption():
    df = _cumulative_df()
    chart = pick_chart(df, hint=ChartHint(y="CumulativeRevenue", title="Cumulative growth"))
    assert chart.caption == "Cumulative growth"


def test_hint_color_overrides_default_series_in_bar():
    # Bar with two categoricals — default picks the second non_numeric as color.
    # Hint forces the first instead.
    df = pd.DataFrame({
        "Country": ["USA", "USA", "UK", "UK"],
        "Genre": ["Rock", "Jazz", "Rock", "Jazz"],
        "Revenue": [100, 50, 80, 40],
    })
    chart = pick_chart(df, hint=ChartHint(color="Country"))
    assert chart.kind == "bar"
    # Plotly creates one trace per color category — Country has 2 values -> 2 traces.
    assert len(chart.figure.data) == 2


def test_hint_y_equal_to_x_is_ignored():
    # Hint pointing at the temporal x column is invalid — must fall back.
    df = _cumulative_df()
    chart = pick_chart(df, hint=ChartHint(y="Month"))
    assert chart.kind == "line"
    assert list(chart.figure.data[0].y) == [100, 150, 200]  # default kept


# --- bucket labels (date_dim Quarter/Week strings) ----------------------------

def test_quarter_label_renders_as_line_in_chronological_order():
    df = pd.DataFrame({
        "Quarter": ["2021-Q3", "2021-Q1", "2021-Q4", "2021-Q2"],
        "NewCustomers": [10, 15, 8, 12],
    })
    chart = pick_chart(df)
    assert chart.kind == "line"
    assert list(chart.figure.data[0].x) == ["2021-Q1", "2021-Q2", "2021-Q3", "2021-Q4"]
    assert list(chart.figure.data[0].y) == [15, 12, 10, 8]


def test_week_label_renders_as_line_in_chronological_order():
    df = pd.DataFrame({
        "Week": ["2021-W22", "2021-W03", "2021-W15", "2021-W01"],
        "Revenue": [8, 15, 10, 12],
    })
    chart = pick_chart(df)
    assert chart.kind == "line"
    assert list(chart.figure.data[0].x) == ["2021-W01", "2021-W03", "2021-W15", "2021-W22"]


def test_bucket_label_with_color_series():
    # Quarter on x, Genre as series color, Revenue as y.
    df = pd.DataFrame({
        "Quarter": ["2021-Q1", "2021-Q1", "2021-Q2", "2021-Q2"],
        "Genre":   ["Rock",    "Jazz",    "Rock",    "Jazz"],
        "Revenue": [100, 50, 120, 60],
    })
    chart = pick_chart(df)
    assert chart.kind == "line"
    assert len(chart.figure.data) == 2  # one trace per genre


def test_non_bucket_string_still_falls_through_to_bar():
    # Sanity: arbitrary categorical strings must NOT be misclassified as temporal.
    df = pd.DataFrame({"Country": ["USA", "UK", "DE"], "Revenue": [100, 80, 60]})
    chart = pick_chart(df)
    assert chart.kind == "bar"
