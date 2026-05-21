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
- Reference only tables and columns that exist in the schema below. Never invent column names.
- If the question implies data that isn't directly stored (e.g. "customer creation date" when the schema has no such column), derive it from related data (e.g. MIN(InvoiceDate) per customer) ONLY IF the derivation is unambiguous.
- Prefer explicit JOINs over implicit ones. Use the foreign keys shown.
- When the question implies aggregation, use GROUP BY and aliased aggregate columns.
- Add a LIMIT (default 1000) if the question does not imply otherwise.

When to refuse — output exactly one line `CANNOT_ANSWER: <one-sentence reason>` and nothing else (no SQL, no fenced block) if any of these apply:
- The question is too vague to map to a single specific query (multiple equally valid interpretations).
- The required data isn't in the schema and cannot be reasonably derived from what is.
- The question is not a data question at all (e.g. greeting, opinion, off-topic).
Examples of refusals:
  CANNOT_ANSWER: The schema has no column tracking when customers signed up; only purchase dates are recorded.
  CANNOT_ANSWER: "Best" is ambiguous — please clarify whether you mean by revenue, by unit count, or by rating."""


@dataclass
class LLMResponse:
    sql: str
    raw: str


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
_REFUSAL = re.compile(r"CANNOT_ANSWER\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE)


def extract_sql(raw: str) -> str:
    """Pull SQL out of a fenced block; raise UnanswerableError on a refusal marker."""
    fence = _FENCE.search(raw)
    if fence:
        sql = fence.group(1).strip().rstrip(";").strip()
        if sql:
            return sql

    # No fenced SQL — check for a refusal marker
    refusal = _REFUSAL.search(raw)
    if refusal:
        raise UnanswerableError(refusal.group(1).strip())

    # Fall back to stripped text (legacy behavior)
    sql = raw.strip().rstrip(";").strip()
    if not sql:
        raise LLMError("Model returned no SQL.")
    return sql
