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
