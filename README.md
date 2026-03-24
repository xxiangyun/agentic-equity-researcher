# Agentic Equity Researcher

Agentic equity research app for one ticker at a time.

![App screenshot](docs/app-fullscreen.png)

## What it does

This app runs a research workflow for a single public company in either `preview` or `review` mode and produces a research packet in the browser.

The packet includes:

- an analyst note
- a KPI snapshot
- a valuation view
- comparison tickers
- linked source references
- an evidence ledger
- an agent trace

## What it uses

The current build does **not** need OpenAI keys or third-party finance API keys.

It runs on:

- public Yahoo Finance access through `yfinance`
- public SEC endpoints
- a local FastAPI server that runs the workflow in the background

## How it works

When you submit the form on the homepage, the app:

1. creates a run in the local database
2. starts a background research job on the FastAPI server
3. collects market context, SEC filings, and linked news
4. extracts structured facts and filing snippets
5. builds a research packet
6. scores the result against a fixed rubric
7. iterates until it hits a stop rule
8. keeps the best-scoring version and shows it on the run page

The run page then shows:

- the research packet first
- the research team
- the evidence ledger with filing snippets when available
- the agent trace
- iteration history as secondary diagnostics

## Current research agents

- `Source Scout`: market history and linked news
- `Filing Tracker`: SEC mapping and recent forms
- `Document Reader`: filing text and `Exhibit 99` snippet extraction
- `Peer Mapper`: comparable set construction
- `Note Writer`: final packet assembly

## Public data sources

- Yahoo Finance `fast_info`
- Yahoo Finance price history
- Yahoo Finance linked news feed
- SEC `company_tickers.json`
- SEC submissions JSON feed
- SEC filing documents from EDGAR archives

## Good tickers to try

The current app works best with large US companies that have active SEC coverage and stable public market data.

Examples:

- `MSFT`
- `AAPL`
- `TSLA`
- `JPM`
- `XOM`

## Running locally

Recommended with `uv`:

```bash
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Fallback without `uv`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Running tests

Recommended with `uv`:

```bash
uv run pytest -q
```

Fallback:

```bash
source .venv/bin/activate
pytest -q
```

## Configuration

Environment variables use the `AUTO_RESEARCH_` prefix.

Available settings in code right now:

- `AUTO_RESEARCH_USER_AGENT`
- `AUTO_RESEARCH_MAX_ITERATIONS`
- `AUTO_RESEARCH_TARGET_SCORE`
- `AUTO_RESEARCH_MIN_IMPROVEMENT`
- `AUTO_RESEARCH_PATIENCE`

## Stop rules

Default run controls:

- `max_iterations = 5`
- `target_score = 85`
- `min_improvement = 2`
- `patience = 2`

## Current limitations

- This is not a Bloomberg-quality research stack.
- It does not yet ingest full earnings call transcripts.
- It does not yet use an LLM.
- Valuation is still lightweight and should be read as directional context, not a full model.
- Filing snippet quality depends on what recent SEC documents are available for the ticker.
- Some tickers will still produce weak evidence if their recent filings are mostly insider forms or administrative filings.

## Notes

- `uv` is the recommended way to run the project and the repo now includes a `pyproject.toml`.
- SEC requests work better with a real contactable user-agent string.
- The README only documents behavior that is implemented in the current codebase.
