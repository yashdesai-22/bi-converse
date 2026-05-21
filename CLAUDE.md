# CLAUDE.md

Working context for this repo — read this before making changes.

## What this project is

**bi-converse** is a Conversational BI Platform built as a portfolio/resume project.
Users ask questions in plain English; a HuggingFace LLM writes SQL with schema-aware
prompting; the SQL is validated and dry-run before it touches the database; results
render as interactive Plotly charts in a Streamlit app.

The project exists to back a specific resume bullet — design decisions favor what
makes the demo more convincing to a recruiter, **not** production hardening.

## Tech stack

- **UI**: Streamlit 1.55+ (dark theme, custom CSS, no external component libs)
- **LLM**: HuggingFace Inference API via `huggingface_hub.InferenceClient`
  - Default model: `Qwen/Qwen2.5-Coder-32B-Instruct`
  - Provider: `"auto"` (HF routes to whichever provider is available)
  - Token via `HF_TOKEN` env var (local) or Streamlit `st.secrets` (cloud)
- **Database**: SQLite (bundled Chinook sample, ~1 MB, downloaded on first run)
- **SQL safety**: `sqlglot` for parsing + validation
- **Charts**: Plotly Express + Graph Objects
- **Tests**: pytest

## Pipeline

```
question → schema-aware prompt → HF Inference (Qwen2.5-Coder)
                                       ↓
                                generated SQL
                                       ↓
   sqlglot parse + SELECT-only + identifier whitelist + EXPLAIN dry-run
                                       ↓
              ┌────── validation error ──┴── ok ──────┐
              ↓                                        ↓
   feed error to LLM (≤2 retries)             execute on SQLite
                                                       ↓
                                  shape-aware render: answer / list /
                                  line / bar / scatter / table / empty
```

Plus a **refusal path**: the LLM can emit `CANNOT_ANSWER: <reason>` instead of
SQL when a question is vague or asks about data that isn't in the schema. This
bypasses the retry loop and shows a friendly amber card.

## File map

```
bi-converse/
├── app.py                    Streamlit entry. Orchestrates retry loop, renders results.
├── requirements.txt          streamlit, plotly, sqlalchemy, sqlglot, huggingface_hub, pytest
├── .env.example              HF_TOKEN slot for local dev
├── .gitignore                Excludes .env, .venv, data/*.sqlite, .claude/
├── README.md                 Public-facing. Setup, deploy guides, design notes.
├── CLAUDE.md                 This file.
├── .streamlit/
│   ├── config.toml           Dark theme (violet accent #7C3AED), minimal toolbar
│   └── secrets.toml.example  Template for Streamlit Cloud "Secrets" field
├── src/
│   ├── __init__.py
│   ├── seed.py               Downloads Chinook_Sqlite.sqlite into data/ on first run
│   ├── db.py                 SQLAlchemy engine, schema introspection, query exec
│   ├── llm.py                InferenceClient + SYSTEM_PROMPT + extract_sql + refusal
│   ├── sql_validator.py      sqlglot safety + identifier whitelist + EXPLAIN
│   ├── visualize.py          pick_chart(): result-shape → Chart (kind, figure, caption)
│   └── ui.py                 Theme CSS injection, hero(), card helpers, answer/list blocks
├── tests/
│   └── test_validator.py     Happy paths + rejects DROP/UPDATE/multi-stmt/unknown ids
└── data/                     Created at runtime; chinook.sqlite cached here (gitignored)
```

## Key design decisions (don't undo these)

- **Schema is fully introspected at startup** and dumped into the prompt as
  `CREATE TABLE` DDL + FK comments + one sample row per table. See
  `db.render_schema`. This is the "schema-aware prompting" on the resume.
- **The validator does NOT trust the LLM.** `sqlglot` parses, walks the tree
  for forbidden node types (`Insert`, `Update`, `Delete`, `Drop`, `Alter`,
  `Pragma`, …), whitelists every referenced table and column against the live
  schema (allowing aliases and CTE names too), and runs `EXPLAIN` as a final
  dry-run. Identifier matching is case-insensitive.
- **Retry loop is bounded at 2 retries.** Errors get fed back into the next
  prompt as context. Unanswerable refusals (`CANNOT_ANSWER:`) short-circuit
  the loop — don't burn tokens trying to coerce SQL.
