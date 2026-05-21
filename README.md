# Conversational BI Platform

> **Live demo:** _[deploy this app and paste the URL here]_

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

## Setup (local)

```bash
git clone <repo> && cd bi-converse
python -m venv .venv
.venv\Scripts\Activate.ps1     # PowerShell on Windows
# source .venv/bin/activate    # macOS / Linux
pip install -r requirements.txt

cp .env.example .env
# edit .env and add your HF_TOKEN
```

Get a free token at <https://huggingface.co/settings/tokens> (read scope or
"Make calls to Inference Providers" is enough).

## Run

```bash
streamlit run app.py
```

On first launch the app downloads the [Chinook](https://github.com/lerocha/chinook-database)
sample database (~1 MB) into `data/`. No other setup needed.

## Try these questions

- *How many customers are there in total?* → single-value answer card
- *Top 10 customers by total spend* → ranked bar chart
- *Monthly invoice revenue trend* → line chart
- *List all genres in the catalog* → numbered list
- *Customers who have never bought anything* → empty-state UI

The full sample-questions list lives in the sidebar inside the app.

## Deploying

### Streamlit Community Cloud (recommended)

1. Push this repo to GitHub.
2. Go to <https://share.streamlit.io>, click **New app**, point it at the repo
   and at `app.py`.
3. Open **Settings → Secrets** and paste the contents of
   `.streamlit/secrets.toml.example` with your real `HF_TOKEN` value.
4. Click **Deploy**. The first build takes a couple of minutes; subsequent
   updates redeploy automatically on `git push`.

### HuggingFace Spaces

1. Create a new Space, SDK = **Streamlit**.
2. Push this repo into the Space.
3. In **Settings → Variables and secrets**, add `HF_TOKEN` as a secret.

## Tests

```bash
pytest
```

The validator suite covers happy paths plus rejection of `DROP`/`DELETE`/`UPDATE`/
`INSERT`, multi-statement input, unknown tables, unknown columns, alias references,
and CTE aliases.

## Project layout

```
bi-converse/
├── app.py                  Streamlit UI, orchestration, retry loop
├── .streamlit/
│   ├── config.toml         Dark theme + violet accent
│   └── secrets.toml.example  Template for cloud secrets
├── src/
│   ├── seed.py             Downloads Chinook on first run
│   ├── db.py               SQLAlchemy engine, schema introspection
│   ├── llm.py              HF InferenceClient + schema-aware prompt
│   ├── sql_validator.py    sqlglot safety + EXPLAIN dry-run
│   ├── visualize.py        Result-shape → Plotly chart heuristic
│   └── ui.py               Theme injection, hero, answer/list cards
└── tests/
    └── test_validator.py
```

## Design notes

- **Schema-aware prompting.** `db.introspect` dumps tables, column types, primary
  keys, foreign keys, and a sample row per table. `db.render_schema` formats
  that into compact `CREATE TABLE`-style DDL the model can ground on.
- **Defense in depth.** The model is instructed to emit SELECT-only SQL, but the
  validator does not trust it: `sqlglot` parses the statement, walks the tree for
  forbidden nodes (`Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Pragma`, …),
  whitelists every referenced table and column against the live schema (allowing
  aliases and CTE names), and finally runs `EXPLAIN` to catch anything the parser
  permitted but SQLite would reject.
- **Bounded retry.** When validation or execution fails, the error is appended
  to the next prompt so the model can self-correct. Capped at 2 retries.
- **Shape-aware rendering.** `visualize.pick_chart` picks the right output mode
  for the result shape: single-row → "answer" card, single-column → list,
  temporal + numeric → line, categorical + numeric → bar, two numerics →
  scatter, otherwise → table.
