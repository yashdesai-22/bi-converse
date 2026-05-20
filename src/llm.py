"""HuggingFace Inference client + schema-aware prompt builder."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from huggingface_hub import InferenceClient

DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"
DEFAULT_PROVIDER = "auto"

SYSTEM_PROMPT = """You are a senior analytics engineer. Translate the user's question into a single SQLite SELECT query.

Rules:
- Output ONLY the SQL inside a ```sql ... ``` fenced block. No prose, no explanation.
- Use SQLite syntax. Quote identifiers with double quotes if they contain spaces or reserved words.
- One statement only. SELECT only — never INSERT, UPDATE, DELETE, DROP, ALTER, ATTACH, PRAGMA.
- Reference only tables and columns that exist in the schema below.
- Prefer explicit JOINs over implicit ones. Use the foreign keys shown.
- When the question implies aggregation, use GROUP BY and aliased aggregate columns.
- Add a LIMIT (default 1000) if the question does not imply otherwise.
- If the question is ambiguous, pick the most useful BI interpretation."""


@dataclass
class LLMResponse:
    sql: str
    raw: str


class LLMError(RuntimeError):
    pass


def build_user_prompt(schema: str, question: str, prior_error: str | None = None) -> str:
    parts = [
        "Database schema:",
        "```sql",
        schema,
        "```",
        "",
        f"Question: {question}",
    ]
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
        max_tokens=512,
        temperature=0.1,
    )
    raw = completion.choices[0].message.content or ""
    return LLMResponse(sql=extract_sql(raw), raw=raw)


_FENCE = re.compile(r"```(?:sql|sqlite)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def extract_sql(raw: str) -> str:
    """Pull SQL out of a fenced block; fall back to stripped text."""
    m = _FENCE.search(raw)
    sql = m.group(1) if m else raw
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise LLMError("Model returned no SQL.")
    return sql