- **Shape-aware rendering** in `visualize.pick_chart`:
  - 1 row → `kind="answer"` (rendered as labeled key/value card; no chart)
  - 1 column, N rows → `kind="list"` (numbered list; no chart)
  - empty → `kind="empty"` (info banner)
  - temporal + numeric → line
  - categorical + numeric → bar
  - 2 numerics → scatter
  - otherwise → table
- **The sidebar is always open by default** (`initial_sidebar_state="expanded"`)
  but users CAN collapse it via the chevron. Don't hide the collapse button.
- **Two scrollable sidebar blocks** ("Database Tables" + "Sample questions"),
  each sized via CSS `calc((100vh - 180px) / 2)` so they fit the viewport
  without sidebar-level scroll. `min-height: 160px` for tiny windows.
- **Streamlit chrome is hidden** via CSS (`#MainMenu`, `footer`,
  `stDecoration`, `stStatusWidget`) — but NOT the `stToolbar` itself, because
  the sidebar collapse control lives inside it. Hiding stToolbar = locked-out
  sidebar (we've already hit this bug; don't reintroduce).

## Running locally

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env       # then edit, add HF_TOKEN
streamlit run app.py
```

Python 3.14 on Windows is the dev environment. No venv has been set up — pip
installs go to system Python.

## Tests

```powershell
python -m pytest tests/ -q
```

Currently 12 tests, all passing. Covers SELECT happy path, JOIN+aggregate,
ORDER BY alias, CTE alias, write-statement rejection (DROP/DELETE/UPDATE/INSERT),
multi-statement rejection, unknown-table, unknown-column, parse-error.

When extending the validator, add a regression test alongside.

## Deployment status

- **GitHub:** https://github.com/yashdesai-22/bi-converse (public, `main`)
- **Live demo:** https://bi-converse.streamlit.app/ (Streamlit Community Cloud,
  auto-redeploys on `git push origin main`)
- **Screenshot:** README has NO embed. The user explicitly opted out of both
  a GIF and a screenshot — do not re-pitch unless they ask.

## Pending user actions

1. (Optional) **Add a few-shot examples block to `SYSTEM_PROMPT`** — would
   measurably improve SQL quality on complex BI questions. ~30 min.
2. (Optional) **CSV/Parquet upload** — broadens the demo's pitch from "Chinook"
   to "any dataset." ~1 hr.
3. (Optional) **Stream the LLM response token-by-token** — visceral demo polish.
   ~30 min.

No blocking actions remaining. Project is shipped.

## Sample questions

28 sample questions live in `app.py` inside `main()` — organized by what render
mode they exercise (scalar/answer, ranking/bar, time series/line, comparative,
list, edge cases). When adding more, ensure they map cleanly to actual Chinook
columns — the model hallucinates column names when a question implies data that
isn't there (e.g. earlier we had "customer acquisition" which implied a
`CreatedDate` column; we changed it to "by first invoice date" to point at real
data).

## Known constraints / quirks

- **HF Inference free credits are limited.** Each question = 1 LLM call (~600
  input + ~100 output tokens). Tens to low-hundreds of queries per month should
  stay free. If a 402 hits, swap to `HF_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct`.
- **The Chinook schema has no creation/timestamp columns on entities.** Only
  `Invoice.InvoiceDate` exists. Questions about "growth," "acquisition," or
  "trend" should be phrased relative to `InvoiceDate`.
- **Streamlit Cloud uses `st.secrets`, not env vars.** `app.py` bridges
  `st.secrets["HF_TOKEN"]` into `os.environ` before calling `get_client()`.
- **Windows line endings.** Git warns about CRLF on every commit — this is
  harmless. Don't add a `.gitattributes` unless asked.
- **PowerShell stderr noise.** When invoking native CLIs (`gh`, `git`),
  PowerShell prints stderr as red NativeCommandError text even on success.
  The actual exit code and output show the real status.

## How to think about new features

Before adding anything, ask: *does this strengthen the resume story?* Good adds:
better example questions, clearer error states, polished screenshots, an
"Explain SQL" feature (we built and then removed this — could come back),
streaming LLM output, few-shot prompt examples, CSV upload (BYO data).
Bad adds: auth, multi-tenancy, cost dashboards, RBAC, a full React rewrite.
