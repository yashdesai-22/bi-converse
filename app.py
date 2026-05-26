"""Conversational BI — Streamlit entry point."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.db import get_engine, introspect, render_schema, run_query
from src.llm import LLMError, UnanswerableError, generate_sql, get_client
from src.schema_inspect import identifier_result_columns
from src.sql_validator import ValidationError, validate
from src.ui import answer_block, card_close, card_open, hero, inject_theme, list_block
from src.visualize import ChartHint, pick_chart

load_dotenv()

# Streamlit Community Cloud exposes secrets via st.secrets, not env vars.
# Bridge them so the rest of the codebase can keep reading os.getenv("HF_TOKEN").
if not os.getenv("HF_TOKEN"):
    try:
        os.environ["HF_TOKEN"] = st.secrets["HF_TOKEN"]
    except (KeyError, FileNotFoundError):
        pass

MAX_RETRIES = 2  # bounded LLM retry on validation/exec error

st.set_page_config(
    page_title="Conversational BI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_theme()


@dataclass
class QueryResult:
    question: str
    sql: str
    df: pd.DataFrame | None
    error: str | None
    attempts: int
    raw_responses: list[str]
    unanswerable_reason: str | None = None
    id_columns: set[str] = field(default_factory=set)
    chart_hint: ChartHint | None = None


@st.cache_resource(show_spinner="Loading database…")
def load_db():
    engine = get_engine()
    schema = introspect(engine)
    return engine, schema, render_schema(schema)


@st.cache_resource(show_spinner="Connecting to HuggingFace…")
def load_llm():
    return get_client()


def answer(question: str, engine, schema, schema_text: str, client) -> QueryResult:
    raw_responses: list[str] = []
    prior_error: str | None = None
    last_sql = ""

    for attempt in range(1, MAX_RETRIES + 2):  # initial + retries
        try:
            resp = generate_sql(question, schema_text, prior_error=prior_error, client=client)
            raw_responses.append(resp.raw)
            last_sql = resp.sql
            validated = validate(resp.sql, schema, engine)
            df = run_query(validated.sql, engine)
            return QueryResult(
                question=question, sql=validated.sql, df=df,
                error=None, attempts=attempt, raw_responses=raw_responses,
                id_columns=identifier_result_columns(validated.sql, schema),
                chart_hint=resp.hint,
            )
        except UnanswerableError as e:
            # Model declined — do not retry; surface the reason to the user.
            return QueryResult(
                question=question, sql="", df=None, error=None,
                attempts=attempt, raw_responses=raw_responses,
                unanswerable_reason=e.reason,
            )
        except (ValidationError, LLMError) as e:
            prior_error = str(e)
        except Exception as e:  # noqa: BLE001 — surface execution failure to the LLM
            prior_error = f"Execution error: {e}"

    return QueryResult(
        question=question, sql=last_sql, df=None,
        error=prior_error, attempts=MAX_RETRIES + 1, raw_responses=raw_responses,
    )


def main() -> None:
    hero(
        title="Conversational BI",
        subtitle=(
            "Ask questions in plain English. An LLM writes SQL with schema-aware "
            "prompting, the query is parsed and dry-run before it touches the database, "
            "and the result renders as an interactive chart."
        ),
        badges=[
            ("HuggingFace Inference", ""),
            ("SQLite · Chinook", "cyan"),
            ("Plotly + Streamlit", "slate"),
        ],
    )

    if not os.getenv("HF_TOKEN"):
        st.error("Set `HF_TOKEN` in `.env` (copy `.env.example`).")
        st.stop()

    engine, schema, schema_text = load_db()
    client = load_llm()

    with st.sidebar:
        st.header("Database Tables")
        with st.container(height=200, border=True):
            for t in schema:
                with st.expander(t.name):
                    st.code(
                        "\n".join(f"{c.name}: {c.type}" for c in t.columns),
                        language="text",
                    )

        st.header("Sample questions")
        examples = [
            # — Single-value answers (showcase the answer card) —
            "How many customers are there in total?",
            "What is the total lifetime revenue?",
            "Which customer placed the single largest invoice ever?",
            "What percentage of total revenue comes from the top 5 customers?",
            "Which employee's customers have the highest average spend?",
            # — Rankings with multi-table joins —
            "Top 10 customers by total spend",
            "Top 5 best-selling artists by total revenue",
            "Top 10 tracks by number of playlist appearances",
            "For each genre, what is the top-selling track?",
            "Top 3 highest-grossing albums per genre",
            "Artists whose albums span the most distinct genres",
            "Albums where every track is longer than 4 minutes",
            # — Time series with window functions —
            "Monthly revenue trend with year-over-year growth percentage",
            "Cumulative revenue over time",
            "New customers acquired per quarter (by first invoice date)",
            "Top-selling genre in each year",
            # — Comparative aggregates —
            "Customers whose total spend is above the average customer spend",
            "Each employee's total sales compared to the company average",
            "Revenue contribution percentage by country",
            "Average days between first and last purchase per customer",
            "Top 3 genres by revenue within each country",
            # — Lists —
            "List all genres in the catalog",
            "Customers who bought tracks from more than 5 different genres",
            "Tracks longer than 10 minutes",
            "Playlists containing more than 100 tracks",
            # — Edge cases —
            "Customers who have never bought anything",
            "Albums with no tracks",
            "Genres with no sales",
        ]
        with st.container(height=200, border=True):
            for ex in examples:
                if st.button(ex, use_container_width=True, key=f"ex_{ex}"):
                    st.session_state["pending_question"] = ex

    if "history" not in st.session_state:
        st.session_state["history"] = []

    for past in st.session_state["history"]:
        _render_result(past)

    question = st.chat_input("Ask a question about the data…")
    if not question and "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")

    if question:
        with st.spinner("Thinking…"):
            result = answer(question, engine, schema, schema_text, client)
        st.session_state["history"].append(result)
        _render_result(result)


def _render_result(result: QueryResult) -> None:
    with st.chat_message("user", avatar="🧑"):
        st.write(result.question)

    with st.chat_message("assistant", avatar="📊"):
        if result.unanswerable_reason:
            st.markdown(
                f'<div class="card" style="border-color: rgba(245,158,11,0.35); '
                f'background: rgba(245,158,11,0.06);">'
                f'<div class="card-title" style="color:#FBBF24;">I can\'t answer that</div>'
                f'<div style="font-size:15px; line-height:1.5;">{result.unanswerable_reason}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )
            return

        if result.error:
            st.error(
                f"Couldn't answer after {result.attempts} attempt(s): {result.error}"
            )
            if result.sql:
                with st.expander("Last SQL attempted"):
                    st.code(result.sql, language="sql")
            return

        df = result.df
        rows, cols = (df.shape if df is not None else (0, 0))
        chart = pick_chart(df, schema_id_cols=result.id_columns, hint=result.chart_hint)

        # Empty result — say so, no table or chart
        if chart.kind == "empty":
            st.info("Query ran successfully but returned no rows.")
            with st.expander("Generated SQL"):
                st.code(result.sql, language="sql")
            return

        # Single-row answer — render as a labeled answer card, skip chart + table
        if chart.kind == "answer":
            answer_block(df.iloc[0].to_dict())
            with st.expander("Generated SQL"):
                st.code(result.sql, language="sql")
            return

        # Single-column result — render as a list, skip chart
        if chart.kind == "list":
            list_block(df[df.columns[0]].tolist(), chart.caption)
            with st.expander("Generated SQL"):
                st.code(result.sql, language="sql")
            return

        # Full result — chart (if any), then the data table with stats in its header
        if chart.figure is not None:
            card_open("Visualization")
            st.plotly_chart(chart.figure, use_container_width=True, key=f"chart_{id(result)}")
            st.caption(chart.caption)
            card_close()

        retry_note = f"after {result.attempts - 1} retry" if result.attempts > 1 else "first try"
        data_title = f"Data · {rows:,} rows × {cols} columns · {retry_note}"
        card_open(data_title)
        st.dataframe(df, use_container_width=True, hide_index=True)
        card_close()

        with st.expander("Generated SQL"):
            st.code(result.sql, language="sql")


if __name__ == "__main__":
    main()
