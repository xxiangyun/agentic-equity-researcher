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

## Design goal

The agent loop is intentionally simple.

This project is closer to a fixed research pipeline than a general-purpose autonomous planner:

1. collect public sources
2. extract structured facts and filing snippets
3. draft the packet
4. optionally let GPT-5.4 rewrite the narrative sections
5. score the result and retry a small number of times

That keeps the behavior easier to inspect, debug, and explain in a portfolio setting.

## What it uses

The app can run in two modes:

- public-data mode with no OpenAI key
- GPT-5.4 synthesis mode when `AUTO_RESEARCH_OPENAI_API_KEY` or `OPENAI_API_KEY` is set

Both modes run on:

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
6. if an OpenAI key is configured, sends the structured facts and evidence bundle to GPT-5.4 through the Responses API
7. scores the result against a fixed rubric
8. retries a few times with the same fixed loop
9. keeps the best-scoring version and shows it on the run page

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
- `Note Writer`: final packet assembly, with GPT-5.4 synthesis when configured

## Reference

This project is informed by [virattt/dexter](https://github.com/virattt/dexter), which describes itself as an autonomous financial research agent with task planning, autonomous execution, self-validation, and loop safety. Our implementation is intentionally much simpler: fixed research steps, fixed data sources, fixed scoring, and a small retry budget instead of an open-ended planning loop.

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

To enable GPT-5.4 synthesis:

```bash
export AUTO_RESEARCH_OPENAI_API_KEY=your_key_here
uv run uvicorn app.main:app --reload
```

The app also accepts the standard `OPENAI_API_KEY` environment variable.

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
- `AUTO_RESEARCH_OPENAI_API_KEY`
- `AUTO_RESEARCH_OPENAI_BASE_URL`
- `AUTO_RESEARCH_OPENAI_MODEL`
- `AUTO_RESEARCH_OPENAI_REASONING_EFFORT`
- `AUTO_RESEARCH_OPENAI_TIMEOUT_SECONDS`

## Stop rules

Default run controls:

- `max_iterations = 5`
- `target_score = 85`
- `min_improvement = 2`
- `patience = 2`

## Current limitations

- This is not a Bloomberg-quality research stack.
- It does not yet ingest full earnings call transcripts.
- GPT-5.4 currently powers narrative synthesis only; source retrieval and scoring remain local workflow steps.
- Valuation is still lightweight and should be read as directional context, not a full model.
- Filing snippet quality depends on what recent SEC documents are available for the ticker.
- Some tickers will still produce weak evidence if their recent filings are mostly insider forms or administrative filings.

## Notes

- `uv` is the recommended way to run the project and the repo now includes a `pyproject.toml`.
- SEC requests work better with a real contactable user-agent string.
- The README only documents behavior that is implemented in the current codebase.
