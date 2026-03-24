from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.models import (
    AgentAction,
    AgentBrief,
    EvidenceItem,
    IterationArtifact,
    RevisionPlan,
    RunConfig,
    RunInput,
    RunMode,
    Scorecard,
)
from app.pipeline import AutoResearchRunner
from app.storage import Storage


class ScriptedRunner(AutoResearchRunner):
    def __init__(self, storage: Storage, run_dir: Path, scripted_scores: list[int]) -> None:
        super().__init__(storage=storage, run_dir=run_dir)
        self._scores = scripted_scores

    async def _collect_sources(self, run_input: RunInput, iteration: int):  # noqa: ANN001
        return {"news": [], "sec": {"filings": []}, "citations": ["test"]}

    def _extract_facts(self, run_input: RunInput, sources, iteration: int):  # noqa: ANN001
        return {"sector": "Technology"}

    def _build_artifact(self, run_input: RunInput, facts, sources, iteration: int):  # noqa: ANN001
        return IterationArtifact(
            summary=f"Iteration {iteration}",
            kpi_table=[],
            guidance_notes="",
            peer_table=[],
            valuation_summary="",
            risks_and_catalysts="",
            analyst_note="",
            citations=["test"],
            agent_briefs=[
                AgentBrief(
                    name="Source Scout",
                    role="Collects source inputs.",
                    status="completed",
                    detail="Collected test inputs.",
                )
            ],
            agent_actions=[
                AgentAction(
                    agent="Source Scout",
                    tool="fixture",
                    status="completed",
                    output="Loaded the scripted fixture set.",
                )
            ],
            evidence_items=[
                EvidenceItem(
                    agent="Source Scout",
                    claim="Fixture evidence is available.",
                    support="One deterministic test source was loaded.",
                    source_label="test fixture",
                    source_url=None,
                )
            ],
        )

    def _evaluate(self, artifact, sources, facts, iteration: int):  # noqa: ANN001
        score = self._scores[iteration - 1]
        return Scorecard(
            factual_grounding=10,
            kpi_completeness=10,
            guidance_capture=10,
            peer_relevance=10,
            valuation_coherence=10,
            narrative_consistency=10,
            writing_quality=5,
            total=score,
            major_issues=[],
            missing_data=[],
        )

    def _propose_revision(self, scorecard: Scorecard, iteration: int):  # noqa: ARG002
        return RevisionPlan(focus_areas=["test"], actions=["test"])


class LLMRunner(AutoResearchRunner):
    def __init__(self, storage: Storage, run_dir: Path) -> None:
        super().__init__(storage=storage, run_dir=run_dir)
        self._llm_enabled = True
        self._llm_model = "gpt-5.4"

    async def _collect_sources(self, run_input: RunInput, iteration: int):  # noqa: ANN001
        return {
            "news": [{"title": "Revenue outlook in focus", "url": "https://example.com/news", "published": "2026-03-24"}],
            "history": [{"date": "2026-03-01", "close": "100.0", "volume": "1"}, {"date": "2026-03-24", "close": "110.0", "volume": "1"}],
            "info": {"marketCap": 1000000, "sector": "Technology", "shortName": "Apple Inc."},
            "sec": {
                "filings": [{"form": "8-K", "date": "2026-03-20", "description": "Current report"}],
                "filing_snippets": [
                    {
                        "form": "8-K",
                        "date": "2026-03-20",
                        "description": "Current report",
                        "snippet": "Revenue increased year over year and management reiterated margin discipline.",
                        "document_url": "https://example.com/8k",
                    }
                ],
                "submissions_url": "https://example.com/submissions",
            },
            "citations": ["Yahoo Finance history", "SEC submissions feed"],
        }

    def _extract_facts(self, run_input: RunInput, sources, iteration: int):  # noqa: ANN001
        return {
            "company_name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "kpis": {
                "market_cap": "$1,000,000",
                "last_price": "$110.00",
                "six_month_return": "+10.00%",
                "volatility_30d": "12.00%",
                "beta": "1.10",
                "trailing_pe": "24.00",
                "forward_pe": "22.00",
                "dividend_yield": "0.50%",
                "average_volume": "1,000,000",
            },
            "peers": ["MSFT", "GOOGL", "AMZN"],
            "guidance_bullets": ["Captured one filing snippet.", "Reviewed one recent news item."],
            "mode": run_input.mode.value,
            "event_date": run_input.event_date.isoformat(),
        }

    async def _generate_llm_sections(self, run_input: RunInput, facts, sources, artifact, iteration: int):  # noqa: ANN001
        return {
            "summary": f"GPT summary for {run_input.ticker.upper()} iteration {iteration}.",
            "analyst_note": "GPT-5.4 synthesized the note from the supplied public sources.",
            "guidance_notes": "Management tone remained constructive in the supplied filing snippet.",
            "valuation_summary": "GPT-5.4 framed valuation as a directional cross-check, not a full model.",
            "risks_and_catalysts": "Key watch items are demand durability, margins, and guidance follow-through.",
            "peer_table": [
                {
                    "ticker": "MSFT",
                    "thesis_role": "quality benchmark",
                    "comment": "Used as a profitability and quality comparison anchor.",
                },
                {
                    "ticker": "GOOGL",
                    "thesis_role": "growth benchmark",
                    "comment": "Used as a growth and ad-cycle comparison point.",
                },
            ],
        }


