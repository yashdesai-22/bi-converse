# Conversational BI Platform

Ask questions in plain English. A HuggingFace LLM writes SQL using **schema-aware
prompting**, the query is **parsed, sandboxed, and dry-run** before it touches the
database, and the result is rendered as an interactive Plotly chart in Streamlit.

## Pipeline

```
question  ─►  schema-aware prompt  ─►  HF Inference API (Qwen2.5-Coder)
                                              │
                                              ▼
                                      generated SQL
                                              │
                          sqlglot parse + SELECT-only + identifier
                          whitelist + SQLite EXPLAIN (dry-run)
                                              │
                              ┌───── error ───┴──── ok ─────┐
                              ▼                              ▼
                  feed error back to LLM             execute on SQLite
                     (up to 2 retries)                       │
                                                             ▼
                                              auto-chosen Plotly chart
                                                  + raw result table
```

## Setup

```bash
git clone <repo> && cd bi-converse
python -m venv .venv
.venv\Scripts\Activate.ps1     # PowerShell on Windows
# source .venv/bin/activate    # macOS / Linux
pip install -r requirements.txt

cp .env.example .env
# edit .env and add your HF_TOKEN
```

Get a free token at <https://huggingface.co/settings/tokens> (read scope is enough).

## Run

```bash
streamlit run app.py
```

On first launch the app downloads the [Chinook](https://github.com/lerocha/chinook-database)
sample database (~1 MB) into `data/`. No other setup needed.

## Try these questions

- *Top 10 customers by total spend*
- *Monthly invoice revenue trend*
- *Revenue by genre*
- *Which country has the most customers?*
- *Average invoice total per billing country*

## Tests

```bash
pytest
```

The validator suite covers happy paths plus rejection of `DROP`/`DELETE`/`UPDATE`/
`INSERT`, multi-statement input, unknown tables, and unknown columns.

## Project layout

```
bi-converse/
├── app.py                  Streamlit UI, orchestration, retry loop
├── src/
│   ├── seed.py             Downloads Chinook on first run
│   ├── db.py               SQLAlchemy engine, schema introspection
│   ├── llm.py              HF InferenceClient + schema-aware prompt
│   ├── sql_validator.py    sqlglot safety + EXPLAIN dry-run
│   └── visualize.py        Result-shape → Plotly chart heuristic
└── tests/
    └── test_validator.py
```

## Design notes

- **Schema-aware prompting.** `db.introspect` dumps tables, column types, primary
  keys, foreign keys, and one sample row per table. `db.render_schema` formats
  that into compact `CREATE TABLE`-style DDL the model can ground on.
- **Defense in depth.** The model is instructed to emit SELECT-only SQL, but the
  validator does not trust it: `sqlglot` parses the statement, walks the tree for
  forbidden nodes (`Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Pragma`, …),
  whitelists every referenced table and column against the live schema, and
  finally runs `EXPLAIN` to catch anything the parser allowed but SQLite would
  reject.
- **Bounded retry.** When validation or execution fails, the error is appended
  to the next prompt so the model can self-correct. Capped at 2 retries to avoid
  burning tokens.
- **Chart selection.** `visualize.pick_chart` reads the DataFrame shape — single
  scalar → KPI, temporal + numeric → line, categorical + numeric → bar, two
  numerics → scatter, otherwise → table.
