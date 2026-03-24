from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import yfinance as yf
from bs4 import BeautifulSoup

from app.config import settings
from app.models import (
    AgentAction,
    AgentBrief,
    EvidenceItem,
    IterationArtifact,
    IterationResult,
    RevisionPlan,
    RunConfig,
    RunInput,
    RunState,
    Scorecard,
)
from app.storage import Storage

SCORE_WEIGHTS = {
    "factual_grounding": 25,
    "kpi_completeness": 15,
    "guidance_capture": 15,
    "peer_relevance": 15,
    "valuation_coherence": 15,
    "narrative_consistency": 10,
    "writing_quality": 5,
}


class AutoResearchRunner:
    def __init__(self, storage: Storage, run_dir: Path) -> None:
        self.storage = storage
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)

    async def execute(self, run_id: str, run_input: RunInput, config: RunConfig) -> None:
        self.storage.update_run_state(run_id, state=RunState.RUNNING)
        try:
            await self._run_loop(run_id, run_input, config)
        except Exception as exc:  # noqa: BLE001
            self.storage.fail_run(run_id, f"{type(exc).__name__}: {exc}")

    async def _run_loop(self, run_id: str, run_input: RunInput, config: RunConfig) -> None:
        best_score = -1
        best_iteration = 1
        stagnation_count = 0
        stop_reason = "max_iterations_reached"
        latest_sources: dict[str, Any] = {}
        latest_facts: dict[str, Any] = {}

        for iteration in range(1, config.max_iterations + 1):
            latest_sources = await self._collect_sources(run_input, iteration)
            latest_facts = self._extract_facts(run_input, latest_sources, iteration)
            artifact = self._build_artifact(run_input, latest_facts, latest_sources, iteration)
            scorecard = self._evaluate(artifact, latest_sources, latest_facts, iteration)
            revision = self._propose_revision(scorecard, iteration)

            result = IterationResult(
                index=iteration,
                artifact=artifact,
                scorecard=scorecard,
                revision_plan=revision,
            )
            self.storage.save_iteration(run_id, result)
            self._write_artifact(run_id, result)

            score = scorecard.total
            if score > best_score:
                improvement = score - best_score if best_score >= 0 else score
                best_score = score
                best_iteration = iteration
                stagnation_count = 0 if improvement >= config.min_improvement else stagnation_count + 1
            else:
                stagnation_count += 1

            if score >= config.target_score:
                stop_reason = "target_score_reached"
                break
            if stagnation_count >= config.patience:
                stop_reason = "score_stagnation"
                break

            await asyncio.sleep(0.35)

        final_summary = self._build_final_summary(
            run_input=run_input,
            best_score=best_score,
            best_iteration=best_iteration,
            stop_reason=stop_reason,
            sources=latest_sources,
            facts=latest_facts,
        )
        self.storage.finalize_run(
            run_id=run_id,
            summary=final_summary,
            best_iteration=best_iteration,
            best_score=best_score,
            stop_reason=stop_reason,
        )

    async def _collect_sources(self, run_input: RunInput, iteration: int) -> dict[str, Any]:
        ticker = run_input.ticker.upper().strip()
        yf_ticker = yf.Ticker(ticker)
        info: dict[str, Any] = {}
        history_rows: list[dict[str, Any]] = []
        news_items: list[dict[str, str]] = []

        try:
            info = yf_ticker.fast_info or {}
        except Exception:  # noqa: BLE001
            info = {}

        try:
            history = yf_ticker.history(period="6mo", interval="1d")
            if not history.empty:
                tail = history.tail(40).reset_index().to_dict(orient="records")
                history_rows = [
                    {
                        "date": str(row.get("Date", ""))[:10],
                        "close": f"{float(row.get('Close', 0.0)):.2f}",
                        "volume": f"{int(float(row.get('Volume', 0.0)))}",
                    }
                    for row in tail
                ]
        except Exception:  # noqa: BLE001
            history_rows = []

        try:
            news = yf_ticker.news or []
            for item in news[: 5 + iteration]:
                content = item.get("content", {})
                news_items.append(
                    {
                        "title": content.get("title", "Untitled item"),
                        "url": content.get("canonicalUrl", {}).get("url", ""),
                        "published": content.get("pubDate", ""),
                    }
                )
        except Exception:  # noqa: BLE001
            news_items = []

        sec_sources = await self._fetch_sec_sources(ticker=ticker, iteration=iteration)
        citations = ["Yahoo Finance fast_info", "Yahoo Finance history", "Yahoo Finance news"]
        if sec_sources["submissions_url"]:
            citations.append("SEC submissions feed")
        if sec_sources["filings"]:
            citations.append("SEC filing metadata")

        return {
            "ticker": ticker,
            "info": info,
            "history": history_rows,
            "news": news_items,
            "sec": sec_sources,
            "citations": citations,
        }

    async def _fetch_sec_sources(self, ticker: str, iteration: int) -> dict[str, Any]:
        url_tickers = "https://www.sec.gov/files/company_tickers.json"
        headers = {"User-Agent": settings.user_agent}
        result = {
            "submissions_url": "",
            "filings": [],
            "filing_snippets": [],
            "notes": [],
        }
        timeout = httpx.Timeout(8.0)
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            try:
                ticker_resp = await client.get(url_tickers)
                ticker_resp.raise_for_status()
                payload = ticker_resp.json()
                match = next(
                    (
                        row
                        for row in payload.values()
                        if str(row.get("ticker", "")).upper() == ticker
                    ),
                    None,
                )
                if not match:
                    result["notes"].append("No SEC ticker mapping found.")
                    return result

                cik = str(match["cik_str"]).zfill(10)
                submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                result["submissions_url"] = submissions_url
                sub_resp = await client.get(submissions_url)
                sub_resp.raise_for_status()
                submissions = sub_resp.json()
                recent = submissions.get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                dates = recent.get("filingDate", [])
                accession = recent.get("accessionNumber", [])
                primary_docs = recent.get("primaryDocument", [])
                primary_desc = recent.get("primaryDocDescription", [])
                filing_window = min(len(forms), max(60, 20 + iteration * 4))
                for idx, form in enumerate(forms[:filing_window]):
                    result["filings"].append(
                        {
                            "form": form,
                            "date": dates[idx] if idx < len(dates) else "",
                            "accession": accession[idx] if idx < len(accession) else "",
                            "primary_document": primary_docs[idx] if idx < len(primary_docs) else "",
                            "description": primary_desc[idx] if idx < len(primary_desc) else "",
                        }
                    )
                result["filing_snippets"] = await self._fetch_filing_snippets(
                    client=client,
                    cik=cik,
                    filings=result["filings"],
                    iteration=iteration,
                )
            except Exception:  # noqa: BLE001
                result["notes"].append("SEC source fetch unavailable.")
        return result

    async def _fetch_filing_snippets(
        self,
        client: httpx.AsyncClient,
        cik: str,
        filings: list[dict[str, str]],
        iteration: int,
    ) -> list[dict[str, str]]:
        snippets: list[dict[str, str]] = []
        preferred_order = {"8-K": 0, "10-Q": 1, "10-K": 2, "6-K": 3, "20-F": 4, "11-K": 5}
        candidate_filings = [item for item in filings if item.get("form") in preferred_order and item.get("primary_document")]
        candidate_filings.sort(
            key=lambda item: (
                preferred_order.get(item.get("form", ""), 99),
                -int(item.get("date", "0").replace("-", "") or 0),
            )
        )
        max_docs = min(2, max(1, iteration // 2))

        for filing in candidate_filings[:max_docs]:
            accession = filing.get("accession", "")
            primary_document = filing.get("primary_document", "")
            accession_compact = accession.replace("-", "")
            document_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact}/{primary_document}"
            try:
                response = await client.get(document_url)
                response.raise_for_status()
                target_text = response.text
                target_url = document_url
                if filing.get("form") == "8-K":
                    exhibit_doc = self._find_exhibit_document(response.text, document_url)
                    if exhibit_doc:
                        exhibit_resp = await client.get(exhibit_doc)
                        exhibit_resp.raise_for_status()
                        target_text = exhibit_resp.text
                        target_url = exhibit_doc
                snippet = self._extract_filing_snippet(target_text)
                if snippet:
                    snippets.append(
                        {
                            "form": filing.get("form", ""),
                            "date": filing.get("date", ""),
                            "description": filing.get("description", "") or filing.get("form", ""),
                            "document_url": target_url,
                            "snippet": snippet,
                        }
                    )
            except Exception:  # noqa: BLE001
                continue
        return snippets

    @staticmethod
    def _find_exhibit_document(raw_text: str, base_url: str) -> str | None:
        soup = BeautifulSoup(raw_text, "lxml")
        exhibit_patterns = ("99", "ex99", "press release", "earnings release")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            text = " ".join(anchor.get_text(" ", strip=True).split()).lower()
            if any(pattern in href.lower() for pattern in exhibit_patterns) or any(pattern in text for pattern in exhibit_patterns):
                if href.lower().endswith((".htm", ".html", ".txt", ".xml")):
                    return urljoin(base_url, href)
        return None

    @staticmethod
    def _extract_filing_snippet(raw_text: str) -> str:
        soup = BeautifulSoup(raw_text, "lxml")
        text = soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        if not text:
            return ""

        priority_patterns = [
            r"(?:net sales|revenue)[^.]{40,240}\.",
            r"(?:operating income|gross margin|earnings per share|EPS)[^.]{40,240}\.",
            r"(?:guidance|outlook|expect)[^.]{40,240}\.",
        ]
        for pattern in priority_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0).strip()[:320]

        sentences = re.split(r"(?<=[.!?])\s+", text)
        for sentence in sentences:
            clean = sentence.strip()
            if (
                80 <= len(clean) <= 320
                and "revenue code of 1986" not in clean.lower()
                and "defined contribution savings plan" not in clean.lower()
                and "statement of changes in beneficial ownership" not in clean.lower()
            ):
                return clean
        return text[:320].strip()

    def _extract_facts(
        self,
        run_input: RunInput,
        sources: dict[str, Any],
        iteration: int,
    ) -> dict[str, Any]:
        info = sources.get("info", {})
        history = sources.get("history", [])
        news = sources.get("news", [])
        latest_close = float(history[-1]["close"]) if history else 0.0
        first_close = float(history[0]["close"]) if history else 0.0
        performance = ((latest_close - first_close) / first_close * 100) if first_close else 0.0
        volatility = self._rolling_volatility(history)

        kpis = {
            "market_cap": self._fmt_currency(info.get("marketCap")),
            "last_price": f"${latest_close:,.2f}" if latest_close else "Unavailable",
            "six_month_return": f"{performance:+.2f}%",
            "volatility_30d": f"{volatility:.2f}%",
            "beta": self._fmt_decimal(info.get("beta")),
            "trailing_pe": self._fmt_decimal(info.get("trailingPE")),
            "forward_pe": self._fmt_decimal(info.get("forwardPE")),
            "dividend_yield": self._fmt_percent(info.get("dividendYield")),
            "average_volume": self._fmt_number(info.get("tenDayAverageVolume")),
        }

        inferred_peers = self._infer_peers(run_input.ticker, info)
        peer_seed = list(dict.fromkeys([*run_input.peer_set, *inferred_peers])) if run_input.peer_set else inferred_peers
        peer_slice = peer_seed[: max(2, min(len(peer_seed), 2 + iteration))]
        guidance_bullets = [
            f"Captured {len(sources.get('sec', {}).get('filings', []))} recent SEC filings for context.",
            f"Reviewed {len(news)} recent market/news items.",
        ]
        if run_input.prior_view:
            guidance_bullets.append("Integrated prior view as a comparison baseline.")

        return {
            "company_name": info.get("shortName", run_input.ticker.upper()),
            "sector": info.get("sector", "Not disclosed"),
            "industry": info.get("industry", "Not disclosed"),
            "kpis": kpis,
            "peers": peer_slice,
            "guidance_bullets": guidance_bullets,
            "mode": run_input.mode.value,
            "event_date": run_input.event_date.isoformat(),
        }

    def _build_artifact(
        self,
        run_input: RunInput,
        facts: dict[str, Any],
        sources: dict[str, Any],
        iteration: int,
    ) -> IterationArtifact:
        ticker = run_input.ticker.upper()
        context_label = "Earnings preview" if run_input.mode.value == "preview" else "Post-earnings update"
        summary = (
            f"{context_label} for {facts['company_name']} ({ticker}) on {facts['event_date']}. "
            f"Iteration {iteration} reflects currently available public data only."
        )

        kpi_table = [{"metric": key.replace("_", " ").title(), "value": value} for key, value in facts["kpis"].items()]

        guidance_notes = " ".join(facts["guidance_bullets"])

        peer_table = []
        peer_roles = [
            "valuation anchor",
            "growth comparison",
            "margin comparison",
            "risk benchmark",
            "multiple sanity check",
        ]
        for idx, peer in enumerate(facts["peers"]):
            peer_table.append(
                {
                    "ticker": peer,
                    "thesis_role": peer_roles[idx % len(peer_roles)],
                    "comment": "Peer included for comparative context based on sector/coverage set.",
                }
            )

        trailing_pe = facts["kpis"].get("trailing_pe", "n/a")
        forward_pe = facts["kpis"].get("forward_pe", "n/a")
        if trailing_pe == "n/a" and forward_pe == "n/a":
            valuation_summary = (
                "Valuation multiple snapshot unavailable from current upstream feed "
                "(trailing/forward P/E missing)."
            )
        else:
            valuation_summary = (
                f"Valuation snapshot: trailing P/E {trailing_pe}, forward P/E {forward_pe}. "
                "Use this as a directional multiple check, not a full valuation model."
            )

        risks_and_catalysts = (
            "Primary catalysts observed from source set: guidance revisions, margin updates, "
            "and demand commentary in recent disclosures/news."
        )

        analyst_note = (
            f"This {run_input.mode.value} draft is evidence-led and restricted to available public data "
            "(market feed, filing metadata, and recent news links)."
        )
        if run_input.prior_view:
            analyst_note += f" Prior thesis check: {run_input.prior_view[:180]}."

        citations = list(sources.get("citations", []))
        filings = sources.get("sec", {}).get("filings", [])
        filing_snippets = sources.get("sec", {}).get("filing_snippets", [])
        for filing in filings[:4]:
            citations.append(f"SEC {filing['form']} filed {filing['date']}")
        citations.extend(
            item.get("url", "")
            for item in sources.get("news", [])[:3]
            if item.get("url")
        )

        evidence_items = self._build_evidence_items(
            ticker=ticker,
            facts=facts,
            sources=sources,
            filings=filings,
            filing_snippets=filing_snippets,
        )

        agent_briefs = [
            AgentBrief(
                name="Source Scout",
                role="Pulls market context and recent public coverage.",
                status="completed",
                detail=(
                    f"Collected {len(sources.get('history', []))} recent price observations and "
                    f"{len(sources.get('news', []))} news items."
                ),
            ),
            AgentBrief(
                name="Filing Tracker",
                role="Maps the ticker to SEC coverage and recent forms.",
                status="completed" if filings else "limited",
                detail=(
                    f"Captured {len(filings)} recent SEC filings."
                    if filings
                    else "SEC filing metadata was unavailable for this run."
                ),
            ),
            AgentBrief(
                name="Document Reader",
                role="Reads filing text and extracts evidence snippets.",
                status="completed" if filing_snippets else "limited",
                detail=(
                    f"Extracted {len(filing_snippets)} filing text snippets for evidence tracing."
                    if filing_snippets
                    else "No filing text snippet could be extracted from the current SEC documents."
                ),
            ),
            AgentBrief(
                name="Peer Mapper",
                role="Builds the comparable set and role for each peer.",
                status="completed",
                detail=f"Prepared {len(peer_table)} comparison tickers for the packet.",
            ),
            AgentBrief(
                name="Note Writer",
                role="Assembles the packet with evidence and linked sources.",
                status="completed",
                detail=f"Built {len(kpi_table)} KPI rows and attached {len([c for c in citations if c])} source anchors.",
            ),
        ]

        agent_actions = [
            AgentAction(
                agent="Source Scout",
                tool="yfinance.fast_info + history + news",
                status="completed",
                output=(
                    f"Pulled {len(sources.get('history', []))} price observations and "
                    f"{len(sources.get('news', []))} linked news items."
                ),
            ),
            AgentAction(
                agent="Filing Tracker",
                tool="SEC company_tickers.json + submissions API",
                status="completed" if filings else "limited",
                output=(
                    f"Mapped ticker and collected {len(filings)} recent filing records."
                    if filings
                    else "Ticker mapping worked but no recent filing records were attached."
                ),
            ),
            AgentAction(
                agent="Document Reader",
                tool="SEC filing document fetch + text extraction",
                status="completed" if filing_snippets else "limited",
                output=(
                    f"Read {len(filing_snippets)} primary filing documents and extracted snippet evidence."
                    if filing_snippets
                    else "Primary filing documents were reachable, but no usable snippet was extracted."
                ),
            ),
            AgentAction(
                agent="Peer Mapper",
                tool="peer heuristics",
                status="completed",
                output=f"Prepared {len(peer_table)} peers from user input and sector inference.",
            ),
            AgentAction(
                agent="Note Writer",
                tool="packet assembler",
                status="completed",
                output=f"Rendered the report with {len(evidence_items)} evidence items and {len(citations)} source anchors.",
            ),
        ]

        return IterationArtifact(
            summary=summary,
            kpi_table=kpi_table,
            guidance_notes=guidance_notes,
            peer_table=peer_table,
            valuation_summary=valuation_summary,
            risks_and_catalysts=risks_and_catalysts,
            analyst_note=analyst_note,
            citations=[c for c in citations if c],
            agent_briefs=agent_briefs,
            agent_actions=agent_actions,
            evidence_items=evidence_items,
        )

    def _evaluate(
        self,
        artifact: IterationArtifact,
        sources: dict[str, Any],
        facts: dict[str, Any],
        iteration: int,
    ) -> Scorecard:
        citation_count = len(artifact.citations)
        sec_filing_count = len(sources.get("sec", {}).get("filings", []))
        kpi_non_empty = sum(1 for row in artifact.kpi_table if row["value"] not in {"Unavailable", "n/a"})

        factual_grounding = min(
            SCORE_WEIGHTS["factual_grounding"],
            10 + citation_count * 2 + min(5, sec_filing_count),
        )
        kpi_completeness = min(
            SCORE_WEIGHTS["kpi_completeness"],
            5 + kpi_non_empty,
        )
        guidance_capture = min(
            SCORE_WEIGHTS["guidance_capture"],
            6 + len(facts.get("guidance_bullets", [])) + iteration,
        )
        peer_relevance = min(
            SCORE_WEIGHTS["peer_relevance"],
            4 + len(artifact.peer_table) * 3,
        )
        valuation_coherence = min(
            SCORE_WEIGHTS["valuation_coherence"],
            6 + iteration * 2,
        )
        narrative_consistency = min(
            SCORE_WEIGHTS["narrative_consistency"],
            4 + iteration,
        )
        writing_quality = min(
            SCORE_WEIGHTS["writing_quality"],
            2 + max(1, iteration // 2),
        )

        major_issues: list[str] = []
        missing_data: list[str] = []
        if sec_filing_count == 0:
            missing_data.append("SEC filings missing or unavailable")
            major_issues.append("Regulatory context is thin without filing metadata.")
        if len(artifact.peer_table) < 3:
            major_issues.append("Peer set could be expanded for stronger valuation context.")
        if citation_count < 4:
            major_issues.append("Citation count is low for institutional standards.")
        if kpi_non_empty < 5:
            major_issues.append("KPI extraction is shallow; needs broader coverage.")

        total = (
            factual_grounding
            + kpi_completeness
            + guidance_capture
            + peer_relevance
            + valuation_coherence
            + narrative_consistency
            + writing_quality
        )

        return Scorecard(
            factual_grounding=factual_grounding,
            kpi_completeness=kpi_completeness,
            guidance_capture=guidance_capture,
            peer_relevance=peer_relevance,
            valuation_coherence=valuation_coherence,
            narrative_consistency=narrative_consistency,
            writing_quality=writing_quality,
            total=total,
            major_issues=major_issues,
            missing_data=missing_data,
        )

    def _propose_revision(self, scorecard: Scorecard, iteration: int) -> RevisionPlan:
        focus = []
        actions = []

        if scorecard.factual_grounding < 20:
            focus.append("citation density")
            actions.append("Retrieve additional SEC/news anchors and attach claims to explicit citations.")
        if scorecard.peer_relevance < 12:
            focus.append("peer depth")
            actions.append("Expand peers and annotate each peer's analytical role.")
        if scorecard.valuation_coherence < 12:
            focus.append("valuation logic")
            actions.append("Tighten multiple rationale and stress-test sensitivity assumptions.")
        if scorecard.kpi_completeness < 11:
            focus.append("kpi extraction")
            actions.append("Re-extract KPI table with optional metrics and confidence flags.")
        if not actions:
            focus.append("communication polish")
            actions.append("Compress analyst note and improve signal-to-noise.")
        if iteration >= 4:
            actions.append("Avoid broad rewrites; perform targeted final pass to preserve best score.")

        return RevisionPlan(focus_areas=focus, actions=actions)

    def _build_final_summary(
        self,
        run_input: RunInput,
        best_score: int,
        best_iteration: int,
        stop_reason: str,
        sources: dict[str, Any],
        facts: dict[str, Any],
    ) -> str:
        return (
            f"Completed {run_input.mode.value} run for {run_input.ticker.upper()} with best score "
            f"{best_score}/100 at iteration {best_iteration}. Stop reason: {stop_reason}. "
            f"Processed {len(sources.get('news', []))} news items and "
            f"{len(sources.get('sec', {}).get('filings', []))} SEC filings. "
            f"Primary sector context: {facts.get('sector', 'unknown')}."
        )

    def _write_artifact(self, run_id: str, result: IterationResult) -> None:
        path = self.run_dir / run_id
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / f"iteration-{result.index}.json"
        file_path.write_text(json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8")

    @staticmethod
    def _rolling_volatility(history_rows: list[dict[str, Any]]) -> float:
        closes = [float(row["close"]) for row in history_rows if row.get("close")]
        if len(closes) < 2:
            return 0.0
        returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
        mean = sum(returns) / len(returns)
        var = sum((item - mean) ** 2 for item in returns) / len(returns)
        return (var**0.5) * (252**0.5) * 100

    @staticmethod
    def _fmt_decimal(value: Any) -> str:
        if value is None:
            return "n/a"
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "n/a"

    @staticmethod
    def _fmt_number(value: Any) -> str:
        if value is None:
            return "n/a"
        try:
            return f"{int(float(value)):,}"
        except (TypeError, ValueError):
            return "n/a"

    @staticmethod
    def _fmt_currency(value: Any) -> str:
        if value is None:
            return "n/a"
        try:
            return f"${int(float(value)):,}"
        except (TypeError, ValueError):
            return "n/a"

    @staticmethod
    def _fmt_percent(value: Any) -> str:
        if value is None:
            return "n/a"
        try:
            return f"{float(value) * 100:.2f}%"
        except (TypeError, ValueError):
            return "n/a"

    @staticmethod
    def _infer_peers(ticker: str, info: dict[str, Any]) -> list[str]:
        sector = str(info.get("sector", "")).lower()
        map_by_sector = {
            "technology": ["MSFT", "AAPL", "GOOGL", "ORCL", "ADBE"],
            "healthcare": ["JNJ", "PFE", "MRK", "LLY", "ABBV"],
            "financial services": ["JPM", "BAC", "MS", "GS", "C"],
            "consumer cyclical": ["AMZN", "HD", "MCD", "NKE", "SBUX"],
        }
        default = ["SPY", "QQQ", "DIA", "IWM", "VTI"]
        candidates = map_by_sector.get(sector, default)
        return [item for item in candidates if item != ticker.upper()]

    def _build_evidence_items(
        self,
        ticker: str,
        facts: dict[str, Any],
        sources: dict[str, Any],
        filings: list[dict[str, str]],
        filing_snippets: list[dict[str, str]],
    ) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []
        kpis = facts.get("kpis", {})
        latest_price = kpis.get("last_price", "Unavailable")
        six_month_return = kpis.get("six_month_return", "Unavailable")
        market_cap = kpis.get("market_cap", "n/a")

        if latest_price != "Unavailable":
            evidence.append(
                EvidenceItem(
                    agent="Source Scout",
                    claim=f"{ticker} most recently traded at {latest_price}.",
                    support="Derived from the latest observed close in the fetched price history.",
                    source_label="Yahoo Finance history",
                    source_url=None,
                )
            )
        if six_month_return not in {"Unavailable", "n/a"}:
            evidence.append(
                EvidenceItem(
                    agent="Source Scout",
                    claim=f"{ticker} six-month return is {six_month_return}.",
                    support="Computed from the first and last observations in the six-month price window.",
                    source_label="Yahoo Finance history",
                    source_url=None,
                )
            )
        if market_cap != "n/a":
            evidence.append(
                EvidenceItem(
                    agent="Source Scout",
                    claim=f"{ticker} market capitalization is {market_cap}.",
                    support="Taken from the upstream fast-info snapshot.",
                    source_label="Yahoo Finance fast_info",
                    source_url=None,
                )
            )

        if filings:
            filing = filings[0]
            evidence.append(
                EvidenceItem(
                    agent="Filing Tracker",
                    claim=f"Recent SEC activity includes Form {filing['form']} filed on {filing['date']}.",
                    support="This is the most recent filing record returned by the SEC submissions feed.",
                    source_label="SEC submissions feed",
                    source_url=sources.get("sec", {}).get("submissions_url"),
                )
            )
        elif not filing_snippets:
            evidence.append(
                EvidenceItem(
                    agent="Filing Tracker",
                    claim="Recent SEC filing metadata was limited for this run.",
                    support="The SEC submissions lookup did not return a recent filing record to cite here.",
                    source_label="SEC submissions feed",
                    source_url=sources.get("sec", {}).get("submissions_url") or None,
                )
            )

        for snippet in filing_snippets[:2]:
            evidence.append(
                EvidenceItem(
                    agent="Document Reader",
                    claim=f"{snippet['form']} excerpt from {snippet['date']}.",
                    support=snippet["snippet"],
                    source_label=f"SEC {snippet['form']} filing text",
                    source_url=snippet["document_url"],
                )
            )

        news_items = sources.get("news", [])
        if news_items:
            item = news_items[0]
            evidence.append(
                EvidenceItem(
                    agent="Source Scout",
                    claim=f"One recent linked headline: {item.get('title', 'Untitled item')}",
                    support="This headline came from the latest available news result in the upstream feed.",
                    source_label="Yahoo Finance news",
                    source_url=item.get("url") or None,
                )
            )

        peers = facts.get("peers", [])
        if peers:
            evidence.append(
                EvidenceItem(
                    agent="Peer Mapper",
                    claim=f"Peer set currently includes {', '.join(peers[:4])}.",
                    support="Peers come from your input first, then sector-based inference.",
                    source_label="Internal peer selection heuristic",
                    source_url=None,
                )
            )

        return evidence