def _seed_run(storage: Storage, run_id: str) -> tuple[RunInput, RunConfig]:
    run_input = RunInput(
        ticker="AAPL",
        mode=RunMode.REVIEW,
        event_date=date(2026, 3, 24),
        peer_set=["MSFT", "GOOGL"],
    )
    config = RunConfig(max_iterations=5, target_score=85, min_improvement=2, patience=2)
    storage.create_run(run_id=run_id, payload=run_input, config=config)
    return run_input, config


@pytest.mark.asyncio
async def test_stops_when_target_score_reached(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    runner = ScriptedRunner(storage, tmp_path / "runs", scripted_scores=[90, 91, 92])
    run_input, config = _seed_run(storage, run_id="target-stop")

    await runner.execute("target-stop", run_input, config)
    run = storage.get_run("target-stop")
    iterations = storage.list_iterations("target-stop")

    assert run is not None
    assert run.stop_reason == "target_score_reached"
    assert run.best_score == 90
    assert run.best_iteration == 1
    assert len(iterations) == 1


@pytest.mark.asyncio
async def test_stagnation_stops_and_retains_best_iteration(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    runner = ScriptedRunner(storage, tmp_path / "runs", scripted_scores=[70, 71, 71, 70, 69])
    run_input, config = _seed_run(storage, run_id="stagnation-stop")

    await runner.execute("stagnation-stop", run_input, config)
    run = storage.get_run("stagnation-stop")
    iterations = storage.list_iterations("stagnation-stop")

    assert run is not None
    assert run.stop_reason == "score_stagnation"
    assert run.best_score == 71
    assert run.best_iteration == 2
    assert len(iterations) == 3


@pytest.mark.asyncio
async def test_llm_note_writer_updates_packet_and_trace(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "app.db")
    runner = LLMRunner(storage, tmp_path / "runs")
    run_input, config = _seed_run(storage, run_id="llm-run")
    config = RunConfig(max_iterations=2, target_score=1, min_improvement=2, patience=2)

    await runner.execute("llm-run", run_input, config)
    run = storage.get_run("llm-run")
    iterations = storage.list_iterations("llm-run")

    assert run is not None
    assert run.stop_reason == "target_score_reached"
    assert len(iterations) == 1
    artifact = iterations[0].artifact
    note_writer = next(item for item in artifact.agent_actions if item.agent == "Note Writer")
    assert artifact.analyst_note == "GPT-5.4 synthesized the note from the supplied public sources."
    assert artifact.summary == "GPT summary for AAPL iteration 1."
    assert note_writer.tool == "OpenAI Responses API (gpt-5.4)"
    assert note_writer.status == "completed"
