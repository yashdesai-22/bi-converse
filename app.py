"""Conversational BI — Streamlit entry point."""
from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.db import get_engine, introspect, render_schema, run_query
from src.llm import LLMError, generate_sql, get_client
from src.sql_validator import ValidationError, validate
from src.visualize import pick_chart

load_dotenv()

MAX_RETRIES = 2  # bounded LLM retry on validation/exec error

st.set_page_config(
    page_title="Conversational BI",
    page_icon="📊",
    layout="wide",
)


@dataclass
class QueryResult:
    question: str
    sql: str
    df: pd.DataFrame | None
    error: str | None
    attempts: int
    raw_responses: list[str]


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
            )
        except (ValidationError, LLMError) as e:
            prior_error = str(e)
        except Exception as e:  # noqa: BLE001 — show any execution failure to the LLM
            prior_error = f"Execution error: {e}"

    return QueryResult(
        question=question, sql=last_sql, df=None,
        error=prior_error, attempts=MAX_RETRIES + 1, raw_responses=raw_responses,
    )


def main() -> None:
    st.title("📊 Conversational BI")
    st.caption(
        "Ask questions in plain English. An LLM writes SQL, we validate it, "
        "run it on SQLite, and chart the result."
    )

    if not os.getenv("HF_TOKEN"):
        st.error("Set `HF_TOKEN` in `.env` (copy `.env.example`).")
        st.stop()

    engine, schema, schema_text = load_db()
    client = load_llm()

    with st.sidebar:
        st.subheader("Database")
        st.write(f"**{len(schema)}** tables")
        for t in schema:
            with st.expander(t.name):
                st.code(
                    "\n".join(f"{c.name}: {c.type}" for c in t.columns),
                    language="text",
                )
        st.divider()
        st.subheader("Examples")
        examples = [
            "Top 10 customers by total spend",
            "Monthly invoice revenue trend",
            "Revenue by genre",
            "Which country has the most customers?",
            "Average invoice total per billing country",
        ]
        for ex in examples:
            if st.button(ex, use_container_width=True):
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
    with st.chat_message("user"):
        st.write(result.question)

    with st.chat_message("assistant"):
        if result.error:
            st.error(
                f"Couldn't answer after {result.attempts} attempt(s): {result.error}"
            )
            if result.sql:
                with st.expander("Last SQL attempted"):
                    st.code(result.sql, language="sql")
            return

        retry_note = f" (after {result.attempts - 1} retry)" if result.attempts > 1 else ""
        st.markdown(f"**Result**{retry_note}")

        chart = pick_chart(result.df)
        if chart.figure is not None:
            st.plotly_chart(chart.figure, use_container_width=True)
            st.caption(chart.caption)

        st.dataframe(result.df, use_container_width=True, hide_index=True)

        with st.expander("Generated SQL"):
            st.code(result.sql, language="sql")


if __name__ == "__main__":
    main()
