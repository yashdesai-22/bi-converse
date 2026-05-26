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
question → (pattern router: match → inject 1 worked example) → schema-aware prompt
                                                                       ↓
                                                       HF Inference (Qwen2.5-Coder)
                                                                       ↓
                                       PLAN + ```sql```block + ```chart``` block
                                                                       ↓
        sqlglot parse + SELECT-only + identifier whitelist + EXPLAIN dry-run
                                                                       ↓
              ┌────── validation error ──┴── ok ──────┐
              ↓                                        ↓
   feed error to LLM (≤2 retries)             execute on SQLite
                                                       ↓
                            schema_inspect: PK/FK column aliases from the SQL
                                                       ↓
                       pick_chart(df, schema_id_cols, hint=chart_hint)
                                                       ↓
                         answer / list / line / bar / scatter / table / empty
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
│   ├── llm.py                InferenceClient + SYSTEM_PROMPT (with CoT PLAN) + extract_sql + refusal
│   ├── patterns.py           Pattern registry + regex router; injects one worked example per question
│   ├── schema_inspect.py     Parses validated SQL → set of result columns that alias a PK/FK
│   ├── sql_validator.py      sqlglot safety + identifier whitelist + EXPLAIN
│   ├── visualize.py          pick_chart(): result-shape → Chart (kind, figure, caption)
│   └── ui.py                 Theme CSS injection, hero(), card helpers, answer/list blocks
├── tests/
│   ├── test_validator.py        Happy paths + rejects DROP/UPDATE/multi-stmt/unknown ids
│   ├── test_patterns.py         Pattern router: positive routes, no-route cases, "by revenue" trap
│   ├── test_schema_inspect.py   PK/FK collection, alias resolution, aggregate-skip
│   ├── test_chart_hint.py       ```chart``` block parsing + fence regex hardening
│   └── test_visualize.py        Chart picker: single/multi-series line, series cap, ID handling, hint overrides
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
  - temporal + numeric → line (multi-series when an extra categorical column exists; capped at 12 series, top-by-total)
  - categorical + numeric → bar
  - 2 numerics → scatter
  - otherwise → table
- **The LLM emits a structured chart hint alongside SQL.** After the ```sql``` block,
  the model writes a ```chart``` block with `y:`, `color:`, `title:`, `kind:` keys (only
  `y` is meaningful most of the time). `parse_chart_hint` in `llm.py` returns a `ChartHint`,
  which flows through `QueryResult.chart_hint` into `pick_chart(... hint=...)`. The picker
  honors the hint when it validates against the actual DataFrame (column exists, isn't the
  x-axis, etc.) and **silently falls back to its heuristics on any mismatch** — the LLM
  proposes, the heuristic disposes. The `_FENCE` regex was hardened to exclude ```chart```
  blocks so they can't be mis-extracted as SQL.
- **ID-like columns (`CustomerId`, `employee_id`, `USER_ID`) are treated as categorical**
  even when their dtype is integer, and are cast to string before plotting so Plotly
  draws discrete category ticks instead of a continuous numeric axis. Detection has two layers:
  (1) name-based (`_looks_like_identifier` in `visualize.py`) for the unaliased common case;
  (2) **schema-aware** (`schema_inspect.identifier_result_columns`) which parses the validated
  SQL, walks the outermost SELECT's projection list, and flags any alias whose source is a PK
  or FK column. The app passes the resulting set into `pick_chart(df, schema_id_cols=...)`,
  catching `SELECT c.CustomerId AS Customer` patterns the name regex misses. Cardinality was
  rejected as too false-positive-prone on legitimately-unique measures.
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

Currently 81 tests, all passing. Validator covers SELECT happy path, JOIN+aggregate,
ORDER BY alias, CTE alias, write-statement rejection (DROP/DELETE/UPDATE/INSERT),
multi-statement rejection, unknown-table, unknown-column, parse-error. Pattern
router covers positive routes for each registered pattern, no-route cases for
plain ranking ("top 10 by revenue"), and aggregate uniqueness. Visualize covers
single- and multi-series line, the 12-series cap, and the answer/list/empty
short-circuits.

When extending the validator, add a regression test alongside. When adding a
new pattern, add a positive route test AND a no-route test for the most likely
phrase that should NOT trigger it.

## Deployment status

- **GitHub:** https://github.com/yashdesai-22/bi-converse (public, `main`)
- **Live demo:** https://bi-converse.streamlit.app/ (Streamlit Community Cloud,
  auto-redeploys on `git push origin main`)
- **Screenshot:** README has NO embed. The user explicitly opted out of both
  a GIF and a screenshot — do not re-pitch unless they ask.

## Pending user actions

1. (Optional) **CSV/Parquet upload** — broadens the demo's pitch from "Chinook"
   to "any dataset." ~1 hr.
2. (Optional) **Stream the LLM response token-by-token** — visceral demo polish.
   ~30 min.

Items already shipped (don't re-pitch):
- Few-shot examples — `SYSTEM_PROMPT` now has 3 worked examples; the pattern
  library (`src/patterns.py`) injects an additional per-question example when
  the question matches a known shape.
- Structured LLM output — model emits both ```sql``` and ```chart``` blocks;
  the chart hint flows into `pick_chart` to fix headline-metric selection.
- Schema-aware ID detection — `schema_inspect.identifier_result_columns`
  catches aliased PK/FK columns so Plotly treats them as categorical, not
  numeric (no more CustomerId on a continuous axis).

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

- **HF Inference free credits are limited.** Each question = 1 LLM call. Token
  budget is roughly: ~1,200 input (schema ~600 + system prompt ~600 + optional
  pattern injection ~400 when matched) + up to 768 output (`max_tokens` cap;
  actual ~250–500 with PLAN + SQL + chart block). Tens to low-hundreds of
  queries per month should stay free. If a 402 hits, swap to
  `HF_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct`.
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
streaming LLM output, CSV upload (BYO data).
Bad adds: auth, multi-tenancy, cost dashboards, RBAC, a full React rewrite.

**Architectural pattern to keep:** the project converged on "LLM proposes,
heuristic disposes" — the model emits chart hints, pattern picks, etc., and
a deterministic layer validates them and falls back silently on any mismatch.
This is the right shape for new improvements too: ask the LLM, validate the
answer, never trust blindly, always have a non-LLM fallback path.
